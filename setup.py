"""py2app build configuration for CC Usage Tracker."""

from setuptools import setup

APP = ["app.py"]
DATA_FILES = []

OPTIONS = {
    "argv_emulation": False,  # True crashes pyobjc's event loop
    "plist": {
        "CFBundleName": "CC Usage Tracker",
        "CFBundleIdentifier": "com.cc-usage-tracker.app",
        "CFBundleVersion": "1.0.0",
        "CFBundleShortVersionString": "1.0.0",
        "LSUIElement": True,  # hide from Dock (menu bar app)
    },
    "packages": [
        "rumps",
        "requests",
        "keyring",
        "pycookiecheat",
        "certifi",
        "cryptography",
        "cffi",
        "charset_normalizer",
        "providers",
    ],
    "includes": [
        "views",
        "login_item",
        "_cffi_backend",
    ],
}

setup(
    app=APP,
    name="CC Usage Tracker",
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
