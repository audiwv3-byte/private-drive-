import plistlib, pathlib, sys, subprocess, hashlib
app = pathlib.Path(sys.argv[1])
def load(path):
    with path.open("rb") as f: return plistlib.load(f)
info = load(app / "Info.plist")
assert info["CFBundleIdentifier"] == "lt.privatedrive.qa.privateDrive"
assert info["DTPlatformName"] == "iphoneos"
assert "iPhoneOS" in info["CFBundleSupportedPlatforms"]
assert info.get("NSCameraUsageDescription") and info.get("NSLocationWhenInUseUsageDescription")
assert not info.get("NSAppTransportSecurity", {}).get("NSAllowsArbitraryLoads", False)
assert not info.get("NSAppTransportSecurity", {}).get("NSExceptionDomains")
assert info.get("UIBackgroundModes") == ["location"]
assert info.get("NSLocationAlwaysAndWhenInUseUsageDescription")
assert "NSMicrophoneUsageDescription" not in info
assert "NSPhotoLibraryUsageDescription" not in info
privacy = load(app / "PrivacyInfo.xcprivacy")
assert privacy["NSPrivacyTracking"] is False and not privacy["NSPrivacyTrackingDomains"]
assert all(not x["NSPrivacyCollectedDataTypeTracking"] for x in privacy["NSPrivacyCollectedDataTypes"])
assert any(x["NSPrivacyAccessedAPIType"] == "NSPrivacyAccessedAPICategoryUserDefaults" and "CA92.1" in x["NSPrivacyAccessedAPITypeReasons"] for x in privacy["NSPrivacyAccessedAPITypes"])
exe = app / info["CFBundleExecutable"]
arch = subprocess.check_output(["lipo", "-archs", str(exe)], text=True).strip()
assert arch == "arm64", arch
platform = subprocess.check_output(["xcrun", "vtool", "-show-build", str(exe)], text=True)
assert "platform IOS" in platform and "IOSSIMULATOR" not in platform, platform
print("PASS iphoneos arm64 Release bundle, isolated ID, ATS, consented background location capability, privacy manifest")
print("SDK:", info.get("DTSDKName"), "min iOS:", info.get("MinimumOSVersion"))
print("Executable SHA256:", hashlib.sha256(exe.read_bytes()).hexdigest())
for p in sorted(app.rglob("PrivacyInfo.xcprivacy")):
    load(p)
    print("Privacy manifest:", p.relative_to(app))
