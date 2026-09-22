#include "clock.h"

#include <sys/time.h>
#include <time.h>

uint32_t clockNow() { return static_cast<uint32_t>(time(nullptr)); }

void clockSet(uint32_t unixTime) {
  timeval tv{};
  tv.tv_sec = unixTime;
  settimeofday(&tv, nullptr);
}
