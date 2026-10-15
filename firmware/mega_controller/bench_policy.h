#pragma once
#include <stdint.h>

// A repeated RUN command cannot extend the limit. A STOP command is required
// before a new run after timeout/fault. Unsigned subtraction handles wraparound.
class BenchRunLimit {
 public:
  bool allow(bool requested, uint32_t now) {
    if (!requested) { running_ = false; blocked_ = false; return false; }
    if (blocked_) return false;
    if (!running_) { started_ = now; running_ = true; }
    if (expired(now)) { trip(); return false; }
    return true;
  }
  bool expired(uint32_t now) const { return running_ && (uint32_t)(now - started_) >= 10000; }
  void trip() { running_ = false; blocked_ = true; }
 private:
  uint32_t started_ = 0;
  bool running_ = false, blocked_ = true;
};
