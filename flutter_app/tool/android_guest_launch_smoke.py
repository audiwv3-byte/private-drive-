"""Exercise the actual assembled internal APK on a disposable CI emulator.

No phone number, OTP, camera, paid service or server role is used.
"""
import os
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


def wait_for_labels(*labels, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        xml = snapshot()
        if all(label in xml for label in labels):
            return xml
        time.sleep(1)
    raise AssertionError(f'Missing screen labels: {labels}')


wait_for_labels('Тестовый вход', 'Тестовый пароль')
click_label('Тестовый пароль')
adb('shell', 'input', 'text', os.environ['PD_QA_LOCAL_PIN'])
adb('shell', 'input', 'keyevent', '4')
click_label('Войти в тест')
wait_for_labels('Выбери кабинет', 'Пассажир', 'Пилот', 'Диспетчер')

for role, labels in [
    ('Пассажир', ('Такси', 'Трансфер')),
    ('Пилот', ('Кабина пилота', 'Не на линии')),
    ('Диспетчер', ('PRIVATE DRIVE · Диспетчер',)),
]:
    click_label(role)
    xml = wait_for_labels('Внутренний тест', *labels)
    assert 'Фотоконтроль' not in xml
    Path(f'android-guest-{role}.xml').write_text(xml, encoding='utf-8')
    Path(f'android-guest-{role}.png').write_bytes(adb('exec-out', 'screencap', '-p'))
    adb('shell', 'input', 'keyevent', '4')
    wait_for_labels('Выбери кабинет')
print('PASS: actual APK opened all three local cabins without phone or camera.', flush=True)
