#pragma once
#include <stdint.h>
#include <string.h>

struct VentilationPlan {
  const char* state;
  const char* vent;
  const char* fan;
  bool enabled;
  uint16_t pulseUs;
};

struct TemperatureStop {
  bool active = false;
  bool cooling = false;
  uint32_t normalSince = 0;

  // Called only for a new sensor measurement. Invalid samples interrupt the
  // recovery window; unsigned subtraction also works across millis() rollover.
  void update(float temperature, bool valid, uint32_t now,
              float trip, float release, uint32_t recoveryMs) {
    if (!valid) { cooling = false; return; }
    if (temperature >= trip) active = true;
    if (active && temperature < release) {
      if (!cooling) { cooling = true; normalSince = now; }
      else if (uint32_t(now - normalSince) >= recoveryMs) { active = false; cooling = false; }
    } else cooling = false;
  }
};

inline uint8_t ventilationTemperatureLevel(float value, float warning, float danger) {
  return value >= danger ? 2 : value >= warning ? 1 : 0;
}

inline const char* ventilationStatus(const char* state, bool accessAlert, bool stopped, bool temperatureDanger = false,
                                     bool temperatureStop = false) {
  if (stopped) return "STOPPED";
  if (strcmp(state, "FAULT") == 0) return "DEVICE ERROR";
  if (temperatureStop) return "TEMP AUTO STOP";
  if (strcmp(state, "WARNING") == 0) return accessAlert || temperatureDanger ? "DANGER" : "CAUTION";
  if (accessAlert || strcmp(state, "DANGER") == 0) return "UNAUTHORIZED";
  return "NORMAL";
}

inline bool ventilationOrangePhase(const char* state, bool accessAlert, uint32_t now, bool temperatureDanger = false) {
  return !temperatureDanger && strcmp(state, "WARNING") == 0 && (!accessAlert || now % 800 < 400);
}

inline bool ventilationRedPhase(const char* state, bool accessAlert, uint32_t now, bool temperatureDanger = false) {
  if (temperatureDanger && strcmp(state, "WARNING") == 0) return true;
  bool intrusion = accessAlert || strcmp(state, "DANGER") == 0;
  return intrusion && now % 800 >= 400;
}

inline uint16_t ventilationBuzzerHz(const char* state, uint32_t now,
                                   bool emergencyStop = false, bool acknowledged = false) {
  if (emergencyStop || acknowledged) return 0;
  if (strcmp(state, "WARNING") == 0) {
    uint16_t phase = now % 2000;
    return phase < 200 || (phase >= 400 && phase < 600) ? 1800 : 0;
  }
  // Intrusion keeps its LED pattern and lock, but has no audible alarm.
  if (strcmp(state, "DANGER") == 0 || strcmp(state, "NORMAL") == 0) return 0;
  return now % 2000 < 300 ? 2000 : 0;
}

inline VentilationPlan planVentilation(const char* requestedState, bool localEnvironment,
                                      bool ready, bool requestedRun,
                                      uint16_t stopUs, uint16_t lowUs, uint16_t highUs,
                                      const char* manualVent = "AUTO", bool emergencyStop = false,
                                      bool temperatureStop = false) {
  bool known = strcmp(requestedState, "NORMAL") == 0 || strcmp(requestedState, "WARNING") == 0
      || strcmp(requestedState, "DANGER") == 0;
  if (emergencyStop)
    return {known && ready ? requestedState : "FAULT", "CLOSED", "OFF", false, stopUs};
  if (temperatureStop)
    return {known && ready ? "WARNING" : "FAULT", "CLOSED", "OFF", false, stopUs};
  if (!ready || !known)
    return {"FAULT", localEnvironment ? "OPEN" : "SAFE", "OFF", false, stopUs};
  bool environment = localEnvironment || strcmp(requestedState, "WARNING") == 0;
  bool intrusion = strcmp(requestedState, "DANGER") == 0;
  const char* state = environment ? "WARNING" : intrusion ? "DANGER" : "NORMAL";
  const char* vent = environment ? "OPEN" : "CLOSED";
  if (strcmp(manualVent, "OPEN") == 0 || strcmp(manualVent, "CLOSED") == 0) vent = manualVent;
  return {state, vent,
          !requestedRun ? "OFF" : environment ? "HIGH" : "LOW", requestedRun,
          !requestedRun ? stopUs : environment ? highUs : lowUs};
}
