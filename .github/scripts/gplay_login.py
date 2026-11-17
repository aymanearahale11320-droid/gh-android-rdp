#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""تسجيل دخول Google تلقائيًا (API 30/35) داخل محاكي Play.

ينشر VERIFY=<الرقم> و VERIFY_STATE=pending/approved/expired إلى ملف الحالة
ليظهر فورًا في تطبيق Server Manager.
"""
import os
import re
import subprocess
import sys
import time

import uiautomator2 as u2

EMAIL = os.environ.get("GPLAY_EMAIL", "")
PASSWORD = os.environ.get("GPLAY_PASSWORD", "")
SERIAL = os.environ.get("ADB_SERIAL", "emulator-5554")
VERIFY_WAIT = int(os.environ.get("GPLAY_VERIFY_WAIT", "75"))
VERIFY_TRIES = int(os.environ.get("GPLAY_VERIFY_TRIES", "5"))
PUBLISH = os.environ.get("GPLAY_PUBLISH", "1") != "0" and bool(os.environ.get("GH_TOKEN"))


def log(*a):
    print("[gplay]", *a, flush=True)


def publish(**kw):
    if not PUBLISH:
        return
    pairs = " ".join(f"{k}={v}" for k, v in kw.items())
    subprocess.run(["bash", "-lc",
                    f"source .github/scripts/publish.sh; publish_set {pairs}"],
                   capture_output=True, text=True)


def texts(d):
    try:
        xml = d.dump_hierarchy()
    except Exception:
        return []
    return [t for t in re.findall(r'text="([^"]*)"', xml) if t.strip()]


def joined(d):
    return " ".join(texts(d)).lower()


def tap(d, label):
    """يضغط على زر/نص حتى لو كان NEXT بحروف كبيرة."""
    cands = [d(text=label), d(text=label.upper()), d(text=label.lower()),
             d(textContains=label), d(description=label),
             d(descriptionContains=label)]
    for el in cands:
        try:
            if el.exists:
                el.click()
                return True
        except Exception:
            pass
    return False


def set_first(d, value):
    els = d(className="android.widget.EditText")
    if not els.count:
        return False
    e = els[0]
    e.click()
    time.sleep(0.4)
    e.set_text(value)
    time.sleep(0.4)
    return True


def signed_in(d):
    try:
        out = d.shell("dumpsys account")
    except Exception:
        return False
    out = getattr(out, "output", None) or str(out)
    return EMAIL.lower() in str(out).lower()


def find_code(d):
    m = re.search(r"tap\s+(\d{1,2})", joined(d))
    if m:
        return m.group(1)
    for t in texts(d):
        if re.fullmatch(r"\d{2}", t.strip()) and 10 <= int(t) <= 99:
            return t.strip()
    return ""


def publish_state(code="", state="", attempt=0):
    publish(VERIFY=code, VERIFY_STATE=state,
            VERIFY_KIND="phone_tap" if code else "",
            VERIFY_TRY=str(attempt) if attempt else "",
            VERIFY_AT=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


def finish_play_setup(d):
    """أكمل شاشات Play الأولى (Use password / Got it) التي لا تظهر في screencap."""
    try:
        d.shell("monkey -p com.android.vending -c android.intent.category.LAUNCHER 1")
    except Exception:
        pass
    end = time.time() + 90
    while time.time() < end:
        j = joined(d)
        try:
            if "use password" in j or "verify your purchases" in j:
                tap(d, "Use password")
                time.sleep(2)
                if d(className="android.widget.EditText").count:
                    d(className="android.widget.EditText")[0].set_text(PASSWORD)
                    time.sleep(1)
                tap(d, "Done")
                time.sleep(4)
            elif "get started" in j or "welcome to google play" in j:
                tap(d, "Get started")
                time.sleep(3)
            elif "got it" in j:
                tap(d, "Got it")
                time.sleep(1)
            elif "signed in as" in j or "top charts" in j or "recommended for you" in j:
                log("play store ready")
                d.press("home")
                return True
        except Exception as e:
            log("setup step:", repr(e))
        time.sleep(2)
    return False


def handle_verify(d):
    for attempt in range(1, VERIFY_TRIES + 1):
        code = ""
        end = time.time() + 30
        while time.time() < end:
            code = find_code(d)
            if code:
                break
            j = joined(d)
            if "resend it" in j:
                tap(d, "Resend it")
                time.sleep(3)
                continue
            if "choose how you want to sign in" in j:
                tap(d, "Tap Yes on your phone")
                time.sleep(3)
                continue
            time.sleep(1.5)
        if not code:
            return signed_in(d)
        log("verify code", code, "attempt", attempt)
        publish_state(code, "pending", attempt)
        approved = False
        wait_end = time.time() + VERIFY_WAIT
        while time.time() < wait_end:
            time.sleep(3)
            if signed_in(d):
                approved = True
                break
            cur = joined(d)
            if (f"tap {code}" not in cur and "tap yes" not in cur
                    and "check your" not in cur):
                approved = True
                break
        if approved:
            log("approved", code)
            publish(VERIFY="", VERIFY_STATE="approved", VERIFY_TRY=str(attempt))
            time.sleep(5)
            publish(VERIFY_STATE="")
            return signed_in(d)
        log("expired", code)
        publish(VERIFY="", VERIFY_STATE="expired", VERIFY_TRY=str(attempt))
        if not tap(d, "Resend it"):
            tap(d, "TRY ANOTHER WAY")
            time.sleep(2)
            tap(d, "Tap Yes on your phone")
        time.sleep(4)
    return signed_in(d)


def main():
    if not EMAIL or not PASSWORD:
        log("missing credentials")
        return 2
    d = u2.connect(SERIAL)
    log("connected", d.info.get("productName"), d.info.get("sdkInt"))

    if signed_in(d):
        log("already signed in")
        finish_play_setup(d)
        publish(GPLAY=1, VERIFY="")
        return 0

    # API35: SYNC_SETTINGS لا يُظهر «إضافة حساب»، استخدم ADD_ACCOUNT_SETTINGS
    d.shell("am start -a android.settings.ADD_ACCOUNT_SETTINGS")
    time.sleep(4)
    if not tap(d, "Google"):
        d.shell("am start -a android.settings.SYNC_SETTINGS")
        time.sleep(3)
        if not tap(d, "Add account"):
            log("Add account not found")
            return 3
        time.sleep(2)
        tap(d, "Google")
    log("google row opened")

    # شاشة البريد
    for i in range(40):
        if d(className="android.widget.EditText").count:
            break
        j = joined(d)
        if "sign in with ease" in j or "skip" in j:
            tap(d, "SKIP")
        time.sleep(1)
    if not set_first(d, EMAIL):
        log("email field not found")
        return 4
    tap(d, "NEXT")
    log("email submitted")
    time.sleep(6)

    # شاشة كلمة السر
    for i in range(30):
        if "forgot password" in joined(d) or d(className="android.widget.EditText").count:
            break
        time.sleep(1)
    if not set_first(d, PASSWORD):
        log("password field not found")
        return 4
    tap(d, "NEXT")
    log("password submitted")
    time.sleep(8)

    if handle_verify(d):
        log("signed in")
        finish_play_setup(d)
        publish(GPLAY=1, VERIFY="", VERIFY_STATE="")
        return 0

    end = time.time() + 300
    while time.time() < end:
        if signed_in(d):
            log("signed in")
            finish_play_setup(d)
            publish(GPLAY=1, VERIFY="", VERIFY_STATE="")
            return 0
        j = joined(d)
        if "i agree" in j or "accept" in j or ("backup" in j and "next" in j):
            for lbl in ("No thanks", "I agree", "Accept", "NEXT", "Next", "Done"):
                if tap(d, lbl):
                    break
            time.sleep(2)
            continue
        if "verify it" in j and ("tap yes" in j or "check your" in j):
            if handle_verify(d):
                publish(GPLAY=1, VERIFY="", VERIFY_STATE="")
                return 0
            continue
        if "couldn't sign in" in j or "try again" in j:
            log("google refused sign-in")
            publish(GPLAY=0, VERIFY="", VERIFY_STATE="")
            return 5
        time.sleep(2)

    log("timeout")
    publish(VERIFY="", VERIFY_STATE="")
    return 6


if __name__ == "__main__":
    sys.exit(main())
