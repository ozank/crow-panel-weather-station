#include "weather.h"

#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <WiFi.h>

#include "config.h"

namespace {

int8_t toI8(float v) { return static_cast<int8_t>(constrain(lroundf(v), -128L, 127L)); }
uint8_t toU8(float v) { return static_cast<uint8_t>(constrain(lroundf(v), 0L, 255L)); }

// Days since 1970-01-01 for a civil date (Howard Hinnant's algorithm).
int32_t daysFromCivil(int y, unsigned m, unsigned d) {
  y -= m <= 2;
  const int era = (y >= 0 ? y : y - 399) / 400;
  const unsigned yoe = static_cast<unsigned>(y - era * 400);
  const unsigned doy = (153 * (m + (m > 2 ? -3 : 9)) + 2) / 5 + d - 1;
  const unsigned doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
  return era * 146097 + static_cast<int32_t>(doe) - 719468;
}

// Local-time helpers. `local` is unix time shifted by the UTC offset.
int64_t toLocal(const Forecast &fc, uint32_t t) { return static_cast<int64_t>(t) + fc.utcOffset; }
int localHour(int64_t local) { return static_cast<int>((local % 86400) / 3600); }
int32_t localDay(int64_t local) { return static_cast<int32_t>(local / 86400); }

}  // namespace

uint32_t parseHttpDate(const char *s) {
  if (!s) return 0;
  char mon[4] = {0};
  int d, y, hh, mm, ss;
  if (sscanf(s, "%*3s, %d %3s %d %d:%d:%d", &d, mon, &y, &hh, &mm, &ss) != 6) return 0;
  static const char *const kMonths = "JanFebMarAprMayJunJulAugSepOctNovDec";
  const char *p = strstr(kMonths, mon);
  if (!p || strlen(mon) != 3) return 0;
  const unsigned m = static_cast<unsigned>((p - kMonths) / 3 + 1);
  const int64_t t = static_cast<int64_t>(daysFromCivil(y, m, d)) * 86400 + hh * 3600 + mm * 60 + ss;
  return t > 0 ? static_cast<uint32_t>(t) : 0;
}

bool fetchForecast(Forecast &out, uint32_t &serverTime) {
  char url[640];
  snprintf(url, sizeof(url),
           "http://api.open-meteo.com/v1/forecast?latitude=%.4f&longitude=%.4f"
           "&current=temperature_2m,apparent_temperature,relative_humidity_2m,"
           "weather_code,wind_speed_10m,is_day"
           "&hourly=temperature_2m,apparent_temperature,relative_humidity_2m,"
           "wind_speed_10m,weather_code,precipitation_probability,is_day"
           "&daily=weather_code,temperature_2m_max,temperature_2m_min,"
           "precipitation_probability_max"
           "&timezone=auto&timeformat=unixtime&forecast_days=%d&forecast_hours=%d",
           LATITUDE, LONGITUDE, FC_DAYS, FC_HOURS);

  HTTPClient http;
  http.setTimeout(HTTP_TIMEOUT_MS);
  if (!http.begin(url)) return false;
  const char *headerKeys[] = {"Date"};
  http.collectHeaders(headerKeys, 1);

  const int status = http.GET();
  if (status != HTTP_CODE_OK) {
    Serial.printf("[wx] HTTP %d\n", status);
    http.end();
    return false;
  }
  serverTime = parseHttpDate(http.header("Date").c_str());

  JsonDocument doc;
  const DeserializationError err = deserializeJson(doc, http.getStream());
  http.end();
  if (err) {
    Serial.printf("[wx] JSON error: %s\n", err.c_str());
    return false;
  }
  if (!parseForecast(doc, out)) return false;

  // No Date header: fall back to the observation time (15-minute resolution).
  if (serverTime == 0) serverTime = out.fetchedAt;
  out.fetchedAt = serverTime;
  return true;
}

