#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""يُكمل نافذة Google المحمية (Use password) تلقائيًا.

نافذة إدخال كلمة سر Google volatile FLAG_SECURE ⇒ screencap يعطي أسود.
هذا المُصحّح يقرأ الواجهة عبر uiautomator2 (يعمل حتى مع FLAG_SECURE)
ويضغط Use password → يُدخل كلمة السر → Done → Got it ⇒ تختفي الشاشة السوداء.
خفيف جدًا (فحص كل 3 ثوانٍ) — لا يلمس إعدادات الأداء.
"""
import os
import re
import subprocess
import time

import uiautomator2 as u2

PWFILE = "/opt/android-server/gplay_pw"
PASSWORD = ""
if os.path.exists(PWFILE):
    try:
        PASSWORD = open(PWFILE, encoding="utf-8").read().strip()
    except Exception:
        pass
if not PASSWORD:
    PASSWORD = os.environ.get("GPLAY_PASSWORD", "")

d = u2.connect("emulator-5554")


def texts():
    try:
        xml = d.dump_hierarchy()
    except Exception:
        return []
    return [t for t in re.findall(r'text="([^"]*)"', xml) if t.strip()]


def tap(label):
    for el in (d(text=label), d(text=label.upper()), d(textContains=label),
               d(descriptionContains=label)):
        try:
            if el.exists:
                el.click()
                return True
        except Exception:
            pass
    return False


def focus():
    try:
        out = d.shell("dumpsys window | grep mCurrentFocus")
        return getattr(out, "output", None) or str(out)
    except Exception:
        return ""


print("[secure-fix] started, pw=", bool(PASSWORD), flush=True)
while True:
    try:
        f = focus()
        if ("com.android.vending" in f or "com.google.android.gms" in f) and PASSWORD:
            ts = texts()
            j = " ".join(ts).lower()
            if "use password" in j:
                tap("Use password")
                time.sleep(2)
            elif ("setting password" in j or "enter your password" in j
                  or "show password" in j):
                els = d(className="android.widget.EditText")
                if els.count:
                    els[0].set_text(PASSWORD)
                    time.sleep(0.8)
                    tap("Done") or tap("NEXT") or d.press("enter")
                    time.sleep(3)
            elif "got it" in j:
                tap("Got it")
                time.sleep(1)
            elif "welcome to google play" in j or "get started" in j:
                tap("Get started")
                time.sleep(2)
    except Exception:
        pass
    time.sleep(3)
