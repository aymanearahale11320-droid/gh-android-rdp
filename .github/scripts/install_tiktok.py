#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""تثبيت تيك توك لايت من Play Store داخل المحاكي."""
import re
import sys
import time

import uiautomator2 as u2

PKG = "com.tiktok.lite.go"
d = u2.connect("emulator-5554")


def texts():
    try:
        xml = d.dump_hierarchy()
    except Exception:
        return []
    return [t for t in re.findall(r'text="([^"]*)"', xml) if t.strip()]


def tap(label):
    for el in (d(text=label), d(text=label.upper()), d(textContains=label),
               d(description=label), d(descriptionContains=label)):
        try:
            if el.exists:
                el.click()
                return True
        except Exception:
            pass
    return False


def installed():
    out = d.shell(f"pm list packages | grep -F {PKG}")
    out = getattr(out, "output", None) or str(out)
    return PKG in out


print("[tiktok] initial:", texts()[:10])
if installed():
    print("[tiktok] already installed")
    sys.exit(0)

d.shell(f'am start -a android.intent.action.VIEW -d "market://details?id={PKG}"')
print("[tiktok] opened market://")
end = time.time() + 240
while time.time() < end:
    ts = texts()
    j = " ".join(ts).lower()
    if installed():
        print("[tiktok] INSTALLED")
        break
    for lbl in ("Install", "Accept", "Got it", "Continue", "Open"):
        if tap(lbl):
            print("[tiktok] tapped", lbl)
            time.sleep(4)
            break
    else:
        time.sleep(3)
else:
    print("[tiktok] TIMEOUT")

print("[tiktok] final:", texts()[:12])
# افتح التطبيق للتأكد من عدم الانهيار
d.shell(f"monkey -p {PKG} -c android.intent.category.LAUNCHER 1")
time.sleep(12)
print("[tiktok] focus:", d.shell("dumpsys window | grep mCurrentFocus").strip())