bool parseForecast(JsonDocument &doc, Forecast &out) {
  JsonObject cur = doc["current"];
  JsonObject hr = doc["hourly"];
  JsonObject dy = doc["daily"];
  if (cur.isNull() || hr.isNull() || dy.isNull()) return false;

  out.utcOffset = doc["utc_offset_seconds"] | 0;
  out.fetchedAt = cur["time"] | 0u;
  out.temp = cur["temperature_2m"] | 0.0f;
  out.feels = cur["apparent_temperature"] | 0.0f;
  out.humidity = toU8(cur["relative_humidity_2m"] | 0.0f);
  out.wind = cur["wind_speed_10m"] | 0.0f;
  out.code = cur["weather_code"] | 0;
  out.isDay = (cur["is_day"] | 1) == 1;

  JsonArray ht = hr["time"];
  if (ht.size() < FC_HOURS) return false;
  out.hourStart = ht[0] | 0u;
  for (int i = 0; i < FC_HOURS; i++) {
    FcHour &h = out.hours[i];
    h.temp = toI8(hr["temperature_2m"][i] | 0.0f);
    h.feels = toI8(hr["apparent_temperature"][i] | 0.0f);
    h.humidity = toU8(hr["relative_humidity_2m"][i] | 0.0f);
    h.wind = toU8(hr["wind_speed_10m"][i] | 0.0f);
    h.code = hr["weather_code"][i] | 0;
    h.precipPct = toU8(hr["precipitation_probability"][i] | 0.0f);
    h.isDay = (hr["is_day"][i] | 1) == 1;
  }

  JsonArray dt = dy["time"];
  if (dt.size() < FC_DAYS) return false;
  out.dayStart = dt[0] | 0u;
  for (int i = 0; i < FC_DAYS; i++) {
    FcDay &d = out.days[i];
    d.tMax = toI8(dy["temperature_2m_max"][i] | 0.0f);
    d.tMin = toI8(dy["temperature_2m_min"][i] | 0.0f);
    d.code = dy["weather_code"][i] | 0;
    d.precipPct = toU8(dy["precipitation_probability_max"][i] | 0.0f);
  }

  out.valid = out.hourStart > 0 && out.dayStart > 0;
  Serial.printf("[wx] %.1f C code %u, %d h / %d days cached\n", out.temp, out.code, FC_HOURS, FC_DAYS);
  return out.valid;
}

bool buildView(const Forecast &fc, uint32_t now, bool fresh, Weather &out) {
  if (!fc.valid || now < fc.hourStart) return false;

  const int nowIdx = static_cast<int>((now - fc.hourStart) / 3600);
  const int64_t localNow = toLocal(fc, now);
  const int curHour = localHour(localNow);
  // First slot on the fixed 3-hour grid strictly after the current hour.
  const int firstIdx = nowIdx + (3 - curHour % 3);
  const int lastIdx = firstIdx + 3 * (HOURS - 1);

  const int64_t localDay0 = toLocal(fc, fc.dayStart);
  const int firstDay = localDay(localNow) - localDay(localDay0);

  if (lastIdx >= FC_HOURS || firstDay < 0 || firstDay + DAYS > FC_DAYS) return false;

  const int64_t localFetched = toLocal(fc, fc.fetchedAt);
  snprintf(out.updated, sizeof(out.updated), "%02d:%02d", localHour(localFetched),
           static_cast<int>((localFetched % 3600) / 60));

  if (fresh) {
    out.temp = fc.temp;
    out.feels = fc.feels;
    out.humidity = fc.humidity;
    out.wind = fc.wind;
    out.code = fc.code;
    out.isDay = fc.isDay;
  } else {
    const FcHour &h = fc.hours[nowIdx];
    out.temp = h.temp;
    out.feels = h.feels;
    out.humidity = h.humidity;
    out.wind = h.wind;
    out.code = h.code;
    out.isDay = h.isDay;
  }

  for (int i = 0; i < HOURS; i++) {
    const int k = firstIdx + 3 * i;
    const FcHour &h = fc.hours[k];
    out.hours[i].hour = static_cast<uint8_t>(localHour(toLocal(fc, fc.hourStart + 3600u * k)));
    out.hours[i].temp = h.temp;
    out.hours[i].code = h.code;
    out.hours[i].precipPct = h.precipPct;
    out.hours[i].isDay = h.isDay;
  }

  for (int i = 0; i < DAYS; i++) {
    const FcDay &d = fc.days[firstDay + i];
    out.days[i].weekday = static_cast<uint8_t>((localDay(localNow) + i + 4) % 7);  // 1970-01-01 was a Thursday
    out.days[i].tMax = d.tMax;
    out.days[i].tMin = d.tMin;
    out.days[i].code = d.code;
    out.days[i].precipPct = d.precipPct;
  }
  return true;
}
