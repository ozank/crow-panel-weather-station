#pragma once
#include <Adafruit_GFX.h>

#include "weather.h"

// Draws the forecast screen into a 250 x 122 canvas (1 = black).
void drawForecast(GFXcanvas1 &c, const Weather &w, bool offline);

// Simple centred message, used before any data has been fetched.
void drawMessage(GFXcanvas1 &c, const char *title, const char *detail);
