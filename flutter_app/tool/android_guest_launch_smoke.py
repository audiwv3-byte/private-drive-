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


def click_node(label, *, timeout=60, announce=True):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        text = snapshot()
        root = ET.fromstring(text)
        for node in root.iter('node'):
            props = ' '.join(node.get(key, '') for key in ('text', 'content-desc', 'resource-id'))
            if announce and label not in props:
                continue
            if not announce and label != node.get('text') and label != node.get('content-desc'):
                continue
            values = [int(n) for n in re.findall(r'\d+', node.get('bounds', ''))]
            if len(values) != 4:
                continue
            x1, y1, x2, y2 = values
            if x2 <= x1 or y2 <= y1:
                continue
            adb('shell', 'input', 'tap', str((x1 + x2) // 2), str((y1 + y2) // 2))
            if announce:
                print('Tapped:', label, flush=True)
            return True
        time.sleep(1)
    Path('android-launch-last-window.xml').write_text(text, encoding='utf-8')
    Path('android-launch-last-window.png').write_bytes(adb('exec-out', 'screencap', '-p'))
    raise AssertionError('Required app control not found: ' + (label if announce else 'PIN digit'))


def wait_for_labels(*labels, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        xml = snapshot()
        if all(label in xml for label in labels):
            return xml
        time.sleep(1)
    Path('android-launch-last-window.xml').write_text(xml, encoding='utf-8')
    Path('android-launch-last-window.png').write_bytes(adb('exec-out', 'screencap', '-p'))
    raise AssertionError(f'Missing screen labels: {labels}')


def scroll_to_passenger_option(label, xml, *, scroll_back=False):
    screen_sizes = re.findall(r'(\d+)x(\d+)', adb('shell', 'wm', 'size').decode())
    width, height = map(int, screen_sizes[-1])
    for _ in range(4):
        if label in xml:
            return xml
        start, end = height * 3 // 4, height // 3
        if scroll_back:
            start, end = end, start
        adb('shell', 'input', 'swipe', str(width // 2), str(start),
            str(width // 2), str(end), '350')
        xml = snapshot()
    if label in xml:
        return xml
    raise AssertionError(f'Missing passenger option after scrolling: {label}')


wait_for_labels('Тестовый вход')
click_node('Ввести цифрами на экране')
for digit in os.environ['PD_QA_LOCAL_PIN']:
    click_node(digit, announce=False)
click_node('Войти в тест')
entry = wait_for_labels('Выбери кабинет', 'Пассажир', 'Пилот')
assert 'Диспетчер' not in entry, 'Dispatcher must stay on the website'

for role, labels in [
    ('Пассажир', ('Такси',)),
    ('Пилот', ('Кабина пилота', 'Не на линии')),
]:
    click_node(role)
    xml = wait_for_labels('Внутренний тест', *labels)
    if role == 'Пассажир':
        xml = scroll_to_passenger_option('Трансфер', xml)
        xml = scroll_to_passenger_option('Доставка', xml)
        scroll_to_passenger_option('Трансфер', xml, scroll_back=True)
        click_node('Трансфер')
        wait_for_labels('Mapbox')
        assert b'PD_MAPBOX_TILE_OK' in adb('logcat', '-d'), 'Mapbox tile probe did not succeed'
        Path('android-guest-mapbox.png').write_bytes(adb('exec-out', 'screencap', '-p'))
        adb('shell', 'input', 'keyevent', '4')
        wait_for_labels('Такси')
    assert 'Фотоконтроль' not in xml and 'Проверка личности' not in xml
    Path(f'android-guest-{role}.xml').write_text(xml, encoding='utf-8')
    Path(f'android-guest-{role}.png').write_bytes(adb('exec-out', 'screencap', '-p'))
    adb('shell', 'input', 'keyevent', '4')
    wait_for_labels('Выбери кабинет')
print('PASS: actual APK opened both local cabins without phone or camera.', flush=True)
