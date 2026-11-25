"""Install a tested checkout into the existing PythonAnywhere WSGI entry point."""
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
from tempfile import NamedTemporaryFile

from cryptography.fernet import Fernet
from PIL import features


def create_secret(path, value):
    try:
        with path.open("xb") as file:
            file.write(value + b"\n")
    except FileExistsError:
        pass


def main():
    os.umask(0o077)
    if not features.check("webp"):
        raise SystemExit("Pillow must support WebP.")
    release = Path(__file__).resolve().parents[1]
    state = Path.home() / ".private-drive-dispatch"
    live = Path("/var/www/wilsonpark_pythonanywhere_com_wsgi.py")
    if state.stat().st_mode & 0o077:
        raise SystemExit("The dispatcher state directory is not private.")
    original = live.read_bytes()
    source = original.decode()
    pattern = r'(?m)^_pd_release = Path\.home\(\) / "pd-dispatch-release-[^"\n]+"$'
    replacement = "_pd_release = Path(" + repr(str(release)) + ")"
    if replacement in source.splitlines():
        print("Конфигурация уже установлена.")
        return
    updated, count = re.subn(pattern, lambda _: replacement, source)
    if count != 1 or "application = mount_dispatcher(application)" not in source:
        raise SystemExit("WSGI отличается от ожидаемой конфигурации. Изменения не внесены.")
    create_secret(state / "pilot-intake.key", Fernet.generate_key())
    create_secret(state / "pilot-intake.invite", secrets.token_urlsafe(32).encode("ascii"))
    with NamedTemporaryFile(mode="w", dir=state, suffix=".py") as candidate:
        candidate.write(updated)
        candidate.flush()
        check = """
from pathlib import Path
import runpy
import sys
from werkzeug.test import Client
from werkzeug.wrappers import Response
app = runpy.run_path(sys.argv[1])["application"]
client = Client(app, Response)
assert client.get("/dispatch").status_code == 302
assert client.get("/dispatch/login").status_code == 200
assert client.get("/dispatch/qa-pilot-applications").status_code == 401
assert client.get("/pilot-registration").status_code == 200
assert client.get("/").status_code < 400
"""
        subprocess.run([sys.executable, "-B", "-c", check, candidate.name], check=True)
    backup = state / "wsgi-before-pilot-intake.py"
    if not backup.exists():
        with backup.open("xb") as file:
            file.write(original)
    with live.open("r+b") as file:
        if file.read() != original:
            raise SystemExit("Рабочий WSGI изменился во время проверки.")
        try:
            file.seek(0)
            file.write(updated.encode())
            file.truncate()
            file.flush()
            file.seek(0)
            if file.read() != updated.encode():
                raise OSError("WSGI write verification failed")
        except BaseException:
            file.seek(0)
            file.write(original)
            file.truncate()
            raise
    print("Анкета и диспетчерская проверены. Конфигурация установлена, нужен Reload.")


if __name__ == "__main__":
    main()
