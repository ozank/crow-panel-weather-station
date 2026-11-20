#pragma once
#include <Arduino.h>
#include <Adafruit_GFX.h>

// Display layer for the CrowPanel 2.13" 122x250 black/white panel (SSD1680),
// built on the GxEPD2 library.

namespace epd {

enum class Driver : uint8_t { Unknown = 0, SSD1680 = 1, JD79661 = 2 };

// Powers the panel and initialises the controller.
Driver begin();

// Landscape drawing surface: 250 x 122, colour 1 = black.
constexpr int WIDTH = 250;
constexpr int HEIGHT = 122;

// Full refresh with the canvas contents. Blocks for ~2-4 s.
void show(const GFXcanvas1 &canvas);

// Puts the controller to sleep and cuts panel power.
void end();

const char *driverName();

}  // namespace epd
