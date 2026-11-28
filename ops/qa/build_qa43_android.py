"""Build one signed APK for a private HTTPS QA lab after the approved CI passes."""
import argparse
import base64
import ipaddress
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
ORG = "lt.privatedrive.qa.booking"
PACKAGE = f"{ORG}.private_drive"
LABEL = "PRIVATE DRIVE QA43"
VERSION = "0.2.28"
BUILD_NUMBER = "2026112801"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", required=True, type=ipaddress.IPv4Address)
    parser.add_argument("--ca", required=True, type=Path)
    parser.add_argument("--keystore", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not any(args.address in ipaddress.IPv4Network(network) for network in (
        "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"
    )):
        parser.error("Only a private RFC1918 lab address is allowed")
    ca = args.ca.read_bytes()
    if ca.count(b"-----BEGIN CERTIFICATE-----") != 1 or b"PRIVATE KEY" in ca:
        parser.error("Provide the public PEM file of the lab CA")
    subprocess.run(["openssl", "x509", "-in", str(args.ca), "-checkend", "0", "-noout"], check=True)
    keystore = args.keystore.resolve()
    if keystore.is_relative_to(ROOT):
        parser.error("Keep the QA signing key outside the repository")
    keystore.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    output = args.output.resolve()
    if output.exists():
        parser.error("Output already exists")
    with TemporaryDirectory(prefix="pd-qa43-android-") as temp:
        project = Path(temp) / "android_qa"
        subprocess.run(["flutter", "create", "--no-pub", "--platforms=android",
                        f"--org={ORG}", "--project-name=private_drive", str(project)], check=True)
        for name in ("lib", "assets"):
            shutil.copytree(ROOT / "flutter_app" / name, project / name, dirs_exist_ok=True)
        shutil.copy2(ROOT / "flutter_app/pubspec.yaml", project)
        subprocess.run([sys.executable, str(ROOT / "ops/qa/prepare_android_release.py"),
                        str(project), PACKAGE, LABEL], check=True)
        if not keystore.exists():
            subprocess.run(["keytool", "-genkeypair", "-keystore", str(keystore),
                            "-storepass", "android", "-keypass", "android", "-alias",
                            "androiddebugkey", "-keyalg", "RSA", "-keysize", "2048",
                            "-validity", "365", "-dname", "CN=PRIVATE DRIVE QA43,O=QA,C=LT"],
                           check=True)
        keystore.chmod(0o600)
        shutil.copy2(keystore, project / "android/app/qa43-signing.jks")
        gradle = project / "android/app/build.gradle.kts"
        text = gradle.read_text()
        assert text.count("    buildTypes {") == 1
        gradle.write_text(text.replace("    buildTypes {", """    signingConfigs {
        getByName("debug") {
            storeFile = file("qa43-signing.jks")
        }
    }
    buildTypes {"""))
        subprocess.run(["flutter", "build", "apk", "--release",
                        "--target=lib/qa43_android_main.dart",
                        f"--build-name={VERSION}", f"--build-number={BUILD_NUMBER}",
                        f"--dart-define=PD_NATIVE_AUTH_API_URL=https://{args.address}",
                        f"--dart-define=PD_QA43_LAB_CA={base64.b64encode(ca).decode()}",
                        "--dart-define=PD_ISOLATED_DEVICE_QA=true",
                        "--dart-define=PD_QA43_NATIVE_BOOKING=true"], cwd=project, check=True)
        apk = project / "build/app/outputs/flutter-apk/app-release.apk"
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(apk, output)


if __name__ == "__main__":
    main()
