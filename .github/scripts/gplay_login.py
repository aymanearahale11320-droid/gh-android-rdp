#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
تسجيل دخول Google تلقائيًا داخل محاكي Play، مع نشر رقم التحقق
(مثل 77) إلى ملف الحالة ليظهر فورًا في تطبيق Server Manager.

متغيرات البيئة:
  GPLAY_EMAIL / GPLAY_PASSWORD   (إلزامي)
  ADB_SERIAL                     (افتراضي emulator-5554)
  STATUS_FILE                    (من الـworkflow)
  GPLAY_PUBLISH=0                تعطيل النشر (للاختبار المحلي)
  GPLAY_TIMEOUT                  ثواني الانتظار للتحقق (افتراضي 900)
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
TIMEOUT = int(os.environ.get("GPLAY_TIMEOUT", "900"))
VERIFY_WAIT = int(os.environ.get("GPLAY_VERIFY_WAIT", "75"))
VERIFY_TRIES = int(os.environ.get("GPLAY_VERIFY_TRIES", "5"))
PUBLISH = os.environ.get("GPLAY_PUBLISH", "1") != "0" and bool(os.environ.get("GH_TOKEN"))
SETUP_ONLY = "--setup-only" in sys.argv


def log(*a):
    print("[gplay]", *a, flush=True)


def publish(**kw):
    if not PUBLISH:
        log("publish(skip)", kw)
        return
    pairs = " ".join(f"{k}={v}" for k, v in kw.items())
    cmd = f"source .github/scripts/publish.sh; publish_set {pairs}"
    subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True)


def texts(d):
    try:
        xml = d.dump_hierarchy()
    except Exception:
        return []
    return re.findall(r'text="([^"]*)"', xml) + re.findall(r'content-desc="([^"]*)"', xml)


def has(d, needle):
    n = needle.lower()
    return any(n in t.lower() for t in texts(d))


def tap_text(d, needle):
    esc = re.escape(needle)
    for el in (d(text=needle), d(textContains=needle),
               d(textMatches=f"(?i).*{esc}.*"),
               d(descriptionContains=needle),
               d(descriptionMatches=f"(?i).*{esc}.*")):
        try:
            if el.exists:
                el.click()
                return True
        except Exception:
            continue
    return False


def email_field(d):
    return d(className="android.widget.EditText", resourceId="identifierId").exists


def wait_screen(d, predicate, seconds):
    end = time.time() + seconds
    while time.time() < end:
        try:
            if predicate():
                return True
        except Exception:
            pass
        time.sleep(1.5)
    return False


def set_field(d, value):
    els = d(className="android.widget.EditText")
    if not els.count:
        return False
    e = els[0]
    e.click()
    time.sleep(0.8)
    e.set_text(value)
    time.sleep(0.8)
    d.press("back")
    time.sleep(0.8)
    return True


def signed_in(d):
    try:
        out = d.shell("dumpsys account")
    except Exception:
        return False
    out = getattr(out, "output", None) or str(out)
    return EMAIL.lower() in str(out).lower()


def finish_play_setup(d):
    """أكمل إعداد متجر Play بعد استعادة البذرة.

    شاشة «Use password» نافذة آمنة (FLAG_SECURE) لا تظهر في screencap،
    فتبدو المِرآة سوداء. نُدخل كلمة السر ونضغط Done عبر uiautomator ثم
    نُغلق تلميحات القائمة حتى يصل المستخدم إلى متجر جاهز ومرئي.
    """
    try:
        d.shell("monkey -p com.android.vending -c android.intent.category.LAUNCHER 1")
    except Exception:
        pass
    end = time.time() + 90
    while time.time() < end:
        ts = texts(d)
        joined = " ".join(ts).lower()
        try:
            if "use password" in joined or "verify your purchases" in joined:
                tap_text(d, "Use password")
                time.sleep(2)
                els = d(className="android.widget.EditText")
                if els.count:
                    els[0].set_text(PASSWORD)
                    time.sleep(1)
                    tap_text(d, "Done")
                    time.sleep(4)
                continue
            if "get started" in joined or "welcome to google play" in joined:
                tap_text(d, "Get started")
                time.sleep(3)
                continue
            if "got it" in joined:
                tap_text(d, "Got it")
                time.sleep(1)
                continue
            if ("signed in as" in joined or "top charts" in joined
                    or "recommended for you" in joined):
                log("play store ready")
                d.press("home")
                return True
        except Exception as e:
            log("play setup step:", repr(e))
        time.sleep(2)
    log("play setup timeout (continuing)")
    return False


def find_code(ts):
    """رقم التحقق: يظهر أحيانًا وحده (77) وأحيانًا داخل جملة (tap 5 on your phone)."""
    joined = " ".join(ts)
    m = re.search(r"tap\s+(\d{1,2})\s+on\s+your\s+phone", joined, re.I)
    if m:
        return m.group(1)
    m = re.search(r"then\s+tap\s+(\d{1,2})", joined, re.I)
    if m:
        return m.group(1)
    for t in ts:
        t = t.strip()
        if re.fullmatch(r"\d{2}", t) and 10 <= int(t) <= 99:
            return t
    return ""


