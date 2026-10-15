#pragma once
#include <stdint.h>
#include <string.h>

struct OutputPlan {
  bool deviceEnabled;
  bool red, green, blue;
  bool buzzer;
  uint16_t rotationUs;
};

inline OutputPlan planOutputs(const char* state, bool sensorReady, bool hardwareReady,
                              bool requestedBeep, bool requestedRun,
                              uint16_t stopUs, uint16_t runUs) {
  bool normal = strcmp(state, "NORMAL") == 0;
  bool warning = strcmp(state, "WARNING") == 0;
  // DANGER, FAULT and unknown states always block the rotating device.
  bool alarm = !normal && !warning;
  bool run = normal && sensorReady && hardwareReady && requestedRun;
  return {run, warning || alarm, normal || warning, false,
          requestedBeep || alarm, run ? runUs : stopUs};
}

inline bool activeOutput(bool on, bool activeHigh) {
  return on ? activeHigh : !activeHigh;
}
