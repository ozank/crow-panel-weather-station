#pragma once
#include <Arduino.h>
#include <Adafruit_GFX.h>

// Driver for the CrowPanel 2.13" 122x250 black/white panel.
//
// Elecrow has shipped this board with two different controllers:
//   SSD1680  - BUSY is HIGH while busy (older boards, Elecrow example code)
//   JD79661  - BUSY is LOW while busy  (newer boards)
// The driver tells them apart from the idle level of BUSY after reset,
// or you can force one with -DPANEL_DRIVER=1 / 2.
//
// Controller RAM (both chips): 250 rows of 16 bytes (128 px, 122 used),
// MSB first, bit 1 = white. The two chips scan rows in opposite directions,
// which show() takes care of.

namespace epd {

constexpr int NATIVE_W = 128;   // bytes-aligned width, 122 visible
constexpr int VISIBLE_W = 122;
constexpr int NATIVE_H = 250;
constexpr size_t FRAME_BYTES = NATIVE_W / 8 * NATIVE_H;  // 4000

enum class Driver : uint8_t { Unknown = 0, SSD1680 = 1, JD79661 = 2 };

// Powers the panel, resets it and detects the controller.
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
