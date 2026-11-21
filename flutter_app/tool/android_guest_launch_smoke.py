"""Exercise the actual assembled internal APK on a disposable CI emulator.

No phone number, OTP, legal acceptance, paid service or privileged role is used.
"""
from pathlib import Path
import re
import subprocess
import time
import xml.etree.ElementTree as ET


def adb(*args):
    return subprocess.check_output(['adb', *args], timeout=20)


def snapshot():
    adb('shell', 'uiautomator', 'dump', '/sdcard/pd-window.xml')
    return adb('exec-out', 'cat', '/sdcard/pd-window.xml').decode('utf-8')


def click_label(label, *, optional=False, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        text = snapshot()
        root = ET.fromstring(text)
        for node in root.iter('node'):
            if label not in (node.get('text', '') + ' ' + node.get('content-desc', '')):
                continue
            values = [int(n) for n in re.findall(r'\d+', node.get('bounds', ''))]
            if len(values) != 4:
                continue
            x1, y1, x2, y2 = values
            if x2 <= x1 or y2 <= y1:
                continue
            adb('shell', 'input', 'tap', str((x1 + x2) // 2), str((y1 + y2) // 2))
            print('Tapped:', label, flush=True)
            return True
        time.sleep(1)
    if optional:
        return False
    raise AssertionError('Required app control not found: ' + label)


click_label('Продолжить без разрешений', optional=True, timeout=20)
click_label('Продолжить как гость')
deadline = time.monotonic() + 40
while time.monotonic() < deadline:
    xml = snapshot()
    if all(label in xml for label in ('Гостевой доступ', 'Такси', 'Трансфер')):
        Path('android-guest-passenger.xml').write_text(xml, encoding='utf-8')
        Path('android-guest-passenger.png').write_bytes(adb('exec-out', 'screencap', '-p'))
        print('PASS: actual APK opened passenger cabin without phone, SMS or staff access.', flush=True)
        break
    time.sleep(1)
else:
    raise AssertionError('Guest passenger cabin did not open')
