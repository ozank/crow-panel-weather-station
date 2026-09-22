#pragma once
#include <Arduino.h>
#include <ArduinoJson.h>

// ---- what the screen shows ----------------------------------------------------

constexpr int HOURS = 6;  // hourly slots shown, every 3 h on a fixed grid (00, 03, 06 ...)
constexpr int DAYS = 3;   // daily columns shown (today + 2)

struct HourSlot {
  uint8_t hour;       // local hour 0..23
  int8_t temp;        // °C, rounded
  uint8_t code;       // WMO weather code
  uint8_t precipPct;  // precipitation probability
  bool isDay;
};

struct DaySlot {
  uint8_t weekday;  // 0 = Sunday
  int8_t tMax, tMin;
  uint8_t code;
  uint8_t precipPct;
};

struct Weather {
  char updated[6];  // "HH:MM" local time of the last download
  float temp;
  float feels;
  uint8_t humidity;
  float wind;       // km/h
  uint8_t code;
  bool isDay;
  HourSlot hours[HOURS];
  DaySlot days[DAYS];
};

// ---- what gets downloaded and cached in RTC memory ---------------------------
// Enough hourly and daily data to keep redrawing the screen for a day without
// Wi-Fi. No default member initialisers: this lives in RTC memory and must not
// be reset by a constructor on every wake.

constexpr int FC_HOURS = 48;
constexpr int FC_DAYS = 4;

struct FcHour {
  int8_t temp, feels;
  uint8_t humidity, wind, code, precipPct;
  bool isDay;
};

struct FcDay {
  int8_t tMax, tMin;
  uint8_t code, precipPct;
};

struct Forecast {
  bool valid;
  int32_t utcOffset;   // seconds, local = UTC + offset
  uint32_t fetchedAt;  // unix time of the download
  // Observed conditions at download time
  float temp, feels, wind;
  uint8_t humidity, code;
  bool isDay;
  uint32_t hourStart;  // unix time of hours[0]; entries are 1 h apart
  uint32_t dayStart;   // unix time of local midnight of days[0]
  FcHour hours[FC_HOURS];
  FcDay days[FC_DAYS];
};

// Downloads the forecast from Open-Meteo. Wi-Fi must already be connected.
// serverTime receives the current unix time (HTTP Date header).
bool fetchForecast(Forecast &out, uint32_t &serverTime);

// Parses an Open-Meteo response (split out so it can be tested off-device).
bool parseForecast(JsonDocument &doc, Forecast &out);

// Builds the screen contents for time `now` from the cache. `fresh` means the
// download happened on this wake, so the observed conditions are used for the
// "now" block instead of the hourly forecast. Returns false if the cache no
// longer covers `now`.
bool buildView(const Forecast &fc, uint32_t now, bool fresh, Weather &out);

// Parses an RFC 1123 date ("Tue, 22 Sep 2026 11:41:07 GMT") to unix time, 0 on failure.
uint32_t parseHttpDate(const char *s);
