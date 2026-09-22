#pragma once

// ---- Location (Open-Meteo, no API key needed) ------------------------------
#define LOCATION_NAME   "Ankara"
#define LATITUDE        39.93f
#define LONGITUDE       32.86f

// ---- Timing -----------------------------------------------------------------
// The screen is redrawn every hour from cached data (no Wi-Fi). A new forecast
// is downloaded every FETCH_HOURS, or when MENU / the dial is pressed.
#define FETCH_HOURS          3
#define WAKE_OFFSET_S       90   // wake this long after the hour (RTC clock drifts a little)
#define RETRY_MINUTES        5   // first retry after a failed download,
#define RETRY_MAX_MINUTES   60   //   doubling up to this
#define OFFLINE_AFTER_HOURS  6   // mark the screen "offline" when the data is this old
#define WIFI_TIMEOUT_MS  15000
#define HTTP_TIMEOUT_MS  10000

// ---- Display ------------------------------------------------------------------
// Set to 1 if the image comes out upside down on your board.
#define ROTATE_180 0

// ---- Board pins (from the Elecrow schematic) --------------------------------
#define PIN_EPD_PWR   7    // IO7_LCD_3.3_CTL, high = panel powered
#define PIN_EPD_SCK  12
#define PIN_EPD_MOSI 11
#define PIN_EPD_CS   14
#define PIN_EPD_DC   13
#define PIN_EPD_RST  10
#define PIN_EPD_BUSY  9
#define PIN_LED      19

#define PIN_BTN_MENU  2    // buttons are active low
#define PIN_BTN_EXIT  1
#define PIN_BTN_UP    6
#define PIN_BTN_DOWN  4
#define PIN_BTN_CONF  5