def _publish_state(code="", state="", attempt=0):
    publish(VERIFY=code, VERIFY_STATE=state,
            VERIFY_KIND="phone_tap" if code else "",
            VERIFY_TRY=str(attempt) if attempt else "",
            VERIFY_AT=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


def handle_verify(d):
    """دورة كاملة: رقم → انتظار الموافقة → «تمت الموافقة»، أو مهلة → رقم جديد."""
    for attempt in range(1, VERIFY_TRIES + 1):
        code = ""
        find_end = time.time() + 30
        while time.time() < find_end:
            ts = texts(d)
            joined = " ".join(ts).lower()
            code = find_code(ts)
            if code:
                break
            if "resend it" in joined:
                tap_text(d, "Resend it")
                time.sleep(3)
                continue
            if "choose how you want to sign in" in joined:
                tap_text(d, "Tap Yes on your phone")
                time.sleep(3)
                continue
            if "use your password" in joined or "enter your password" in joined:
                if tap_text(d, "Use your password"):
                    time.sleep(2)
                    set_field(d, PASSWORD)
                    tap_text(d, "NEXT")
                    time.sleep(3)
            time.sleep(1.5)
        if not code:
            log("no verify code on screen (attempt %d)" % attempt)
            return signed_in(d)

        log("verify code:", code, "attempt", attempt)
        _publish_state(code, "pending", attempt)
        approved = False
        wait_end = time.time() + VERIFY_WAIT
        while time.time() < wait_end:
            time.sleep(3)
            if signed_in(d):
                approved = True
                break
            cur = " ".join(texts(d)).lower()
            if (f"tap {code}" not in cur and "tap yes" not in cur
                    and "check your" not in cur):
                approved = True
                break
        if approved:
            log("approved", code)
            publish(VERIFY="", VERIFY_STATE="approved", VERIFY_KIND="",
                    VERIFY_TRY=str(attempt))
            time.sleep(6)
            publish(VERIFY_STATE="")
            return signed_in(d)

        log("expired", code)
        publish(VERIFY="", VERIFY_STATE="expired", VERIFY_KIND="",
                VERIFY_TRY=str(attempt))
        if not tap_text(d, "Resend it"):
            tap_text(d, "TRY ANOTHER WAY")
            time.sleep(2)
            tap_text(d, "Tap Yes on your phone")
        time.sleep(4)
    publish(VERIFY="", VERIFY_STATE="")
    return signed_in(d)


def main():
    if not EMAIL or not PASSWORD:
        log("missing credentials")
        return 2
    d = u2.connect(SERIAL)
    log("connected", d.info.get("productName"), d.info.get("sdkInt"))

    if SETUP_ONLY:
        finish_play_setup(d)
        return 0

    if signed_in(d):
        log("already signed in")
        finish_play_setup(d)
        publish(GPLAY=1, VERIFY="")
        return 0

    d.shell("am start -a android.settings.SYNC_SETTINGS")
    for _ in range(20):
        time.sleep(1)
        if has(d, "Add account"):
            break
    if not tap_text(d, "Add account"):
        log("Add account not found")
        return 3
    time.sleep(2)
    if not tap_text(d, "Google"):
        log("Google row not found")
        return 3
    log("google sign-in opened")

    # شاشة "Sign in with ease" (البحث برقم الهاتف) → تخطٍّ
    def ready_for_email():
        if has(d, "SKIP") or has(d, "Sign in with ease"):
            tap_text(d, "SKIP")
            time.sleep(2)
        return email_field(d)

    if not wait_screen(d, ready_for_email, 90):
        log("email screen not found")
        return 4
    if not set_field(d, EMAIL):
        log("email field not found")
        return 4
    tap_text(d, "NEXT")
    log("email submitted")

    if not wait_screen(d, lambda: not email_field(d) and
                       d(className="android.widget.EditText").count > 0, 60):
        log("password screen not found")
        return 4
    if not set_field(d, PASSWORD):
        log("password field not found")
        return 4
    tap_text(d, "NEXT")
    log("password submitted")

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
        ts = texts(d)
        joined = " ".join(ts).lower()
        if ("i agree" in joined or "accept" in joined
                or ("backup" in joined and "next" in joined)):
            (tap_text(d, "No thanks") or tap_text(d, "I agree")
             or tap_text(d, "Accept") or tap_text(d, "NEXT")
             or tap_text(d, "Next") or tap_text(d, "Done"))
            time.sleep(2)
            continue
        if "verify it" in joined and ("tap yes" in joined or "check your" in joined):
            if handle_verify(d):
                publish(GPLAY=1, VERIFY="", VERIFY_STATE="")
                return 0
            continue
        if "couldn't sign in" in joined or "try again" in joined:
            log("google refused sign-in")
            publish(GPLAY=0, VERIFY="", VERIFY_STATE="")
            return 5
        time.sleep(2)

    log("timeout")
    publish(VERIFY="", VERIFY_STATE="")
    return 6


if __name__ == "__main__":
    sys.exit(main())
