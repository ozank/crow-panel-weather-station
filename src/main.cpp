// CrowPanel ESP32-S3 2.13" e-paper weather station.
//
// Wakes shortly after every hour and redraws the screen from a forecast cached
// in RTC memory, with Wi-Fi off. Every FETCH_HOURS (or when MENU / the dial is
// pressed) it connects to Wi-Fi and downloads a fresh forecast first. The panel
// is only refreshed when the picture actually changed.

#include <Arduino.h>
#include <WiFi.h>
#include <driver/gpio.h>
#include <esp_attr.h>
#include <esp_sleep.h>

#include "clock.h"
#include "config.h"
#include "epd.h"
#include "ui.h"
#include "weather.h"

#if __has_include("secrets.h")
#include "secrets.h"
#else
#error "Copy include/secrets.example.h to include/secrets.h and set your Wi-Fi details"
#endif

// ---- state kept across deep sleep ------------------------------------------------
RTC_DATA_ATTR Forecast g_fc;
RTC_DATA_ATTR bool g_clockSet;
RTC_DATA_ATTR uint32_t g_retryAt;      // unix time of the next retry, 0 = none
RTC_DATA_ATTR uint16_t g_retryMin;     // current retry back-off
RTC_DATA_ATTR uint32_t g_shownHash;    // hash of the image on the panel
RTC_DATA_ATTR uint8_t g_bssid[6];
RTC_DATA_ATTR int32_t g_channel;       // 0 = no cached AP

Forecast g_download;  // scratch, only copied into g_fc on success
GFXcanvas1 g_canvas(epd::WIDTH, epd::HEIGHT);

// ---- Wi-Fi ----------------------------------------------------------------------

bool waitForWifi(uint32_t timeoutMs) {
  const uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED) {
    if (millis() - start > timeoutMs) return false;
    delay(20);
  }
  return true;
}

bool connectWifi() {
  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);

  // Fast path: reuse the channel and BSSID from the last successful connection.
  if (g_channel > 0) {
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD, g_channel, g_bssid, true);
    if (waitForWifi(5000)) return true;
    Serial.println("[wifi] cached AP failed, scanning");
    WiFi.disconnect();
    g_channel = 0;
  }

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  if (!waitForWifi(WIFI_TIMEOUT_MS)) return false;

  g_channel = WiFi.channel();
  memcpy(g_bssid, WiFi.BSSID(), 6);
  return true;
}

void wifiOff() {
  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);
}

// ---- helpers ----------------------------------------------------------------------

uint32_t hashCanvas(GFXcanvas1 &c) {
  const uint8_t *p = c.getBuffer();
  const size_t n = static_cast<size_t>((c.width() + 7) / 8) * c.height();
  uint32_t h = 2166136261u;  // FNV-1a
  for (size_t i = 0; i < n; i++) h = (h ^ p[i]) * 16777619u;
  return h ? h : 1;  // 0 means "unknown"
}

// Next wake: WAKE_OFFSET_S after the coming local hour, at least 5 min away.
uint32_t nextHourlyWake(uint32_t now) {
  const int32_t off = g_fc.valid ? g_fc.utcOffset : 0;
  const int64_t local = static_cast<int64_t>(now) + off;
  int64_t target = local - local % 3600 + 3600 + WAKE_OFFSET_S;
  if (target - local < 300) target += 3600;
  return static_cast<uint32_t>(target - off);
}

void goToSleep(uint32_t seconds) {
  wifiOff();

  // Keep the panel rail and LED off while asleep.
  digitalWrite(PIN_EPD_PWR, LOW);
  digitalWrite(PIN_LED, LOW);
  gpio_hold_en(static_cast<gpio_num_t>(PIN_EPD_PWR));
  gpio_hold_en(static_cast<gpio_num_t>(PIN_LED));
  gpio_deep_sleep_hold_en();

  // Don't sleep while a wake button is still held, or we wake straight away.
  while (digitalRead(PIN_BTN_MENU) == LOW || digitalRead(PIN_BTN_CONF) == LOW) delay(10);

  const uint64_t mask = (1ULL << PIN_BTN_MENU) | (1ULL << PIN_BTN_CONF);
  esp_sleep_enable_ext1_wakeup(mask, ESP_EXT1_WAKEUP_ANY_LOW);
  esp_sleep_enable_timer_wakeup(static_cast<uint64_t>(seconds) * 1000000ULL);

  Serial.printf("[main] sleeping %lu s\n", static_cast<unsigned long>(seconds));
  Serial.flush();
  esp_deep_sleep_start();
}

