"""Exercise account registration entry in the assembled Android APK."""
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


def scroll_to_label(label, xml, *, scroll_back=False):
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
    raise AssertionError(f'Missing screen label after scrolling: {label}')


entry = wait_for_labels('Выбери кабинет', 'Пассажир', 'Пилот')
assert 'Тестовый вход' not in entry, 'Account build must not require a local PIN'
assert 'Локальные тестовые данные' not in entry

click_node('Пассажир')
signin = wait_for_labels('Вход пассажира', 'Вход по SMS или через Telegram')
signin = scroll_to_label('Войти через Telegram', signin)
signin = scroll_to_label('Получить код', signin, scroll_back=True)
assert 'Продолжить как гость' not in signin, 'Registration build must not offer guest entry'
Path('android-launch-account.xml').write_text(signin, encoding='utf-8')
Path('android-launch-account.png').write_bytes(adb('exec-out', 'screencap', '-p'))
adb('shell', 'input', 'keyevent', '4')
wait_for_labels('Выбери кабинет')
print('PASS: the assembled APK exposes SMS and Telegram without a local PIN.', flush=True)
