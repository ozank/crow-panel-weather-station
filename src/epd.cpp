#include "epd.h"

#include <GxEPD2_BW.h>
#include <SPI.h>

#include "config.h"

namespace epd {

namespace {

// GDEY0213B74: 2.13" 122x250 black/white panel with an SSD1680 controller.
using Panel = GxEPD2_213_GDEY0213B74;
GxEPD2_BW<Panel, Panel::HEIGHT> g_display(Panel(PIN_EPD_CS, PIN_EPD_DC, PIN_EPD_RST, PIN_EPD_BUSY));

}  // namespace

Driver begin() {
  pinMode(PIN_EPD_PWR, OUTPUT);
  digitalWrite(PIN_EPD_PWR, HIGH);
  delay(50);

  SPI.begin(PIN_EPD_SCK, -1, PIN_EPD_MOSI, PIN_EPD_CS);
  g_display.epd2.selectSPI(SPI, SPISettings(4000000, MSBFIRST, SPI_MODE0));
  g_display.init(0, true, 10, false);  // pass 115200 as the first argument for BUSY timing logs
  g_display.setRotation(ROTATE_180 ? 3 : 1);  // landscape, 250 x 122
  Serial.printf("[epd] controller: %s\n", driverName());
  return Driver::SSD1680;
}

void show(const GFXcanvas1 &canvas) {
  GFXcanvas1 &c = const_cast<GFXcanvas1 &>(canvas);
  g_display.setFullWindow();
  g_display.fillScreen(GxEPD_WHITE);
  g_display.drawBitmap(0, 0, c.getBuffer(), WIDTH, HEIGHT, GxEPD_BLACK);
  g_display.display(false);  // full refresh
}

void end() {
  g_display.hibernate();
  SPI.end();
  digitalWrite(PIN_EPD_PWR, LOW);
}

const char *driverName() { return "SSD1680 (GxEPD2)"; }

}  // namespace epd
