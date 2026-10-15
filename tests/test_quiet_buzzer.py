"""Exercise pulse timing and the actual Timer3 stop/start code with fake registers."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent


class QuietBuzzerTests(unittest.TestCase):
    def test_frequency_pulse_width_stop_and_timer_isolation(self):
        if not shutil.which('g++'):
            self.skipTest('g++ is required')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'avr').mkdir()
            (root / 'util').mkdir()
            (root / 'Arduino.h').write_text('''#pragma once
#include <stdint.h>
#define F_CPU 16000000UL
#define MOBLE_VENTILATION_PROFILE 1
#define _BV(bit) (1U << (bit))
constexpr uint8_t BUZZER_PIN=28, BUZZER_DUTY_PERCENT=5;
constexpr uint8_t OCF3A=1, OCF3B=2, OCF3C=3, TOV3=0;
constexpr uint8_t OCIE3B=2, OCIE3C=3, WGM32=3, CS31=1;
volatile uint8_t TIMSK3=0, TCCR3A=0, TCCR3B=0, TIFR3=0, output=0;
volatile uint16_t TCNT3=0, OCR3A=0, OCR3B=0, OCR3C=0;
inline uint8_t digitalPinToPort(uint8_t) { return 1; }
inline uint8_t digitalPinToBitMask(uint8_t pin) { return 1U << (pin-22); }
inline volatile uint8_t* portOutputRegister(uint8_t) { return &output; }
''')
            (root / 'avr/interrupt.h').write_text('#pragma once\n#define ISR(name) void name()\n')
            (root / 'util/atomic.h').write_text('#pragma once\n#define ATOMIC_RESTORESTATE 0\n#define ATOMIC_BLOCK(x) for(bool once=true; once; once=false)\n')
            (root / 'check.cpp').write_text('''#include <assert.h>
#include <cmath>
#include <initializer_list>
#include "quiet_buzzer.h"
int main() {
  for (uint8_t duty : {5, 17, 50}) for (unsigned hz=100; hz<=8000; ++hz) {
    auto w=planBuzzerWave(hz,duty,F_CPU);
    assert(w.periodTicks > w.highTicks && w.highTicks >= 2);
    double actual=2000000.0/w.periodTicks;
    assert(std::abs(actual-hz)/hz < 0.003);
    assert(std::abs(double(w.highTicks)/w.periodTicks-duty/100.0) < 0.003);
  }
  assert(!planBuzzerWave(0,17,F_CPU).periodTicks);
  assert(!planBuzzerWave(99,17,F_CPU).periodTicks);
  assert(!planBuzzerWave(8001,17,F_CPU).periodTicks);
  assert(!planBuzzerWave(1000,0,F_CPU).periodTicks);
  assert(!planBuzzerWave(1000,51,F_CPU).periodTicks);
  const uint8_t mask=1U<<6, otherPins=0x15;
  output=otherPins|mask;
  setVentilationTone(0);
  assert(output==otherPins && TIMSK3==0 && TCCR3B==0);
  setVentilationTone(1000);
  assert(OCR3A==1999 && OCR3C==1999 && OCR3B==99);
  assert(TIMSK3==(_BV(OCIE3B)|_BV(OCIE3C))); // No Servo compare-A IRQ.
  assert(output==(otherPins|mask));
  TIMER3_COMPB_vect(); assert(output==otherPins);
  TIMER3_COMPC_vect(); assert(output==(otherPins|mask));
  TCNT3=1200;
  setVentilationTone(2400);
  assert(TCNT3==0 && OCR3A==832 && OCR3C==832); // No missed TOP on retune.
  TCNT3=125;
  setVentilationTone(2400);
  assert(TCNT3==125); // Repeated UI updates must not restart the waveform.
  setVentilationTone(0);
  assert(output==otherPins && TIMSK3==0 && TCCR3B==0);
  setVentilationTone(1800);
  assert(TIMSK3 && (output&mask));
  setVentilationTone(0);
  assert(output==otherPins && TIMSK3==0 && TCCR3B==0);
}
''')
            subprocess.check_call(['g++', '-std=c++11', '-Wall', '-Wextra', '-Werror',
                                   '-I', str(root), '-I', str(ROOT / 'firmware/mega_controller'),
                                   str(root / 'check.cpp'), '-o', str(root / 'check')])
            subprocess.check_call([str(root / 'check')])
