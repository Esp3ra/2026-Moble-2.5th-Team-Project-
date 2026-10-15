"""Exercise the actual firmware output policy on the host compiler."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent


class FirmwareOutputTests(unittest.TestCase):
    def test_interlock_rgb_and_polarity(self):
        compiler = shutil.which('g++')
        if not compiler:
            self.skipTest('g++ is required for native firmware policy checks')
        source = r'''
#include <assert.h>
#include "output_policy.h"
int main() {
  const unsigned stop = 1490, run = 1600; // Non-default neutral must be preserved.
  auto normal = planOutputs("NORMAL", true, true, false, true, stop, run);
  assert(normal.deviceEnabled && normal.rotationUs == run);
  assert(normal.green && !normal.red && !normal.blue && !normal.buzzer);
  for (const char* state : {"WARNING", "DANGER", "FAULT", "invalid"}) {
    auto out = planOutputs(state, true, true, false, true, stop, run);
    assert(!out.deviceEnabled && out.rotationUs == stop);
    assert(out.red && !out.blue);
    bool warning = strcmp(state, "WARNING") == 0;
    assert(out.green == warning && out.buzzer == !warning);
  }
  for (bool sensor : {false, true}) for (bool hardware : {false, true}) {
    auto out = planOutputs("NORMAL", sensor, hardware, false, true, stop, run);
    assert(out.deviceEnabled == (sensor && hardware));
    assert(out.rotationUs == (sensor && hardware ? run : stop));
  }
  // Recovery without a new START request must keep the device stopped.
  auto stopped = planOutputs("NORMAL", true, true, false, false, stop, run);
  assert(!stopped.deviceEnabled && stopped.rotationUs == stop);
  auto manualBeep = planOutputs("NORMAL", true, true, true, false, stop, run);
  assert(manualBeep.buzzer && !manualBeep.deviceEnabled);
  // Common-anode RGB and active-low buzzer invert both ON and OFF.
  assert(activeOutput(true, true) && !activeOutput(false, true));
  assert(!activeOutput(true, false) && activeOutput(false, false));
}
'''
        with tempfile.TemporaryDirectory(prefix='moble-output-check-') as temp:
            cpp = Path(temp) / 'check.cpp'
            binary = Path(temp) / 'check'
            cpp.write_text('#include <initializer_list>\n' + source)
            subprocess.check_call([compiler, '-std=c++11', '-Wall', '-Wextra', '-Werror',
                                   '-I', str(ROOT / 'firmware/mega_controller'),
                                   str(cpp), '-o', str(binary)])
            subprocess.check_call([str(binary)])


if __name__ == '__main__':
    unittest.main()
