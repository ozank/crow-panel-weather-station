#include "ui.h"

#include <Fonts/FreeSans9pt7b.h>
#include <Fonts/FreeSansBold9pt7b.h>
#include <Fonts/FreeSansBold12pt7b.h>

#include "config.h"

namespace {

constexpr uint16_t BLACK = 1;
constexpr uint16_t WHITE = 0;

const char *const kWeekdays[] = {"Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"};

// ---- text helpers -------------------------------------------------------------

int16_t textWidth(GFXcanvas1 &c, const char *s) {
  int16_t x1, y1;
  uint16_t w, h;
  c.getTextBounds(s, 0, 0, &x1, &y1, &w, &h);
  return static_cast<int16_t>(w) + x1;
}

// Temperature with a drawn degree ring (the GFX fonts have no ° glyph).
// Returns the x position after the ring.
int16_t printTemp(GFXcanvas1 &c, int16_t x, int16_t y, int value, const GFXfont *font, int ringR) {
  char buf[8];
  snprintf(buf, sizeof(buf), "%d", value);
  c.setFont(font);
  c.setCursor(x, y);
  c.print(buf);
  const int16_t cx = c.getCursorX() + ringR + 1;
  const int16_t top = font ? y - (font == &FreeSansBold12pt7b ? 16 : 12) : y;
  c.drawCircle(cx, top + ringR, ringR, BLACK);
  if (ringR >= 3) c.drawCircle(cx, top + ringR, ringR - 1, BLACK);
  return cx + ringR + 2;
}

void smallText(GFXcanvas1 &c, int16_t x, int16_t y, const char *s) {
  c.setFont(nullptr);  // built-in 6x8, y is the top edge
  c.setCursor(x, y);
  c.print(s);
}

void smallTextCentered(GFXcanvas1 &c, int16_t cx, int16_t y, const char *s) {
  smallText(c, cx - static_cast<int16_t>(strlen(s)) * 3, y, s);
}

// ---- icons ----------------------------------------------------------------------
// All icons are drawn from primitives so they scale to any size.

void cloudShape(GFXcanvas1 &c, float cx, float cy, float w, int grow, uint16_t col) {
  const float rBig = w * 0.24f, rLeft = w * 0.17f, rRight = w * 0.15f;
  const float bx = cx + w * 0.02f, by = cy - w * 0.06f;
  const float lx = cx - w * 0.26f, ly = cy + w * 0.05f;
  const float rx = cx + w * 0.30f, ry = cy + w * 0.07f;
  c.fillCircle(bx, by, rBig + grow, col);
  c.fillCircle(lx, ly, rLeft + grow, col);
  c.fillCircle(rx, ry, rRight + grow, col);
  const float bottom = ly + rLeft;
  c.fillRect(lx, by, rx - lx, bottom - by + grow, col);
}

// Outlined cloud with a white body; covers whatever is behind it.
void cloud(GFXcanvas1 &c, float cx, float cy, float w) {
  const int stroke = w >= 24 ? 2 : 1;
  cloudShape(c, cx, cy, w, stroke, BLACK);
  cloudShape(c, cx, cy, w, 0, WHITE);
}

void sun(GFXcanvas1 &c, float cx, float cy, float s) {
  const float r = s * 0.2f;
  c.fillCircle(cx, cy, r, BLACK);
  for (int i = 0; i < 8; i++) {
    const float a = i * PI / 4;
    const float r1 = r + s * 0.08f, r2 = r + s * 0.2f;
    c.drawLine(cx + cosf(a) * r1, cy + sinf(a) * r1, cx + cosf(a) * r2, cy + sinf(a) * r2, BLACK);
    if (s >= 24)
      c.drawLine(cx + cosf(a) * r1 + 1, cy + sinf(a) * r1, cx + cosf(a) * r2 + 1, cy + sinf(a) * r2, BLACK);
  }
}

void moon(GFXcanvas1 &c, float cx, float cy, float s) {
  const float r = s * 0.3f;
  c.fillCircle(cx, cy, r, BLACK);
  c.fillCircle(cx + r * 0.55f, cy - r * 0.35f, r * 0.85f, WHITE);
}

void rainLines(GFXcanvas1 &c, float cx, float top, float s, int n, bool drizzle) {
  const float step = s * 0.22f;
  const float len = drizzle ? s * 0.08f : s * 0.2f;
  for (int i = 0; i < n; i++) {
    const float x = cx - step * (n - 1) / 2 + step * i;
    c.drawLine(x, top, x - len * 0.5f, top + len, BLACK);
    if (s >= 24) c.drawLine(x + 1, top, x + 1 - len * 0.5f, top + len, BLACK);
  }
}

void snowFlakes(GFXcanvas1 &c, float cx, float top, float s) {
  const float step = s * 0.24f, a = s >= 24 ? 3 : 2;
  for (int i = 0; i < 3; i++) {
    const float x = cx - step + step * i, y = top + (i == 1 ? a * 1.5f : a);
    c.drawLine(x - a, y, x + a, y, BLACK);
    c.drawLine(x, y - a, x, y + a, BLACK);
    c.drawLine(x - a + 1, y - a + 1, x + a - 1, y + a - 1, BLACK);
    c.drawLine(x - a + 1, y + a - 1, x + a - 1, y - a + 1, BLACK);
  }
}

void bolt(GFXcanvas1 &c, float cx, float top, float s) {
  const float h = s * 0.34f, w = s * 0.14f;
  c.fillTriangle(cx + w * 0.3f, top, cx - w, top + h * 0.55f, cx + w * 0.2f, top + h * 0.55f, BLACK);
  c.fillTriangle(cx - w * 0.2f, top + h * 0.45f, cx + w, top + h * 0.45f, cx - w * 0.4f, top + h, BLACK);
}

// Draws the icon for a WMO weather code centred on (cx, cy) in an s x s box.
void weatherIcon(GFXcanvas1 &c, int cx, int cy, int s, uint8_t code, bool isDay) {
  const float f = s;
  auto sky = [&](float x, float y, float size) {
    if (isDay) sun(c, x, y, size);
    else moon(c, x, y, size);
  };

  if (code == 0) {  // clear
    sky(cx, cy, f);
  } else if (code <= 2) {  // mainly clear / partly cloudy
    sky(cx - f * 0.16f, cy - f * 0.14f, f * 0.8f);
    cloud(c, cx + f * 0.08f, cy + f * 0.12f, f * 0.72f);
  } else if (code == 3) {  // overcast
    cloud(c, cx, cy, f * 0.95f);
  } else if (code == 45 || code == 48) {  // fog
    for (int i = 0; i < 4; i++) {
      const int y = cy - f * 0.3f + i * f * 0.2f;
      const int x0 = cx - f * 0.4f + (i % 2) * f * 0.1f;
      c.drawFastHLine(x0, y, f * 0.7f, BLACK);
      if (s >= 24) c.drawFastHLine(x0, y + 1, f * 0.7f, BLACK);
    }
  } else if (code >= 95) {  // thunderstorm
    cloud(c, cx, cy - f * 0.14f, f * 0.9f);
    bolt(c, cx, cy + f * 0.12f, f);
  } else if ((code >= 71 && code <= 77) || code == 85 || code == 86) {  // snow
    cloud(c, cx, cy - f * 0.14f, f * 0.9f);
    snowFlakes(c, cx, cy + f * 0.2f, f);
  } else if (code >= 51 && code <= 57) {  // drizzle
    cloud(c, cx, cy - f * 0.14f, f * 0.9f);
    rainLines(c, cx, cy + f * 0.2f, f, 4, true);
  } else if ((code >= 61 && code <= 67) || (code >= 80 && code <= 82)) {  // rain / showers
    cloud(c, cx, cy - f * 0.14f, f * 0.9f);
    rainLines(c, cx, cy + f * 0.18f, f, 3, false);
  } else {
    cloud(c, cx, cy, f * 0.9f);
  }
}

// ---- layout ---------------------------------------------------------------------
//
//  0 +--------------------------------------------------------------+
//    | Ankara                                         Updated 14:30 |
// 12 +--------------+-----------------------------------------------+
//    | icon  23°    |  15    18    21    00    03    06             |
//    | Feels 21°    |  ico   ico   ico   ico   ico   ico            |
//    | 45%  12km/h  |  23°   21°   17°   15°   14°   13°            |
// 64 +--------------+------------------+----------------------------+
//    | Today   ico  | Wed         ico  | Thu              ico       |
//    | 28°/15°      | 27°/14°          | 25°/13°                    |
//    | 40% rain     | 10% rain         | 0% rain                    |
//122 +--------------+------------------+----------------------------+

void drawHeader(GFXcanvas1 &c, const Weather &w, bool offline) {
  smallText(c, 3, 2, LOCATION_NAME);
  char right[32];
  snprintf(right, sizeof(right), offline ? "Offline, last %s" : "Updated %s", w.updated);
  smallText(c, c.width() - 3 - static_cast<int16_t>(strlen(right)) * 6, 2, right);
  c.drawFastHLine(0, 12, c.width(), BLACK);
}

void drawNow(GFXcanvas1 &c, const Weather &w) {
  weatherIcon(c, 17, 29, 30, w.code, w.isDay);
  printTemp(c, 36, 37, lroundf(w.temp), &FreeSansBold12pt7b, 3);

  char buf[24];
  snprintf(buf, sizeof(buf), "Feels %ld", lroundf(w.feels));
  smallText(c, 3, 45, buf);
  c.drawCircle(3 + strlen(buf) * 6 + 2, 46, 1, BLACK);

  snprintf(buf, sizeof(buf), "%u%% %ldkm/h", w.humidity, lroundf(w.wind));
  smallText(c, 3, 54, buf);

  c.drawFastVLine(80, 13, 51, BLACK);
}

void drawHours(GFXcanvas1 &c, const Weather &w) {
  constexpr int x0 = 82, slotW = 28;
  for (int i = 0; i < HOURS; i++) {
    const HourSlot &h = w.hours[i];
    const int cx = x0 + slotW * i + slotW / 2;
    char buf[8];
    snprintf(buf, sizeof(buf), "%02u", h.hour);
    smallTextCentered(c, cx, 15, buf);
    weatherIcon(c, cx, 33, 18, h.code, h.isDay);

    snprintf(buf, sizeof(buf), "%d", h.temp);
    const int tw = strlen(buf) * 6 + 4;
    smallText(c, cx - tw / 2, 45, buf);
    c.drawCircle(cx - tw / 2 + strlen(buf) * 6 + 2, 46, 1, BLACK);

    if (h.precipPct >= 20) {
      snprintf(buf, sizeof(buf), "%u%%", h.precipPct);
      smallTextCentered(c, cx, 54, buf);
    }
  }
}

void drawDays(GFXcanvas1 &c, const Weather &w) {
  c.drawFastHLine(0, 64, c.width(), BLACK);
  constexpr int colW = 83;
  for (int i = 0; i < DAYS; i++) {
    const DaySlot &d = w.days[i];
    const int x = colW * i;
    if (i > 0) c.drawFastVLine(x, 65, 57, BLACK);

    c.setFont(&FreeSansBold9pt7b);
    c.setCursor(x + 5, 81);
    c.print(kWeekdays[d.weekday]);

    weatherIcon(c, x + colW - 17, 77, 24, d.code, true);

    int16_t cx = printTemp(c, x + 5, 104, d.tMax, &FreeSansBold9pt7b, 2);
    c.setFont(&FreeSans9pt7b);
    c.setCursor(cx, 104);
    c.print("/");
    printTemp(c, c.getCursorX(), 104, d.tMin, &FreeSans9pt7b, 2);

    char buf[16];
    snprintf(buf, sizeof(buf), "%u%% rain", d.precipPct);
    smallText(c, x + 5, 111, buf);
  }
}

}  // namespace

void drawForecast(GFXcanvas1 &c, const Weather &w, bool offline) {
  c.fillScreen(WHITE);
  c.setTextColor(BLACK);
  c.setTextWrap(false);
  drawHeader(c, w, offline);
  drawNow(c, w);
  drawHours(c, w);
  drawDays(c, w);
}

void drawMessage(GFXcanvas1 &c, const char *title, const char *detail) {
  c.fillScreen(WHITE);
  c.setTextColor(BLACK);
  c.setTextWrap(false);
  c.setFont(&FreeSansBold12pt7b);
  c.setCursor((c.width() - textWidth(c, title)) / 2, 58);
  c.print(title);
  smallTextCentered(c, c.width() / 2, 72, detail);
}
