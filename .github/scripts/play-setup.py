#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import re
import time

import uiautomator2 as u2

PW = open("/opt/android-server/gplay_pw", encoding="utf-8").read().strip()
d = u2.connect("emulator-5554")
print("connected", d.info.get("productName"))


def texts():
    try:
        xml = d.dump_hierarchy()
    except Exception:
        return ""
    return xml


for i in range(12):
    xml = texts()
    low = xml.lower()
    if "use password" in low:
        print("step", i, "Use password")
        try:
            d(textContains="Use password").click()
        except Exception:
            pass
        time.sleep(2)
    elif "you're setting password" in low or "enter your password" in low:
        print("step", i, "set password")
        els = d(className="android.widget.EditText")
        if els.count:
            els[0].set_text(PW)
            time.sleep(1)
        try:
            if d(text="Done").exists:
                d(text="Done").click(timeout=3)
            else:
                d.press("enter")
        except Exception:
            d.press("enter")
        time.sleep(5)
    elif "get started" in low:
        print("step", i, "Get started")
        try:
            d(textContains="Get started").click()
        except Exception:
            pass
        time.sleep(3)
    elif "got it" in low:
        print("step", i, "Got it")
        try:
            d(textContains="Got it").click()
        except Exception:
            pass
        time.sleep(1)
    else:
        print("PLAY_SETUP_DONE")
        d.press("home")
        break
else:
    print("PLAY_SETUP_TIMEOUT")
