#include "epd.h"

#include <SPI.h>
#include <driver/gpio.h>
#include <esp_attr.h>
#include <esp_sleep.h>

#include "config.h"

namespace epd {

namespace {

Driver g_driver = Driver::Unknown;
SPIClass g_spi(FSPI);
const SPISettings kSpi(4000000, MSBFIRST, SPI_MODE0);

// JD79661 computes every refresh from the previous image, so keep it across
// deep sleep. RTC slow memory survives deep sleep but not power loss.
RTC_DATA_ATTR uint8_t g_prevFrame[FRAME_BYTES];
RTC_DATA_ATTR bool g_prevValid = false;
RTC_DATA_ATTR bool g_lutSwapped = false;

uint8_t g_frame[FRAME_BYTES];

// ---- low level --------------------------------------------------------------

void command(uint8_t c) {
  digitalWrite(PIN_EPD_DC, LOW);
  digitalWrite(PIN_EPD_CS, LOW);
  g_spi.transfer(c);
  digitalWrite(PIN_EPD_CS, HIGH);
  digitalWrite(PIN_EPD_DC, HIGH);
}

void data(uint8_t d) {
  digitalWrite(PIN_EPD_DC, HIGH);
  digitalWrite(PIN_EPD_CS, LOW);
  g_spi.transfer(d);
  digitalWrite(PIN_EPD_CS, HIGH);
}

void dataBlock(const uint8_t *buf, size_t len) {
  digitalWrite(PIN_EPD_DC, HIGH);
  digitalWrite(PIN_EPD_CS, LOW);
  for (size_t i = 0; i < len; i++) g_spi.transfer(buf[i]);
  digitalWrite(PIN_EPD_CS, HIGH);
}

void dataFill(uint8_t v, size_t len) {
  digitalWrite(PIN_EPD_DC, HIGH);
  digitalWrite(PIN_EPD_CS, LOW);
  for (size_t i = 0; i < len; i++) g_spi.transfer(v);
  digitalWrite(PIN_EPD_CS, HIGH);
}

bool isBusy() {
  const int level = digitalRead(PIN_EPD_BUSY);
  return g_driver == Driver::JD79661 ? level == LOW : level == HIGH;
}

bool waitIdle(uint32_t timeoutMs = 15000) {
  const uint32_t start = millis();
  while (isBusy()) {
    if (millis() - start > timeoutMs) {
      Serial.println("[epd] BUSY timeout");
      return false;
    }
    delay(2);
  }
  return true;
}

// Waits out a panel refresh (seconds long) in light sleep instead of spinning.
// The CPU wakes when BUSY returns to its idle level; outputs keep their state.
bool waitIdleSleeping(uint32_t timeoutMs = 15000) {
  const gpio_num_t busy = static_cast<gpio_num_t>(PIN_EPD_BUSY);
  const gpio_int_type_t idleLevel =
      g_driver == Driver::JD79661 ? GPIO_INTR_HIGH_LEVEL : GPIO_INTR_LOW_LEVEL;

  delay(1);  // let BUSY assert after the refresh command
  Serial.flush();
  gpio_wakeup_enable(busy, idleLevel);
  esp_sleep_enable_gpio_wakeup();
  esp_sleep_enable_timer_wakeup(200000);  // re-check every 200 ms as a safety net

  const uint32_t start = millis();
  bool ok = true;
  while (isBusy()) {
    if (millis() - start > timeoutMs) {
      Serial.println("[epd] BUSY timeout");
      ok = false;
      break;
    }
    esp_light_sleep_start();
  }

  esp_sleep_disable_wakeup_source(ESP_SLEEP_WAKEUP_GPIO);
  esp_sleep_disable_wakeup_source(ESP_SLEEP_WAKEUP_TIMER);
  gpio_wakeup_disable(busy);
  return ok;
}

void hwReset() {
  digitalWrite(PIN_EPD_RST, HIGH);
  delay(10);
  digitalWrite(PIN_EPD_RST, LOW);
  delay(10);
  digitalWrite(PIN_EPD_RST, HIGH);
  delay(100);
}

// Idle BUSY is LOW on the SSD1680 and HIGH on the JD79661.
Driver detect() {
#if defined(PANEL_DRIVER)
  return static_cast<Driver>(PANEL_DRIVER);
#else
  int high = 0;
  for (int i = 0; i < 10; i++) {
    high += digitalRead(PIN_EPD_BUSY);
    delay(5);
  }
  return high >= 8 ? Driver::JD79661 : Driver::SSD1680;
#endif
}

// ---- SSD1680 (sequence from Elecrow's example code) -------------------------

void ssdInit() {
  waitIdle();
  command(0x12);  // software reset
  waitIdle();

  command(0x01);  // driver output control: 250 gate lines
  data(0xF9); data(0x00); data(0x00);

  command(0x11);  // data entry: X+, Y+
  data(0x03);

  command(0x44);  // RAM X range: 0..15 bytes
  data(0x00); data(0x0F);
  command(0x45);  // RAM Y range: 0..249
  data(0x00); data(0x00); data(0xF9); data(0x00);

  command(0x3C);  // border waveform: white
  data(0x01);

  command(0x18);  // internal temperature sensor
  data(0x80);

  command(0x4E); data(0x00);               // RAM X counter
  command(0x4F); data(0x00); data(0x00);   // RAM Y counter
  waitIdle();
}

void ssdShow() {
  ssdInit();
  command(0x24);  // new image
  dataBlock(g_frame, FRAME_BYTES);
  command(0x4E); data(0x00);
  command(0x4F); data(0x00); data(0x00);
  command(0x26);  // "previous" image, kept equal for any later partial refresh
  dataBlock(g_frame, FRAME_BYTES);

  command(0x22);  // full refresh with OTP waveform
  data(0xF7);
  command(0x20);
  waitIdleSleeping();
}

void ssdSleep() {
  command(0x10);  // deep sleep mode 1
  data(0x01);
  delay(20);
}

// ---- JD79661 (sequence from nacree/ESPHome-CrowPanel-ESP32-2.13) -------------

constexpr size_t LUT_LEN = 56;
// Full-refresh (GC) waveform; the rest of each 56-byte table is zero.
const uint8_t LUT20[] = {0x01, 0x00, 0x14, 0x14, 0x01, 0x00, 0x00, 0x01};
const uint8_t LUT21[] = {0x01, 0x60, 0x14, 0x14, 0x01, 0x00, 0x00, 0x01};
const uint8_t LUT22[] = {0x01, 0x20, 0x14, 0x14, 0x01, 0x00, 0x00, 0x01};
const uint8_t LUT23[] = {0x01, 0x10, 0x14, 0x14, 0x01, 0x00, 0x00, 0x01};
const uint8_t LUT24[] = {0x01, 0x90, 0x14, 0x14, 0x01, 0x00, 0x00, 0x01};

void jdLut(uint8_t reg, const uint8_t *lut, size_t len) {
  command(reg);
  dataBlock(lut, len);
  dataFill(0x00, LUT_LEN - len);
}

void jdInit() {
  command(0x00);  // panel setting
  data(0xF7); data(0x8A);
  command(0x01);  // power setting
  data(0x03); data(0x00); data(0x3F); data(0x3F); data(0x03);
  command(0x03);  // power-off sequence
  data(0x00);
  command(0x06);  // booster soft start
  data(0x27); data(0x27); data(0x2F);
  command(0x30); data(0x0D);  // PLL
  command(0x60); data(0x22);  // TCON
  command(0x82); data(0x07);  // VCOM DC
  command(0xE3); data(0x88);  // power saving
  command(0x41); data(0x00);  // temperature sensor
  command(0x61);              // resolution 128 x 250
  data(NATIVE_W); data(0x00); data(NATIVE_H);
  command(0x65); data(0x00); data(0x00); data(0x00);  // gate/source start
  command(0x50); data(0xD7);  // VCOM and data interval
}

void jdShow() {
  jdInit();

  command(0x10);  // previous image
  if (g_prevValid) dataBlock(g_prevFrame, FRAME_BYTES);
  else dataFill(0xFF, FRAME_BYTES);
  command(0x13);  // new image
  dataBlock(g_frame, FRAME_BYTES);

  jdLut(0x20, LUT20, sizeof(LUT20));
  jdLut(0x21, LUT21, sizeof(LUT21));
  jdLut(0x24, LUT24, sizeof(LUT24));
  // 0x22/0x23 alternate between refreshes to keep the panel DC balanced.
  jdLut(g_lutSwapped ? 0x23 : 0x22, LUT22, sizeof(LUT22));
  jdLut(g_lutSwapped ? 0x22 : 0x23, LUT23, sizeof(LUT23));
  g_lutSwapped = !g_lutSwapped;

  command(0x17);  // display refresh
  data(0xA5);
  waitIdleSleeping();

  memcpy(g_prevFrame, g_frame, FRAME_BYTES);
  g_prevValid = true;
}

void jdSleep() {
  command(0x07);  // deep sleep
  data(0xA5);
  delay(20);
}

// Landscape (x: 0..249, y: 0..121) -> controller RAM.
void packFrame(const GFXcanvas1 &c) {
  memset(g_frame, 0xFF, FRAME_BYTES);
  for (int y = 0; y < HEIGHT; y++) {
    for (int x = 0; x < WIDTH; x++) {
      if (!c.getPixel(x, y)) continue;
      int lx = x, ly = y;
#if ROTATE_180
      lx = WIDTH - 1 - x;
      ly = HEIGHT - 1 - y;
#endif
      const int col = ly;
      const int row = (g_driver == Driver::JD79661) ? lx : (NATIVE_H - 1 - lx);
      g_frame[row * (NATIVE_W / 8) + col / 8] &= ~(0x80 >> (col & 7));
    }
  }
}

}  // namespace

Driver begin() {
  pinMode(PIN_EPD_PWR, OUTPUT);
  digitalWrite(PIN_EPD_PWR, HIGH);
  delay(50);

  pinMode(PIN_EPD_CS, OUTPUT);
  pinMode(PIN_EPD_DC, OUTPUT);
  pinMode(PIN_EPD_RST, OUTPUT);
  pinMode(PIN_EPD_BUSY, INPUT);
  digitalWrite(PIN_EPD_CS, HIGH);
  digitalWrite(PIN_EPD_DC, HIGH);

  g_spi.begin(PIN_EPD_SCK, -1, PIN_EPD_MOSI, -1);
  g_spi.beginTransaction(kSpi);

  hwReset();
  g_driver = detect();
  Serial.printf("[epd] controller: %s\n", driverName());
  return g_driver;
}

void show(const GFXcanvas1 &canvas) {
  packFrame(canvas);
  if (g_driver == Driver::JD79661) jdShow();
  else ssdShow();
}

void end() {
  if (g_driver == Driver::JD79661) jdSleep();
  else ssdSleep();
  g_spi.endTransaction();
  g_spi.end();
  digitalWrite(PIN_EPD_PWR, LOW);
}

const char *driverName() {
  switch (g_driver) {
    case Driver::SSD1680: return "SSD1680";
    case Driver::JD79661: return "JD79661";
    default: return "unknown";
  }
}

}  // namespace epd
