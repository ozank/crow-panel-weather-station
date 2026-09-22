#pragma once
#include <stdint.h>

// Wall-clock time in unix seconds. The ESP32 RTC keeps counting through deep
// sleep, so once set from the server it stays roughly right between downloads.
uint32_t clockNow();
void clockSet(uint32_t unixTime);
