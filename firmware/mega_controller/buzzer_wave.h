#pragma once
#include <stdint.h>

struct BuzzerWave {
  uint16_t periodTicks;
  uint16_t highTicks;
};

inline BuzzerWave planBuzzerWave(uint16_t hz, uint8_t dutyPercent, uint32_t cpuHz) {
  if (hz < 100 || hz > 8000 || dutyPercent == 0 || dutyPercent > 50)
    return {0, 0};
  uint32_t period = (cpuHz / 8 + hz / 2) / hz;
  if (period < 4 || period > 65535) return {0, 0};
  uint32_t high = (period * dutyPercent + 50) / 100;
  if (high < 2) high = 2;
  return {static_cast<uint16_t>(period), static_cast<uint16_t>(high)};
}