// ---- main -----------------------------------------------------------------------

void setup() {
  const uint32_t awakeSince = millis();
  gpio_hold_dis(static_cast<gpio_num_t>(PIN_EPD_PWR));
  gpio_hold_dis(static_cast<gpio_num_t>(PIN_LED));
  gpio_deep_sleep_hold_dis();

  Serial.begin(115200);
  pinMode(PIN_LED, OUTPUT);
  digitalWrite(PIN_LED, HIGH);  // on while awake
  pinMode(PIN_EPD_PWR, OUTPUT);
  pinMode(PIN_BTN_MENU, INPUT);  // external pull-ups on the board
  pinMode(PIN_BTN_CONF, INPUT);

  const esp_sleep_wakeup_cause_t cause = esp_sleep_get_wakeup_cause();
  const bool coldBoot = cause != ESP_SLEEP_WAKEUP_TIMER && cause != ESP_SLEEP_WAKEUP_EXT1;
  const bool button = cause == ESP_SLEEP_WAKEUP_EXT1;

  if (coldBoot) {
    g_fc.valid = false;
    g_clockSet = false;
    g_retryAt = 0;
    g_retryMin = 0;
    g_shownHash = 0;
    g_channel = 0;
  }

  // ---- download if due ----
  uint32_t now = clockNow();
  const bool due = !g_fc.valid || !g_clockSet ||
                   now - g_fc.fetchedAt >= FETCH_HOURS * 3600u - 600u;  // 10 min slack
  const bool retryDue = g_retryAt != 0 && now >= g_retryAt;
  const bool wantFetch = coldBoot || button || due || retryDue;
  Serial.printf("[main] wake cause %d, fetch %s\n", cause, wantFetch ? "yes" : "no");

  bool fresh = false;
  bool wifiFailed = false;
  if (wantFetch) {
    uint32_t serverTime = 0;
    const bool connected = connectWifi();
    wifiFailed = !connected;
    if (connected && fetchForecast(g_download, serverTime)) {
      g_fc = g_download;
      clockSet(serverTime);
      g_clockSet = true;
      g_retryAt = 0;
      g_retryMin = 0;
      fresh = true;
    } else {
      g_retryMin = g_retryMin == 0 ? RETRY_MINUTES : min<uint16_t>(g_retryMin * 2, RETRY_MAX_MINUTES);
      g_retryAt = clockNow() + g_retryMin * 60u;
      Serial.printf("[main] download failed, retry in %u min\n", g_retryMin);
    }
    wifiOff();  // radio off before the slow panel refresh
  }

  // ---- draw ----
  now = clockNow();
  // Woke a few minutes early (clock drift)? Draw the coming hour, since the
  // next wake is scheduled for the hour after that.
  uint32_t viewNow = now;
  const int64_t secOfHour = (static_cast<int64_t>(now) + g_fc.utcOffset) % 3600;
  if (g_fc.valid && secOfHour >= 3300) viewNow += static_cast<uint32_t>(3600 - secOfHour);

  Weather view;
  if (g_clockSet && buildView(g_fc, viewNow, fresh, view)) {
    const bool offline = now - g_fc.fetchedAt > OFFLINE_AFTER_HOURS * 3600u;
    drawForecast(g_canvas, view, offline);
  } else {
    drawMessage(g_canvas, wifiFailed ? "No Wi-Fi" : "No data", "Press MENU to retry");
  }

  const uint32_t hash = hashCanvas(g_canvas);
  if (coldBoot || button || hash != g_shownHash) {
    epd::begin();
    epd::show(g_canvas);
    epd::end();
    g_shownHash = hash;
  } else {
    Serial.println("[main] screen unchanged, skipping refresh");
  }

  // ---- schedule ----
  uint32_t sleepS;
  if (!g_clockSet) {
    sleepS = g_retryMin * 60u;  // no clock yet: just back off
  } else {
    now = clockNow();
    uint32_t target = nextHourlyWake(now);
    if (g_retryAt != 0 && g_retryAt < target) target = g_retryAt;
    sleepS = target > now + 60 ? target - now : 60;
  }
  Serial.printf("[main] awake %lu ms\n", static_cast<unsigned long>(millis() - awakeSince));
  goToSleep(sleepS);
}

void loop() {}
