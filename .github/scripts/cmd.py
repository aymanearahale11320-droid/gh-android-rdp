#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""مُنسّق أوامر خفيف يعمل على السيرفر.

يستقبل سطرًا واحدًا (عربي أو إنجليزي) من شريط الأوامر في Server Manager
ويحوّله إلى أمر adb / ctl.sh / سكربت جاهز. لا يستخدم أي LLM — سريع ومحلي 100%.
"""
import os
import subprocess
import sys

ADB = "/usr/local/lib/android/sdk/platform-tools/adb"
DEV = "emulator-5554"
CTL = os.path.expanduser("~/bin/ctl.sh")


def sh(cmd, timeout=180):
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           timeout=timeout)
        out = (p.stdout or "") + (p.stderr or "")
        return out.strip() or f"done (rc={p.returncode})"
    except subprocess.TimeoutExpired:
        return "ERR: timeout"
    except Exception as e:
        return f"ERR: {e}"


def adb(args, timeout=60):
    return sh(f"{ADB} -s {DEV} {args}", timeout)


HELP = """الأوامر المتاحة / available commands:
  install tiktok lite | ثبت تيك توك لايت   → تثبيت وفتح تيك توك لايت
  open chrome <url>   | افتح كروم <رابط>    → فتح رابط في كروم
  open youtube        | افتح يوتيوب
  open play           | افتح بلاي ستور
  home | الرئيسية                          → الشاشة الرئيسية
  back | رجوع                             → رجوع
  stats | الأداء                           → إحصائيات السيرفر
  !adb <args>                              → تمرير adb مباشر
  !ctl <args>                              → تمرير ctl.sh مباشر
  !sh <cmd>                                → تمرير shell مباشر
  help | مساعدة                            → هذه القائمة
"""


def run(line):
    s = " ".join(line.split()).strip()
    low = s.lower()

    if low in ("help", "?", "مساعدة", "أوامر"):
        return HELP

    # تمرير مباشر
    for prefix, fn in (("!adb ", lambda r: adb(r)),
                       ("!ctl ", lambda r: sh(f"bash {CTL} {r}")),
                       ("!sh ", lambda r: sh(r))):
        if low.startswith(prefix):
            return fn(s[len(prefix):])

    # تيك توك لايت
    if any(k in low for k in ("tiktok", "تيك توك", "تيكtok")) and any(
            k in low for k in ("install", "ثبت", "تثبيت", "نزّل", "نزل")):
        if os.path.exists(os.path.expanduser("~/bin/install_tiktok.py")):
            return sh("python3 ~/bin/install_tiktok.py", timeout=300)
        return sh(f"am start -a android.intent.action.VIEW -d "
                  f"'market://details?id=com.tiktok.lite.go'", timeout=60)

    # فتح رابط في كروم
    if any(k in low for k in ("chrome", "كروم")) and any(
            k in low for k in ("open", "افتح", "افتحى")):
        url = ""
        for tok in s.split():
            if tok.startswith(("http://", "https://")):
                url = tok
                break
        if not url:
            return "ERR: أرفق الرابط — مثال: open chrome https://example.com"
        return sh(f"bash {CTL} open-url {subprocess.list2cmdline([url])}", timeout=60)

    if any(k in low for k in ("youtube", "يوتيوب")) and any(
            k in low for k in ("open", "افتح")):
        return adb("shell am start -a android.intent.action.VIEW -d https://www.youtube.com")

    if any(k in low for k in ("play store", "بلاي ستور", "متجر")) and any(
            k in low for k in ("open", "افتح")):
        return adb("shell monkey -p com.android.vending -c android.intent.category.LAUNCHER 1")

    if low in ("home", "الرئيسية", "الشاشة الرئيسية"):
        return adb("shell input keyevent 3")
    if low in ("back", "رجوع"):
        return adb("shell input keyevent 4")
    if low in ("stats", "الأداء", "اداء"):
        return sh(f"bash {CTL} stats")
    if low in ("screenshot", "صورة", "لقطة"):
        return adb("exec-out screencap -p > /tmp/cmd_shot.png && echo /tmp/cmd_shot.png")

    # رابط فقط → كروم
    if low.startswith(("http://", "https://")):
        return sh(f"bash {CTL} open-url {subprocess.list2cmdline([low])}", timeout=60)

    return ("ERR: لم أفهم الأمر. اكتب 'help' أو 'مساعدة' لعرض الأوامر.\n"
            "أو استخدم !adb / !ctl / !sh للتمرير المباشر.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(HELP)
        sys.exit(0)
    print(run(" ".join(sys.argv[1:])))
