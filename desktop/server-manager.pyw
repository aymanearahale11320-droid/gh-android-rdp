# -*- coding: utf-8 -*-
"""
Server Manager — لوحة تحكم سيرفرات GitHub Actions (Android 11 · Play Store · RDP)

- تقرأ الحالة من Tailscale + ملفات status-N.txt في المستودع
- تتحكم فعليًا عبر ADB / SSH / GitHub CLI
- كلمة سر مستقلة لكل سيرفر تُحفظ محليًا وتظهر عند الإنشاء وفي الجدول
- تغيير IMEI / MAC / GPS / Android ID / بروكسي من الخارج
- إيقاف/حذف حقيقي + إدارة ذكية لحالة الأزرار + إحصائيات أداء حيّة
"""

import json
import io
import os
import re
import secrets
import shlex
import socket
import shutil
import subprocess
import tempfile
import threading
import time
import calendar
import webbrowser
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except Exception:
    HAS_PIL = False

try:
    import paramiko
    HAS_SSH = True
except Exception:
    HAS_SSH = False

# ─────────────────────────── إعدادات ───────────────────────────
REPO = "aymanearahale11320-droid/gh-android-rdp"
WORKFLOW = "final-android-desktop.yml"
LOCAL = os.environ.get("LOCALAPPDATA", r"C:\Users\DELL\AppData\Local")
ADB = os.path.join(LOCAL, r"Programs\scrcpy\adb.exe")
SCRCPY = os.path.join(LOCAL, r"Programs\scrcpy\scrcpy.exe")
GH = os.path.join(LOCAL, r"Programs\gh\bin\gh.exe")
TS = r"C:\Program Files\Tailscale\tailscale.exe"
STORE = os.path.join(LOCAL, "ServerManager", "servers.json")
KEYDIR = os.path.join(LOCAL, "ServerManager")
PRIVKEY = os.path.join(KEYDIR, "id_server_manager")
PUBKEY = PRIVKEY + ".pub"

RDP_USER = "runner"
JOB_HOURS = 6
NO_WINDOW = 0x08000000
REFRESH_SEC = 10

# مسار adb على السيرفر (يُستخدم داخل SSH)
RADB = "/usr/local/lib/android/sdk/platform-tools/adb"

BG = "#14151b"
PANEL = "#1d1f28"
CARD = "#232634"
FG = "#e9ebf2"
MUTED = "#8b93a7"
ACCENT = "#3b5bdb"
GREEN = "#63e6a3"
RED = "#ff6b6b"
ORANGE = "#ffb454"
CYAN = "#4dd4e8"


# ─────────────────────────── أدوات ───────────────────────────
def sh(cmd, timeout=30):
    """ينفّذ أمرًا ويعيد (stdout+stderr) كنص."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, creationflags=NO_WINDOW)
        return ((p.stdout or "") + (p.stderr or "")).strip()
    except Exception as e:
        return f"__ERR__ {e}"


def popen(cmd):
    try:
        subprocess.Popen(cmd, creationflags=NO_WINDOW)
        return True
    except Exception:
        return False


def gen_password():
    """كلمة سر قوية 16 محرفًا (بدون محارف تُتعب الكتابة اليدوية)."""
    alphabet = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "Rd" + "".join(secrets.choice(alphabet) for _ in range(14))


def gen_imei():
    """IMEI صحيح Luhn (15 رقمًا) — فريد لكل سيرفر."""
    body = "35" + "".join(str(secrets.randbelow(10)) for _ in range(12))
    total = 0
    for i, ch in enumerate(body):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return body + str((10 - total % 10) % 10)


def gen_mac():
    """MAC محلي unicast: 02:xx:xx:xx:xx:xx"""
    return "02:" + ":".join(f"{secrets.randbelow(256):02X}" for _ in range(5))


def parse_row(line):
    """يحوّل 'A=1|B=2' إلى dict."""
    out = {}
    for part in (line or "").split("|"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def fmt_remaining(start_iso):
    if not start_iso:
        return ""
    try:
        t = time.strptime(start_iso.replace("Z", "")[:19], "%Y-%m-%dT%H:%M:%S")
        left = int(calendar.timegm(t) + JOB_HOURS * 3600 - time.time())
        if left <= 0:
            return "انتهى"
        return f"{left // 3600}h {(left % 3600) // 60}m"
    except Exception:
        return ""


def load_store():
    """يقرأ الأسرار المحلية، ويستعيد النسخة الاحتياطية إن تلف الملف الأساسي."""
    def _read(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    data = _read(STORE)
    if not (data.get("servers") or {}):
        backup = _read(STORE + ".bak")
        if backup.get("servers"):
            return backup
    return data or {"servers": {}}


def save_store(data):
    """كتابة ذرّية + نسخة احتياطية (حتى لا تُفقد كلمات السر)."""
    try:
        os.makedirs(os.path.dirname(STORE), exist_ok=True)
        tmp = STORE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
        try:
            if os.path.exists(STORE) and os.path.getsize(STORE) > 20:
                shutil.copy2(STORE, STORE + ".bak")
        except Exception:
            pass
        os.replace(tmp, STORE)
    except Exception:
        pass


def ensure_ssh_key():
    """مفتاح SSH محلي دائم — يسمح بالتحكم بلا كلمة سر (أكثر متانة)."""
    if not HAS_SSH:
        return None, ""
    try:
        os.makedirs(KEYDIR, exist_ok=True)
        if os.path.exists(PRIVKEY):
            key = paramiko.RSAKey.from_private_key_file(PRIVKEY)
            pub = ""
            if os.path.exists(PUBKEY):
                pub = open(PUBKEY, "r", encoding="utf-8").read().strip()
            return key, pub
        key = paramiko.RSAKey.generate(2048)
        key.write_private_key_file(PRIVKEY)
        pub = f"{key.get_name()} {key.get_base64()} server-manager"
        with open(PUBKEY, "w", encoding="utf-8") as fh:
            fh.write(pub + "\n")
        return key, pub
    except Exception:
        return None, ""


def adb_state(serial):
    """يعيد حالة جهاز adb: device / unauthorized / offline / '' (غير موجود)."""
    out = sh([ADB, "devices"], timeout=10)
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == serial:
            return parts[1]
    return ""


# ─────────────────────────── نافذة الإنشاء ───────────────────────────
class CreateDialog(tk.Toplevel):
    def __init__(self, master, slots_used):
        super().__init__(master)
        self.title("إنشاء سيرفر جديد")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self.result = None

        free = [str(i) for i in range(1, 11) if i not in slots_used] or [str(i) for i in range(1, 11)]
        self.slot = tk.StringVar(value=free[0])
        self.inst = tk.StringVar(value="1")
        self.mode = tk.StringVar(value="play")
        self.desk = tk.BooleanVar(value=False)
        self.pw = tk.StringVar(value=gen_password())
        self.imei = tk.StringVar(value=gen_imei())

        pad = {"padx": 12, "pady": 6}
        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", **pad)
        tk.Label(head, text="سيرفر جديد", bg=BG, fg=FG,
                 font=("Segoe UI", 13, "bold")).pack(side="right")

        grid = tk.Frame(self, bg=BG)
        grid.pack(fill="both", **pad)

        def row(r, label, widget, hint=""):
            tk.Label(grid, text=label, bg=BG, fg=MUTED, width=16, anchor="e").grid(
                row=r, column=2, sticky="e", pady=5, padx=(0, 8))
            widget.grid(row=r, column=1, sticky="ew", pady=5)
            if hint:
                tk.Label(grid, text=hint, bg=BG, fg="#6f7789", anchor="w",
                         font=("Segoe UI", 8)).grid(row=r, column=0, sticky="w", padx=(8, 0))

        ttk.Combobox(grid, textvariable=self.slot, values=[str(i) for i in range(1, 11)],
                     width=8, state="readonly").grid(row=0, column=1, sticky="ew", pady=5)
        tk.Label(grid, text="Slot", bg=BG, fg=MUTED, width=16, anchor="e").grid(row=0, column=2, sticky="e", pady=5, padx=(0, 8))
        tk.Label(grid, text="١٠ سيرفرات متوازية · slot مشغول سيُستبدل", bg=BG, fg="#6f7789",
                 font=("Segoe UI", 8)).grid(row=0, column=0, sticky="w", padx=(8, 0))

        ttk.Combobox(grid, textvariable=self.inst, values=["1", "2", "3"], width=8,
                     state="readonly").grid(row=1, column=1, sticky="ew", pady=5)
        tk.Label(grid, text="عدد المحاكيات", bg=BG, fg=MUTED, width=16, anchor="e").grid(row=1, column=2, sticky="e", pady=5, padx=(0, 8))

        mframe = tk.Frame(grid, bg=BG)
        mframe.grid(row=2, column=1, sticky="w", pady=5)
        for text, val in (("Play Store (بلا روت)", "play"), ("روت كامل (بلا Play)", "root")):
            tk.Radiobutton(mframe, text=text, value=val, variable=self.mode, bg=BG, fg=FG,
                           selectcolor=PANEL, activebackground=BG, activeforeground=FG,
                           font=("Segoe UI", 9)).pack(side="right", padx=6)
        tk.Label(grid, text="الوضع", bg=BG, fg=MUTED, width=16, anchor="e").grid(row=2, column=2, sticky="e", pady=5, padx=(0, 8))

        tk.Checkbutton(grid, text="سطح مكتب لينكس + RDP (يستهلك موارد — أبطأ)",
                       variable=self.desk, bg=BG, fg=FG, selectcolor=PANEL,
                       activebackground=BG, activeforeground=FG,
                       font=("Segoe UI", 9)).grid(row=3, column=1, sticky="w", pady=5)
        tk.Label(grid, text="سطح المكتب", bg=BG, fg=MUTED, width=16, anchor="e").grid(row=3, column=2, sticky="e", pady=5, padx=(0, 8))

        pwf = tk.Frame(grid, bg=BG)
        pwf.grid(row=4, column=1, sticky="ew", pady=5)
        ttk.Entry(pwf, textvariable=self.pw, width=26).pack(side="right")
        ttk.Button(pwf, text="⟳", width=3, command=lambda: self.pw.set(gen_password())).pack(side="right", padx=4)
        tk.Label(grid, text="كلمة السر", bg=BG, fg=MUTED, width=16, anchor="e").grid(row=4, column=2, sticky="e", pady=5, padx=(0, 8))

        imf = tk.Frame(grid, bg=BG)
        imf.grid(row=5, column=1, sticky="ew", pady=5)
        ttk.Entry(imf, textvariable=self.imei, width=26).pack(side="right")
        ttk.Button(imf, text="⟳", width=3, command=lambda: self.imei.set(gen_imei())).pack(side="right", padx=4)
        tk.Label(grid, text="IMEI", bg=BG, fg=MUTED, width=16, anchor="e").grid(row=5, column=2, sticky="e", pady=5, padx=(0, 8))

        note = ("✓ الوضع play: Google Play عامل + كروم + الإعدادات فقط، أقصى سرعة\n"
                "✓ الوضع root: صلاحيات كاملة (تغيير MAC/Android ID)، بلا متجر\n"
                "✓ سطح المكتب معطّل = كل موارد السيرفر للمحاكي (الأسرع)")
        tk.Label(self, text=note, bg=PANEL, fg=MUTED, justify="right",
                 font=("Segoe UI", 8), padx=10, pady=8).pack(fill="x", padx=12, pady=8)

        btns = tk.Frame(self, bg=BG)
        btns.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(btns, text="▶ إنشاء السيرفر", style="Accent.TButton",
                   command=self.ok).pack(side="right", padx=4)
        ttk.Button(btns, text="إلغاء", command=self.destroy).pack(side="right", padx=4)

        self.update_idletasks()
        x = master.winfo_rootx() + max(0, (master.winfo_width() - self.winfo_width()) // 2)
        y = master.winfo_rooty() + 120
        self.geometry(f"+{x}+{y}")

    def ok(self):
        if not re.fullmatch(r"\d{15}", self.imei.get().strip()):
            messagebox.showinfo("تنبيه", "IMEI يجب أن يكون 15 رقمًا", parent=self)
            return
        if len(self.pw.get().strip()) < 6:
            messagebox.showinfo("تنبيه", "كلمة السر قصيرة جدًا", parent=self)
            return
        self.result = {
            "slot": self.slot.get(), "instances": self.inst.get(),
            "mode": self.mode.get(), "desktop": "true" if self.desk.get() else "false",
            "password": self.pw.get().strip(), "imei": self.imei.get().strip(),
        }
        self.destroy()


# ─────────────────────────── المِرآة المدمجة ───────────────────────────
class MirrorWindow(tk.Toplevel):
    """مِرآة حيّة + تحكم سريع داخل الأندرويد.

    - الإدخال عبر **جلسة adb shell دائمة** ⇒ زمن استجابة ~١٠٠ms بدل ثوانٍ
    - الفيديو: بث MJPEG (screenrecord+ffmpeg على المضيف) إن توفر، وإلا صور
    - أزرار: تسريع الجهاز، تخفيض الدقة، إدخال نص، أزرار نظام
    """

    def __init__(self, app, row):
        super().__init__(app)
        self.app = app
        self.row = row
        self.title(f"مِرآة الأندرويد — slot {row.get('slot')} · {row.get('ip')}")
        self.configure(bg=BG)
        self.geometry("540x980+30+10")
        self.running = True
        self.paused = False
        self.client = None
        self.in_chan = None
        self.dev_w = self.dev_h = 0
        self.frames = 0
        self.t_fps = time.time()
        self.fps = 0.0
        self.hi_res = True
        self._drag = None

        bar = tk.Frame(self, bg=PANEL)
        bar.pack(fill="x")
        for txt, cmd in (("◀", lambda: self._key(4)),
                         ("●", lambda: self._key(3)),
                         ("■", lambda: self._key(187)),
                         ("⏻", lambda: self._key(26)),
                         ("⚡", self._boost_perf),
                         ("📋", self._smart_paste),
                         ("🔍", self._toggle_res)):
            tk.Button(bar, text=txt, command=cmd, bg=CARD, fg=FG, relief="flat",
                      width=3).pack(side="right", padx=1, pady=3)
        self.pause_btn = tk.Button(bar, text="⏸", command=self._toggle_pause,
                                   bg=CARD, fg=FG, relief="flat", width=3)
        self.pause_btn.pack(side="right", padx=1)
        self.info = tk.Label(bar, text="…", bg=PANEL, fg=CYAN, font=("Segoe UI", 8))
        self.info.pack(side="left", padx=6)

        kb = tk.Frame(self, bg=BG)
        kb.pack(fill="x", pady=(2, 0))
        self.text_var = tk.StringVar()
        ent = ttk.Entry(kb, textvariable=self.text_var)
        ent.pack(side="right", fill="x", expand=True, padx=(4, 2), pady=2)
        ent.bind("<Return>", lambda ev: self._send_text())
        tk.Button(kb, text="إرسال", command=self._send_text, bg=CARD, fg=FG,
                  relief="flat").pack(side="right", padx=2)

        self.canvas = tk.Label(self, bg="#000000", cursor="hand2")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", self._click)
        self.canvas.bind("<B1-Motion>", self._drag_move)
        self.canvas.bind("<ButtonRelease-1>", self._drag_end)
        self.canvas.bind("<Button-3>", lambda e: self._key(4))

        self.msg = tk.Label(self, text="جارٍ الاتصال…", bg=BG, fg=MUTED, anchor="w")
        self.msg.pack(fill="x", padx=6, pady=2)

        self.protocol("WM_DELETE_WINDOW", self.close)
        threading.Thread(target=self._boot, daemon=True).start()

    # ── اتصال وتهيئة ──
    def _boot(self):
        try:
            self.client = self.app._connect_ssh(self.row)
        except Exception as e:
            self.after(0, lambda: self.msg.configure(text=f"فشل SSH: {e}"))
            return
        # جلسة أوامر دائمة => لمس/كتابة فورية
        try:
            self.in_chan = self.client.get_transport().open_session()
            self.in_chan.exec_command(f"{RADB} -s emulator-5554 shell")
            threading.Thread(target=self._drain, args=(self.in_chan,), daemon=True).start()
        except Exception:
            self.in_chan = None
        # تسريع فوري للجهاز
        self._sh(f"{RADB} -s emulator-5554 shell 'settings put global window_animation_scale 0; "
                 "settings put global transition_animation_scale 0; "
                 "settings put global animator_duration_scale 0; "
                 "input keyevent KEYCODE_WAKEUP; wm dismiss-keyguard'", timeout=25)
        # تسريع الجهاز + دقة أخف (540x960) => إطارات أسرع وسلاسة أعلى
        self._sh(f"{RADB} -s emulator-5554 shell 'cmd power set-fixed-performance-mode-enabled true "
                 "2>/dev/null; wm size 540x960; wm density 240; svc power stayon true; am kill-all'",
                 timeout=30)
        self.hi_res = False
        self.after(0, lambda: self.msg.configure(text="متصل — بدء البث"))

        # عرض سريع عبر صور متتابعة (البث h264 غير موثوق على هذه الصور)
        if self.running:
            self._snapshot_loop()

    def _sh(self, cmd, timeout=20):
        try:
            _, so, se = self.client.exec_command(cmd, timeout=timeout)
            return (so.read() + se.read()).decode("utf-8", "replace")
        except Exception as e:
            return f"ERR {e}"

    def _drain(self, chan):
        try:
            while self.running:
                if not chan.recv(8192):
                    break
        except Exception:
            pass

    def _send(self, cmd):
        """يرسل أمرًا إلى جلسة adb shell الدائمة (سريع جدًا)."""
        try:
            if self.in_chan and not self.in_chan.closed:
                self.in_chan.sendall((cmd + "\n").encode())
                return
        except Exception:
            pass
        threading.Thread(
            target=lambda: self._sh(f"{RADB} -s emulator-5554 shell {cmd}", timeout=15),
            daemon=True).start()

    # ── أوامر الجهاز ──
    def _key(self, code):
        self._send(f"input keyevent {code}")

    def _send_text(self):
        txt = self.text_var.get()
        if not txt:
            return
        safe = txt.replace(" ", "%s").replace("'", "").replace('"', "")
        self._send(f"input text '{safe}'")
        self.text_var.set("")

    def _boost_perf(self):
        cmd = ("settings put global window_animation_scale 0; "
               "settings put global transition_animation_scale 0; "
               "settings put global animator_duration_scale 0; "
               "settings put global wifi_scan_always_enabled 0; "
               "cmd power set-fixed-performance-mode-enabled true 2>/dev/null; "
               "am kill-all")
        threading.Thread(
            target=lambda: (self._sh(f"{RADB} -s emulator-5554 shell '{cmd}'", timeout=30),
                            self.after(0, lambda: self.msg.configure(text="وضع الأداء الأقصى ✓"))),
            daemon=True).start()

    def _toggle_res(self):
        self.hi_res = not self.hi_res
        if self.hi_res:
            cmd = "wm size reset; wm density reset"
            text = "الدقة الأصلية (أوضح)"
        else:
            cmd = "wm size 540x960; wm density 240"
            text = "دقة أداء 540x960 (أسرع)"
        threading.Thread(
            target=lambda: (self._sh(f"{RADB} -s emulator-5554 shell '{cmd}'", timeout=20),
                            self.after(0, lambda: self.msg.configure(text=text))),
            daemon=True).start()

    def _smart_paste(self):
        """يقرأ حافظة الحاسوب: رابطًا يفتحه في كروم، وغير ذلك يكتبه في الحقل."""
        try:
            text = self.clipboard_get()
        except Exception:
            text = ""
        if not text.strip():
            self.msg.configure(text="حافظة الحاسوب فارغة")
            return
        url = self.app._as_url(text)
        if url:
            threading.Thread(
                target=lambda: (self._sh(f"IDX=0 ~/bin/ctl.sh open-url {shlex.quote(url)}", timeout=20),
                                self.after(0, lambda: self.msg.configure(text="فُتح الرابط في كروم"))),
                daemon=True).start()
            return
        b64 = base64.b64encode(text.encode("utf-8")).decode()
        threading.Thread(
            target=lambda: (self._sh(f"IDX=0 ~/bin/ctl.sh paste-b64 {b64}", timeout=20),
                            self.after(0, lambda: self.msg.configure(text="كُتب النص في الحقل"))),
            daemon=True).start()

    def _toggle_pause(self):
        self.paused = not self.paused
        self.pause_btn.configure(text="▶" if self.paused else "⏸")

    # ── لمس ──
    def _dev_xy(self, x, y):
        w = max(self.canvas.winfo_width(), 1)
        h = max(self.canvas.winfo_height(), 1)
        return int(x * self.dev_w / w), int(y * self.dev_h / h)

    def _click(self, ev):
        if not self.dev_w:
            return
        self._drag = (ev.x, ev.y, ev.x, ev.y)
        dx, dy = self._dev_xy(ev.x, ev.y)
        self._send(f"input tap {dx} {dy}")

    def _drag_move(self, ev):
        if self._drag:
            self._drag = (self._drag[0], self._drag[1], ev.x, ev.y)

    def _drag_end(self, ev):
        if not self._drag or not self.dev_w:
            self._drag = None
            return
        x1, y1, _, _ = self._drag
        if abs(ev.x - x1) > 6 or abs(ev.y - y1) > 6:
            a = self._dev_xy(x1, y1)
            b = self._dev_xy(ev.x, ev.y)
            self._send(f"input swipe {a[0]} {a[1]} {b[0]} {b[1]} 180")
        self._drag = None

    # ── عرض ──
    def _show(self, data):
        try:
            img = Image.open(io.BytesIO(data))
        except Exception:
            return
        self.dev_w, self.dev_h = img.size
        w = min(520, img.size[0] * 2)
        h = max(1, int(img.size[1] * w / img.size[0]))
        img = img.resize((w, h), Image.BILINEAR)
        ph = ImageTk.PhotoImage(img)
        self.canvas.configure(image=ph)
        self.canvas.image = ph
        self.frames += 1
        now = time.time()
        if now - self.t_fps >= 1.0:
            self.fps = self.frames / (now - self.t_fps)
            self.frames = 0
            self.t_fps = now
            chan = "فوري" if (self.in_chan and not self.in_chan.closed) else "عادي"
            self.info.configure(text=f"{self.fps:.1f} fps · إدخال {chan}")

    def _stream_loop(self):
        """يقرأ تدفّق MJPEG من المضيف ويعرض الإطارات فور وصولها."""
        buf = bytearray()
        got_any = False
        t_start = time.time()
        while self.running:
            try:
                chan = self.client.get_transport().open_session()
                chan.exec_command("IDX=0 ~/bin/ctl.sh stream")
                self.after(0, lambda: self.msg.configure(text="بث مباشر (MJPEG)"))
                while self.running:
                    data = chan.recv(65536)
                    if not data:
                        break
                    buf.extend(data)
                    while True:
                        s = buf.find(b"\xff\xd8")
                        if s < 0:
                            if len(buf) > 16:
                                del buf[:-4]
                            break
                        e = buf.find(b"\xff\xd9", s + 2)
                        if e < 0:
                            if len(buf) > 3_000_000:
                                buf.clear()
                            break
                        frame = bytes(buf[s:e + 2])
                        del buf[:e + 2]
                        got_any = True
                        self.after(0, lambda f=frame: self._show(f))
                try:
                    chan.close()
                except Exception:
                    pass
            except Exception:
                time.sleep(0.5)
            if not got_any and (time.time() - t_start) > 8:
                return  # البث لا يعمل ⇒ الوضع البديل
            if self.running:
                time.sleep(0.1)

    def _snapshot_loop(self):
        while self.running:
            if self.paused:
                time.sleep(0.3)
                continue
            t0 = time.time()
            try:
                chan = self.client.get_transport().open_session()
                chan.exec_command(f"{RADB} -s emulator-5554 exec-out screencap -p")
                chunks = []
                while True:
                    d = chan.recv(65536)
                    if not d:
                        break
                    chunks.append(d)
                chan.close()
                data = b"".join(chunks)
                if data[:8] == b"\x89PNG\r\n\x1a\n":
                    self.after(0, lambda d=data: self._show(d))
                else:
                    self.after(0, lambda: self.msg.configure(
                        text="تعذّر جلب الشاشة (قد يكون المحاكي يُقلع)"))
            except Exception as e:
                if self.running:
                    self.after(0, lambda e=e: self.msg.configure(text=f"خطأ: {e}"))
                time.sleep(0.6)
            dt = time.time() - t0
            time.sleep(max(0.05, 0.20 - dt))

    def close(self):
        self.running = False
        # أعِد دقة الجهاز قبل إغلاق الاتصال (كانت تُفقد لأن الاتصال يُغلق أولًا)
        try:
            if self.client:
                self._sh(f"{RADB} -s emulator-5554 shell 'wm size reset; wm density reset'", timeout=12)
        except Exception:
            pass
        try:
            if self.in_chan:
                self.in_chan.close()
        except Exception:
            pass
        try:
            if self.client:
                self.client.close()
        except Exception:
            pass
        self.destroy()
# ─────────────────────────── التطبيق ───────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Server Manager — GitHub Android / RDP")
        self.geometry("1300x900+6+2")
        self.minsize(1120, 780)
        self.configure(bg=BG)
        self.store = load_store()
        self.store.setdefault("servers", {})
        self.rows = {}
        self.selected = None
        self.busy = False
        self._scrcpy = {}
        self._key_ok = {}
        self.auto = tk.BooleanVar(value=True)
        self._style()
        self._build()
        self._update_actions()
        self.after(200, self.refresh)
        self.after(REFRESH_SEC * 1000, self._tick)

    # ── ستايل ──
    def _style(self):
        s = ttk.Style(self)
        try:
            s.theme_use("clam")
        except Exception:
            pass
        s.configure(".", background=BG, foreground=FG, font=("Segoe UI", 9))
        s.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=FG,
                    rowheight=30, borderwidth=0)
        s.configure("Treeview.Heading", background="#2f3242", foreground="#ffffff",
                    relief="flat", font=("Segoe UI", 9, "bold"))
        s.map("Treeview", background=[("selected", ACCENT)],
              foreground=[("selected", "#ffffff")])
        s.configure("TButton", padding=6)
        s.configure("TLabel", background=BG, foreground=FG)
        s.configure("Muted.TLabel", background=BG, foreground=MUTED)
        s.configure("TFrame", background=BG)
        s.configure("Card.TFrame", background=PANEL)
        s.configure("TEntry", fieldbackground="#2a2d3a", foreground=FG)
        s.configure("TCombobox", fieldbackground="#2a2d3a", background="#2a2d3a",
                    foreground=FG, arrowcolor=FG, selectbackground="#2a2d3a",
                    selectforeground=FG)
        s.map("TCombobox",
              fieldbackground=[("readonly", "#2a2d3a"), ("disabled", PANEL)],
              foreground=[("readonly", FG), ("disabled", MUTED)],
              background=[("readonly", "#2a2d3a")])
        s.configure("Accent.TButton", background=ACCENT, foreground="#ffffff")
        s.map("Accent.TButton", background=[("active", "#4c6ef5")])
        s.configure("Danger.TButton", background="#7a2530", foreground="#ffffff")
        s.map("Danger.TButton", background=[("active", "#a03040")])
        s.configure("TLabelframe", background=BG, foreground=MUTED, bordercolor="#2f3242")
        s.configure("TLabelframe.Label", background=BG, foreground=MUTED)

    # ── بناء الواجهة ──
    def _build(self):
        top = ttk.Frame(self, padding=(12, 10, 12, 4))
        top.pack(fill="x")

        ttk.Button(top, text="+ سيرفر جديد", style="Accent.TButton",
                   command=self.create_server).pack(side="right", padx=(8, 0))
        ttk.Button(top, text="⟳ تحديث", command=self.refresh).pack(side="right", padx=4)
        ttk.Checkbutton(top, text="تلقائي", variable=self.auto,
                        command=self._tick).pack(side="right", padx=8)
        ttk.Button(top, text="☁ Actions", command=self.open_actions).pack(side="right", padx=4)

        self.pill = tk.Label(top, text="جاهز", bg=PANEL, fg=MUTED, padx=10, pady=4,
                             font=("Segoe UI", 9, "bold"))
        self.pill.pack(side="left")

        # جدول السيرفرات
        mid = ttk.Frame(self, padding=(12, 4))
        mid.pack(fill="both", expand=True)

        cols = ("slot", "ip", "state", "pw", "mode", "android", "mac", "imei", "rem", "apps", "run")
        heads = ("Slot", "IP", "الحالة", "كلمة السر", "الوضع", "أندرويد", "MAC", "IMEI", "المتبقي", "تطبيقات", "Run")
        widths = (46, 128, 92, 150, 62, 70, 130, 138, 78, 60, 96)
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", height=5)
        for c, h, w in zip(cols, heads, widths):
            self.tree.heading(c, text=h)
            self.tree.column(c, width=w, anchor="center", stretch=(c == "ip"))
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.tree.bind("<Double-1>", lambda e: self.show_details())
        self.tree.tag_configure("online", foreground=GREEN)
        self.tree.tag_configure("offline", foreground=RED)
        self.tree.tag_configure("pending", foreground=ORANGE)

        # أزرار التحكم
        act = ttk.LabelFrame(self, text=" تحكم بالسيرفر المحدد ", padding=8)
        act.pack(fill="x", padx=12, pady=(8, 2))
        r1 = ttk.Frame(act)
        r1.pack(fill="x", pady=2)
        self.btn = {}
        for key, txt, fn in (
            ("rdp", "🖥 RDP", self.open_rdp),
            ("scrcpy", "📱 scrcpy", self.open_scrcpy),
            ("ssh", "⌨ SSH", self.open_ssh),
            ("stats", "📊 الأداء", self.show_stats),
            ("shot", "📸 صورة", self.screenshot),
            ("apk", "📦 تثبيت APK", self.install_apk),
            ("play", "🛍 Play", lambda: self.ctl("play")),
            ("chrome", "🌐 كروم", lambda: self.ctl("chrome")),
            ("root", "🔓 روت", self.act_root),
            ("nav", "◀ أزرار", lambda: self.ctl("nav")),
            ("reboot", "⏼ إعادة تشغيل", self.act_reboot),
        ):
            b = ttk.Button(r1, text=txt, command=fn)
            b.pack(side="right", padx=3)
            self.btn[key] = b

        r2 = ttk.Frame(act)
        r2.pack(fill="x", pady=2)
        for key, txt, fn, style in (
            ("stop", "⏹ إيقاف السيرفر", self.stop_server, "Danger.TButton"),
            ("delete", "⏻ حذف", self.delete_server, None),
            ("copy", "📋 نسخ البيانات", self.copy_row, None),
            ("pwset", "🔑 تعيين كلمة السر", self.set_password, None),
            ("mirror", "🪞 مِرآة الجهاز", self.open_mirror, None),
            ("sshkey", "🧬 مفتاح SSH", self.install_ssh_key, None),
            ("clip", "📋 الحافظة", self.open_clipboard_dialog, None),
        ):
            b = ttk.Button(r2, text=txt, command=fn, style=style) if style else ttk.Button(r2, text=txt, command=fn)
            b.pack(side="right", padx=3)
            self.btn[key] = b
        self.sel_lbl = ttk.Label(r2, text="لم يتم اختيار سيرفر", style="Muted.TLabel")
        self.sel_lbl.pack(side="left", padx=6)

        # تغيير من الخارج
        chg = ttk.LabelFrame(self, text=" تغيير من الخارج ", padding=8)
        chg.pack(fill="x", padx=12, pady=4)

        g = ttk.Frame(chg)
        g.pack(fill="x", pady=2)
        ttk.Label(g, text="الموقع (GPS):").pack(side="right", padx=(0, 4))
        self.lat = tk.StringVar()
        self.lon = tk.StringVar()
        ttk.Entry(g, textvariable=self.lon, width=10).pack(side="right", padx=2)
        ttk.Label(g, text="lon").pack(side="right")
        ttk.Entry(g, textvariable=self.lat, width=10).pack(side="right", padx=2)
        ttk.Label(g, text="lat").pack(side="right")
        self.btn["geo"] = ttk.Button(g, text="تطبيق الموقع", command=self.set_geo)
        self.btn["geo"].pack(side="right", padx=6)
        ttk.Button(g, text="إيقاف GPS", command=lambda: self.ctl("geo-off")).pack(side="right", padx=2)

        m = ttk.Frame(chg)
        m.pack(fill="x", pady=2)
        self.mac = tk.StringVar()
        self.imei = tk.StringVar()
        self.aid = tk.StringVar()
        self.proxy = tk.StringVar()
        ttk.Label(m, text="MAC:").pack(side="right", padx=(12, 3))
        self.mac_entry = ttk.Entry(m, textvariable=self.mac, width=19)
        self.mac_entry.pack(side="right", padx=2)
        self.btn["mac_gen"] = ttk.Button(m, text="⚡ توليد + تطبيق", command=self.auto_mac)
        self.btn["mac_gen"].pack(side="right", padx=2)
        self.btn["mac_apply"] = ttk.Button(m, text="تطبيق MAC", command=self.set_mac)
        self.btn["mac_apply"].pack(side="right", padx=2)

        ttk.Label(m, text="IMEI:").pack(side="right", padx=(12, 3))
        self.imei_entry = ttk.Entry(m, textvariable=self.imei, width=18)
        self.imei_entry.pack(side="right", padx=2)
        self.btn["imei_gen"] = ttk.Button(m, text="⚡ توليد + تطبيق", command=self.auto_imei)
        self.btn["imei_gen"].pack(side="right", padx=2)
        self.btn["imei_apply"] = ttk.Button(m, text="تطبيق IMEI", command=self.set_imei)
        self.btn["imei_apply"].pack(side="right", padx=2)

        p = ttk.Frame(chg)
        p.pack(fill="x", pady=2)
        ttk.Label(p, text="Android ID:").pack(side="right", padx=(0, 3))
        self.aid_entry = ttk.Entry(p, textvariable=self.aid, width=19)
        self.aid_entry.pack(side="right", padx=2)
        self.btn["aid_gen"] = ttk.Button(p, text="⚡ توليد + تطبيق", command=self.auto_aid)
        self.btn["aid_gen"].pack(side="right", padx=2)
        self.btn["aid_apply"] = ttk.Button(p, text="تطبيق Android ID", command=self.set_aid)
        self.btn["aid_apply"].pack(side="right", padx=2)
        ttk.Label(p, text="بروكسي:").pack(side="right", padx=(16, 3))
        self.proxy_entry = ttk.Entry(p, textvariable=self.proxy, width=18)
        self.proxy_entry.pack(side="right", padx=2)
        self.btn["proxy_on"] = ttk.Button(p, text="تطبيق", command=lambda: self.set_proxy(False))
        self.btn["proxy_on"].pack(side="right", padx=2)
        self.btn["proxy_off"] = ttk.Button(p, text="إلغاء", command=lambda: self.set_proxy(True))
        self.btn["proxy_off"].pack(side="right", padx=2)

        # السجل
        logf = ttk.LabelFrame(self, text=" السجل ", padding=(6, 2, 6, 4))
        logf.pack(side="bottom", fill="x", padx=12, pady=(2, 8))
        self.logbox = tk.Text(logf, height=5, bg="#0e0f14", fg="#8fe6a8", relief="flat",
                              insertbackground="#8fe6a8", font=("Consolas", 9), wrap="word")
        self.logbox.pack(fill="both", expand=True)
        self.logbox.configure(state="disabled")

        # ترتيب الحزم من الأسفل للأعلى حتى لا يُقص السجل في النوافذ الصغيرة
        for w in (logf, chg, act, mid):
            w.pack_forget()
        logf.pack(side="bottom", fill="x", padx=12, pady=(2, 8))
        chg.pack(side="bottom", fill="x", padx=12, pady=4)
        act.pack(side="bottom", fill="x", padx=12, pady=(8, 2))
        mid.pack(fill="both", expand=True, pady=(0, 2))

        self.bind("<F5>", lambda e: self.refresh())
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    # ── سجل ومساعدة ──
    def log(self, msg):
        self.logbox.configure(state="normal")
        self.logbox.insert("end", f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        self.logbox.see("end")
        self.logbox.configure(state="disabled")

    def set_pill(self, text, color=MUTED):
        try:
            self.pill.configure(text=text, fg=color)
        except Exception:
            pass

    def _bg(self, fn):
        threading.Thread(target=fn, daemon=True).start()

    def require_sel(self):
        if not self.selected:
            messagebox.showinfo("تنبيه", "اختر سيرفرًا من الجدول أولًا")
            return False
        return True

    def password_of(self, row):
        if not row:
            return ""
        run = row.get("run") or ""
        info = self.store["servers"].get(run) if run else None
        if info and info.get("password"):
            return info["password"]
        pend = self.store["servers"].get(f"pending:{row.get('slot')}")
        if pend and time.time() - pend.get("ts", 0) < 1800:
            return pend.get("password", "")
        return ""

    # ── اختيار وخصائص ──
    def on_select(self, _evt=None):
        sel = self.tree.selection()
        self.selected = self.rows.get(sel[0]) if sel else None
        if self.selected:
            self.mac.set(self.selected.get("mac") or "")
            self.imei.set(self.selected.get("imei") or "")
            self.aid.set(self.selected.get("aid") or "")
            slot = self.selected.get("slot")
            mode = self.selected.get("mode", "play")
            self.sel_lbl.configure(
                text=f"slot {slot} · {mode} · {self.selected.get('ip') or 'بدون IP'} · "
                     f"{'متصل' if self.selected.get('online') else 'غير متصل'}")
        else:
            self.sel_lbl.configure(text="لم يتم اختيار سيرفر")
        self._update_actions()

    def _update_actions(self):
        r = self.selected
        online = bool(r and r.get("online"))
        has_run = bool(r and r.get("run"))
        can_root = bool(r and r.get("root") == "1")
        has_desk = bool(r and r.get("desktop") == "true")
        has_ip = bool(r and r.get("ip"))
        has_pw = bool(r and self.password_of(r))
        has_auth = (has_pw or bool(r and r.get("sshkey") == "1")
                    or bool(r and self._key_ok.get(r.get("ip"))))

        for k in ("scrcpy", "stats", "shot", "apk", "play", "chrome", "nav",
                  "reboot", "stop", "copy", "geo", "proxy_on", "proxy_off", "aid_gen",
                  "aid_apply", "imei_gen", "imei_apply", "mac_gen", "mac_apply", "root"):
            if k in self.btn:
                self.btn[k].state(["!disabled"] if online else ["disabled"])

        def setstate(k, ok):
            if k in self.btn:
                self.btn[k].state(["!disabled"] if ok else ["disabled"])

        setstate("rdp", online and has_desk)
        setstate("ssh", online and has_auth and has_ip)
        setstate("root", online and can_root)
        setstate("mac_gen", online and can_root and has_auth)
        setstate("mac_apply", online and can_root and has_auth)
        setstate("imei_gen", online and has_auth and has_ip)
        setstate("imei_apply", online and has_auth and has_ip)
        setstate("delete", has_run)
        setstate("stop", online and has_run)
        setstate("copy", bool(r))
        setstate("pwset", bool(r))
        # كل ما يمر عبر SSH يحتاج مصادقة (مفتاح SSH أو كلمة سر)
        for k in ("stats", "shot", "apk", "geo", "aid_gen", "aid_apply",
                  "proxy_on", "proxy_off", "play", "clip"):
            setstate(k, online and has_ip and has_auth)
        for k in ("scrcpy", "nav", "reboot", "chrome"):
            setstate(k, online and has_ip)
        setstate("mirror", online and has_ip)
        setstate("sshkey", online and has_ip)
        self.mac_entry.configure(state="normal" if can_root else "disabled")
        if not can_root:
            self.mac.set("متاح في وضع root فقط")

    # ── جلب البيانات ──
    def _tick(self):
        if self.auto.get():
            self.refresh()
        self.after(REFRESH_SEC * 1000, self._tick)

    def refresh(self):
        if self.busy:
            return
        self.busy = True
        self.set_pill("جارٍ التحديث…", ORANGE)
        self._bg(self._refresh_worker)

    def _refresh_worker(self):
        try:
            peers = self._tailscale_peers()
            status = self._status_files()
            rows = {}

            for slot, info in status.items():
                ip = info.get("IP", "")
                run = info.get("RUN", "")
                state = info.get("STATE", "ready")
                peer = None
                for p in peers:
                    if (ip and p["ip"] == ip) or (run and run in p["name"]):
                        peer = p
                        break
                online = bool(peer and peer["online"])
                key = ip or f"pending-{run or slot}"
                rows[key] = {
                    "slot": slot, "ip": ip, "online": online, "state": state,
                    "run": run, "start": info.get("START", ""),
                    "mode": info.get("MODE", "?"), "root": info.get("ROOT", "0"),
                    "desktop": info.get("DESKTOP", "false"),
                    "android": info.get("ANDROID", "30"),
                    "mac": info.get("MAC", ""), "imei": info.get("IMEI", ""),
                    "aid": info.get("AID", ""), "apps": info.get("APPS", ""),
                    "cores": info.get("CORES", ""), "mem": info.get("MEM", ""),
                    "ports": info.get("PORTS", ""),
                    "adb_server": info.get("ADB_SERVER", "15037"),
                    "sshkey": info.get("SSH_KEY", "0"),
                }

            # عقد Tailscale بلا ملف حالة
            for p in peers:
                if any(r["ip"] == p["ip"] for r in rows.values()):
                    continue
                if not p["online"]:
                    continue
                m = re.search(r"gh-android-(\d+)", p["name"])
                rows[p["ip"]] = {
                    "slot": 0, "ip": p["ip"], "online": True, "state": "ready",
                    "run": m.group(1) if m else "", "start": "", "mode": "?",
                    "root": "0", "desktop": "false", "android": "?", "mac": "",
                    "imei": "", "aid": "", "apps": "", "cores": "", "mem": "", "ports": "",
                }

            # قراءة MAC/AndroidID الحقيقية من السيرفر المحدد فقط (توفيرًا للوقت)
            sel_ip = self.selected.get("ip") if self.selected else None
            for r in rows.values():
                if sel_ip and r["ip"] == sel_ip and r["online"]:
                    try:
                        mac, aid, serial = self._adb_probe(r)
                        if mac:
                            r["mac"] = mac
                        if aid:
                            r["aid"] = aid
                        if serial:
                            r["serial"] = serial
                    except Exception:
                        pass

            self.after(0, lambda: self._render(rows))
        finally:
            self.busy = False
            self.after(0, lambda: self.set_pill(
                f"آخر تحديث {time.strftime('%H:%M:%S')}", MUTED))

    def _tailscale_peers(self):
        raw = sh([TS, "status", "--json"], timeout=15)
        if raw.startswith("__ERR__"):
            return []
        try:
            data = json.loads(raw)
        except Exception:
            return []
        out = []
        for _, v in (data.get("Peer") or {}).items():
            name = v.get("HostName") or ""
            if not name.startswith("gh-android-"):
                continue
            ips = v.get("TailscaleIPs") or []
            out.append({"name": name, "ip": ips[0] if ips else "",
                        "online": bool(v.get("Online"))})
        return out

    def _status_files(self):
        out = {}
        listing = sh([GH, "api", f"repos/{REPO}/contents", "--jq", ".[].name"], timeout=25)
        if listing.startswith("__ERR__"):
            self.after(0, lambda: self.log("تعذّر قراءة ملفات الحالة: " + listing[:120]))
            return out
        import base64
        for name in (n.strip() for n in listing.splitlines()):
            if not re.fullmatch(r"status-\d+\.txt", name):
                continue
            raw = sh([GH, "api", f"repos/{REPO}/contents/{name}", "--jq", ".content"], timeout=20)
            if raw.startswith("__ERR__"):
                continue
            try:
                txt = base64.b64decode(re.sub(r"\s", "", raw)).decode("utf-8", "replace").strip()
            except Exception:
                continue
            if "SLOT=" not in txt:
                continue
            info = parse_row(txt)
            try:
                slot = int(info.get("SLOT") or name.split("-")[1].split(".")[0])
            except Exception:
                continue
            out[slot] = info
        return out

    def _adb_probe(self, row):
        """يقرأ MAC / Android ID / serial من داخل الأندرويد عبر SSH + adb المضيف
        (المضيف مصرّح مسبقًا، فتتجاوز مصادقة adbd في صور Play)."""
        out = self._ssh("IDX=0 ~/bin/ctl.sh probe", timeout=30, row=row)
        mac = aid = serial = ""
        for line in (out or "").splitlines():
            if line.startswith("mac="):
                mac = line[4:].strip().upper()
            elif line.startswith("aid="):
                aid = line[4:].strip()
            elif line.startswith("serial="):
                serial = line[6:].strip()
        return mac, aid, serial

    def _render(self, rows):
        sel_key = None
        if self.selected:
            sel_key = self.selected.get("ip") or f"pending-{self.selected.get('run')}"
        self.tree.delete(*self.tree.get_children())
        self.rows.clear()
        order = {"starting": 0, "booting": 1, "ready": 2}
        online_n = 0
        for r in sorted(rows.values(), key=lambda x: (int(x["slot"] or 99), order.get(x["state"], 3))):
            if r["online"]:
                online_n += 1
            if r["state"] == "starting":
                state, tag = "قيد الإنشاء", "pending"
            elif r["state"] == "booting":
                state, tag = "قيد التجهيز", "pending"
            elif r["online"]:
                state, tag = "متصل", "online"
            else:
                state, tag = "متوقف", "offline"
            pw = self.password_of(r) or "—"
            mode = {"play": "Play", "root": "Root"}.get(r["mode"], "—")
            iid = self.tree.insert("", "end", values=(
                r["slot"] or "-", r["ip"] or "—", state, pw, mode,
                r["android"] if r["android"] != "?" else "—",
                (r["mac"] or "—") if r["root"] == "1" or r["mac"] else "—",
                r["imei"] or "—",
                (fmt_remaining(r["start"]) or "—") if r["online"] else "—",
                r["apps"] or "—", r["run"] or "—",
            ), tags=(tag,))
            self.rows[iid] = r
            key = r["ip"] or f"pending-{r['run']}"
            if sel_key and key == sel_key:
                self.tree.selection_set(iid)
        self.set_pill(f"{len(rows)} سيرفر · {online_n} متصل", GREEN if online_n else MUTED)
        self._update_actions()
        if not rows:
            self.log("لا توجد سيرفرات. اضغط «+ سيرفر جديد» لإنشاء واحد.")

    # ── شل عبر SSH ──
    # ── اتصال SSH (مفتاح أولًا ثم كلمة السر) ──
    def _connect_ssh(self, row, timeout=15):
        """يفتح اتصال SSH: مفتاح التطبيق أولًا، ثم كلمة السر المحفوظة."""
        if not HAS_SSH:
            raise RuntimeError("paramiko غير متاح")
        ip = row.get("ip")
        if not ip:
            raise RuntimeError("لا يوجد IP")
        errors = []
        key, _pub = ensure_ssh_key()
        if key is not None:
            try:
                c = paramiko.SSHClient()
                c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                c.connect(ip, port=22, username=RDP_USER, pkey=key, timeout=timeout,
                          allow_agent=False, look_for_keys=False,
                          banner_timeout=timeout, auth_timeout=timeout)
                self._key_ok[ip] = True
                return c
            except Exception as e:
                self._key_ok[ip] = False
                errors.append(f"key: {type(e).__name__}: {e}")
        pw = self.password_of(row)
        if pw:
            try:
                c = paramiko.SSHClient()
                c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                c.connect(ip, port=22, username=RDP_USER, password=pw, timeout=timeout,
                          allow_agent=False, look_for_keys=False,
                          banner_timeout=timeout, auth_timeout=timeout)
                return c
            except Exception as e:
                errors.append(f"pass: {type(e).__name__}: {e}")
        raise RuntimeError(" | ".join(errors) or "لا مفتاح ولا كلمة سر")

    def _ssh(self, command, timeout=45, row=None):
        row = row or self.selected
        if not row:
            return "__ERR__ لا يوجد سيرفر محدد"
        try:
            c = self._connect_ssh(row)
        except Exception as e:
            return f"__ERR__ {e}"
        try:
            _, so, se = c.exec_command(command, timeout=timeout)
            out = so.read().decode("utf-8", "replace") + se.read().decode("utf-8", "replace")
            return out.strip()
        except Exception as e:
            return f"__ERR__ {type(e).__name__}: {e}"
        finally:
            try:
                c.close()
            except Exception:
                pass

    def ctl(self, args):
        """ينفّذ ctl.sh على السيرفر المحدد."""
        if not self.require_sel():
            return
        if not self.selected.get("online"):
            messagebox.showinfo("تنبيه", "السيرفر غير متصل حاليًا")
            return

        def work():
            self.after(0, lambda: self.set_pill("جارٍ التنفيذ…", ORANGE))
            out = self._ssh(f"IDX=0 ~/bin/ctl.sh {args}")
            if out.startswith("__ERR__"):
                self.after(0, lambda: self.log(f"ctl {args} → {out[:400]}"))
                self.after(0, lambda: messagebox.showerror(
                    "تعذّر تنفيذ الأمر",
                    f"{out}\n\nجرّب زر «🧬 مفتاح SSH» لتثبيت مفتاح التحكم،\n"
                    "أو «🔑 تعيين كلمة السر» إن لم تكن محفوظة."))
            else:
                self.after(0, lambda: self.log(f"ctl {args} → {out[:400]}"))
                self.after(0, lambda: self.set_pill("تم", GREEN))
            if args.startswith(("imei", "reboot", "mac", "aid")):
                time.sleep(2)
                self.refresh()

        self._bg(work)

    # ── إجراءات ──
    def open_actions(self):
        webbrowser.open(f"https://github.com/{REPO}/actions")

    def create_server(self):
        slots_used = {r["slot"] for r in self.rows.values() if r.get("slot")}
        dlg = CreateDialog(self, slots_used)
        self.wait_window(dlg)
        if not dlg.result:
            return
        data = dlg.result
        # خزّن السر مؤقتًا حسب slot (يُربط بالـ run بعد الإرسال)
        self.store["servers"][f"pending:{data['slot']}"] = {
            "password": data["password"], "ts": time.time()}
        save_store(self.store)

        def work():
            _k, pub = ensure_ssh_key()
            cmd = [GH, "workflow", "run", WORKFLOW, "--repo", REPO,
                   "-f", f"slot={data['slot']}", "-f", f"instances={data['instances']}",
                   "-f", f"mode={data['mode']}", "-f", f"desktop={data['desktop']}",
                   "-f", f"password={data['password']}", "-f", f"imei={data['imei']}"]
            if pub:
                cmd += ["-f", f"ssh_pubkey={pub}"]
            out = sh(cmd, timeout=90)
            ok = not out.startswith("__ERR__") and "error" not in out.lower()
            self.after(0, lambda: self.log(
                f"إنشاء slot {data['slot']} ({data['mode']}): {'تم الإرسال ✓' if ok else out[:300]}"))
            if ok:
                self.after(0, lambda: self.log(
                    f"كلمة سر السيرفر: {data['password']}  ·  IMEI: {data['imei']}"))
                # اربط كلمة السر بأحدث run
                for _ in range(12):
                    time.sleep(2)
                    raw = sh([GH, "run", "list", "--repo", REPO, "--workflow", WORKFLOW,
                              "--limit", "1", "--json", "databaseId"], timeout=25)
                    try:
                        rid = str(json.loads(raw)[0]["databaseId"])
                    except Exception:
                        continue
                    self.store["servers"][rid] = {
                        "password": data["password"], "imei": data["imei"],
                        "slot": data["slot"], "mode": data["mode"], "ts": time.time()}
                    self.store["servers"].pop(f"pending:{data['slot']}", None)
                    save_store(self.store)
                    self.after(0, lambda rid=rid: self.log(f"رُبطت كلمة السر بالتشغيل {rid}"))
                    break
            time.sleep(3)
            self.refresh()

        self._bg(work)

    def stop_server(self):
        if not self.require_sel() or not self.selected.get("run"):
            return
        r = self.selected
        if not messagebox.askyesno("تأكيد الإيقاف",
                                   f"إيقاف السيرفر slot {r['slot']}؟\n"
                                   "سيُلغى التشغيل وتُدمَّر الآلة فورًا."):
            return

        def work():
            out = sh([GH, "run", "cancel", r["run"], "--repo", REPO], timeout=60)
            self.after(0, lambda: self.log(f"إيقاف run {r['run']}: {out or 'تم ✓'}"))
            time.sleep(4)
            self.refresh()

        self._bg(work)

    def delete_server(self):
        if not self.require_sel() or not self.selected.get("run"):
            return
        r = self.selected
        if not messagebox.askyesno("تأكيد الحذف",
                                   f"حذف السيرفر slot {r['slot']} نهائيًا؟\n"
                                   "إلغاء التشغيل + حذف ملف الحالة + حذف كلمة السر المحلية."):
            return

        def work():
            sh([GH, "run", "cancel", r["run"], "--repo", REPO], timeout=60)
            f = f"status-{r['slot']}.txt"
            sha = sh([GH, "api", f"repos/{REPO}/contents/{f}", "--jq", ".sha"], timeout=25)
            if sha and not sha.startswith("__ERR__"):
                sh([GH, "api", "-X", "DELETE", f"repos/{REPO}/contents/{f}",
                    "-f", "message=server deleted", "-f", f"sha={sha}"], timeout=25)
            self.store["servers"].pop(str(r["run"]), None)
            self.store["servers"].pop(f"pending:{r['slot']}", None)
            save_store(self.store)
            self.after(0, lambda: self.log(f"حُذف slot {r['slot']} (run {r['run']}) ✓"))
            self.after(0, self.refresh)

        self._bg(work)

    def open_rdp(self):
        if not self.require_sel():
            return
        ip = self.selected.get("ip")
        if not ip:
            return
        pw = self.password_of(self.selected)
        if pw:
            self.clipboard_clear()
            self.clipboard_append(pw)
        popen(["mstsc", f"/v:{ip}"])
        self.log(f"RDP → {ip} · user={RDP_USER} · كلمة السر في الحافظة")

    # ── scrcpy (وضع root) + المِرآة المدمجة (كل الأوضاع) ──
    def open_scrcpy(self):
        """يشغّل scrcpy في الوضعين:
        - root : اتصال مباشر بـ adbd على IP:15555
        - play : نفق SSH ذكي إلى forward الذي ينشئه scrcpy على المضيف
        """
        if not self.require_sel():
            return
        r = self.selected
        if not r.get("online") or not r.get("ip"):
            messagebox.showinfo("تنبيه", "السيرفر غير متصل")
            return
        key = f"scrcpy:{r.get('ip')}"
        old = self._scrcpy.get(key)
        if old and old.get("proc") and old["proc"].poll() is None:
            self.log("scrcpy يعمل بالفعل — إحضار النافذة")
            self._bring_window_front(old["proc"].pid)
            return
        self._bg(lambda: self._scrcpy_run(r, key))

    def _scrcpy_run(self, r, key):
        is_root = r.get("root") == "1"
        mode = "direct" if is_root else "tunnel"
        self.after(0, lambda: self.log(f"scrcpy: تجهيز ({mode}) → {r.get('ip')}"))
        ctx = None
        try:
            if is_root:
                dev = f"{r['ip']}:15555"
                sh([ADB, "connect", dev], timeout=12)
                st = adb_state(dev)
                if st != "device":
                    raise RuntimeError(f"adb: {st or 'غير متصل'} — ثبّت مفتاح SSH أو أعد الإنشاء")
                serial = dev
                ctx = {}
            else:
                # صور Play تفرض مصادقة adb ولا يمكن لـ scrcpy إنشاء نفق محليًا
                self.after(0, self._scrcpy_play_hint)
                return
            self._ssh("~/bin/ctl.sh wake", timeout=20, row=r)
        except Exception as e:
            if ctx:
                self._scrcpy_ctx_close(ctx)
            self.after(0, lambda e=e: self._scrcpy_error(str(e)))
            return

        logf = os.path.join(tempfile.gettempdir(),
                            f"scrcpy-slot{r.get('slot')}-{int(time.time())}.log")
        env = os.environ.copy()
        env["PATH"] = os.path.dirname(ADB) + os.pathsep + env.get("PATH", "")
        args = [SCRCPY, "-s", serial, "--max-size=720", "--max-fps=30",
                "--video-bit-rate=3M", "--no-audio", "--stay-awake",
                f"--window-title=Android {r.get('ip')}"]
        if mode == "tunnel":
            env["ANDROID_ADB_SERVER_ADDRESS"] = r["ip"]
            env["ANDROID_ADB_SERVER_PORT"] = str(r.get("adb_server") or "15037")
            args += ["--tunnel-host=127.0.0.1", f"--tunnel-port={ctx['port']}", "--force-adb-forward"]
        fh = open(logf, "w", encoding="utf-8", errors="replace")
        try:
            proc = subprocess.Popen(args, stdout=fh, stderr=subprocess.STDOUT, env=env)
        except Exception as e:
            if ctx:
                self._scrcpy_ctx_close(ctx)
            self.after(0, lambda e=e: self._scrcpy_error(f"تعذّر تشغيل scrcpy: {e}"))
            return
        self._scrcpy[key] = {"proc": proc, "ctx": ctx}

        # راقب ١٥ ثانية: نافذة/nothing أو خروج بخطأ
        for _ in range(30):
            time.sleep(0.5)
            if proc.poll() is not None:
                break
        if proc.poll() is not None:
            try:
                fh.flush()
                tail = open(logf, encoding="utf-8", errors="replace").read()[-700:]
            except Exception:
                tail = ""
            if ctx:
                self._scrcpy_ctx_close(ctx)
            self.after(0, lambda: self._scrcpy_error(
                f"انتهى scrcpy بكود {proc.returncode}:\n{tail}\n\nالسجل: {logf}"))
            return
        self._bring_window_front(proc.pid)
        self.after(0, lambda: self.log(
            f"scrcpy يعمل ✓ ({mode}) · سجل: {os.path.basename(logf)}"))

        def watch():
            try:
                proc.wait()
            except Exception:
                pass
            if ctx:
                self._scrcpy_ctx_close(ctx)
            self._scrcpy.pop(key, None)

        threading.Thread(target=watch, daemon=True).start()

    def _scrcpy_play_hint(self):
        if messagebox.askyesno(
                "scrcpy لا يعمل في وضع Play",
                "صورة Google Play تفرض مصادقة adb (ro.adb.secure=1) ولا يمكن تعطيلها،\n"
                "لذلك لا يستطيع scrcpy الاتصال بالجهاز.\n\n"
                "البديل: «المِرآة المدمجة» — إدخال فوري (~150ms) وعرض حيّ.\n"
                "للحصول على سلاسة scrcpy الكاملة: أنشئ السيرفر بوضع root.\n\n"
                "هل تفتح المِرآة الآن؟"):
            self.open_mirror()
    def _scrcpy_tunnel_ctx(self, r, port=27183):
        """نفق SSH: localhost:27183 ← مضيف:27183.

        scrcpy ينشئ forward على المضيف تلقائيًا (يختار 27183 بعد تفريغ الـforwards)،
        ثم يتصل بـ --tunnel-port=27183 محليًا ⇒ يمر عبر هذا النفق.
        الاتصال يُعاد حتى يجهز forward (lazy) لتفادي سباق البدء.
        """
        if not HAS_SSH:
            raise RuntimeError("paramiko غير متاح")
        c = self._connect_ssh(r)

        def shc(cmd, t=30):
            _, so, se = c.exec_command(cmd, timeout=t)
            return (so.read() + se.read()).decode("utf-8", "replace").strip()

        shc(f"{RADB} forward --remove-all")      # يجعل adb يختار 27183
        tr = c.get_transport()
        srv = socket.socket()
        try:
            srv.bind(("127.0.0.1", port))
        except OSError as e:
            c.close()
            raise RuntimeError(f"المنفذ المحلي {port} مشغول ({e}). أغلق أي scrcpy قديم.")
        srv.listen(8)
        state = {"stop": False}

        def pipe(a, b):
            try:
                while not state["stop"]:
                    d = a.recv(65536)
                    if not d:
                        break
                    b.sendall(d)
            except Exception:
                pass

        def handle(cli, peer):
            # خيط مستقل لكل اتصال حتى لا يُحجز الاستقبال (مهم: scrcpy يتصل فورًا)
            ch = None
            for _ in range(140):
                if state["stop"]:
                    break
                try:
                    ch = tr.open_channel("direct-tcpip", ("127.0.0.1", port), peer)
                    break
                except Exception:
                    time.sleep(0.25)
            if ch is None:
                try:
                    cli.close()
                except Exception:
                    pass
                return
            threading.Thread(target=pipe, args=(cli, ch), daemon=True).start()
            threading.Thread(target=pipe, args=(ch, cli), daemon=True).start()

        def serve():
            while not state["stop"]:
                try:
                    cli, peer = srv.accept()
                except OSError:
                    return
                threading.Thread(target=handle, args=(cli, peer), daemon=True).start()

        threading.Thread(target=serve, daemon=True).start()
        return {"ssh": c, "srv": srv, "state": state, "port": port}

    def _scrcpy_ctx_close(self, ctx):
        try:
            ctx["state"]["stop"] = True
        except Exception:
            pass
        try:
            ctx["srv"].close()
        except Exception:
            pass
        try:
            ctx["ssh"].close()
        except Exception:
            pass

    def _scrcpy_error(self, detail):
        self.log("scrcpy فشل: " + str(detail).replace("\n", " / ")[:300])
        messagebox.showerror(
            "scrcpy لم يعمل",
            f"{detail}\n\n"
            "حلول سريعة:\n"
            "• جرّب زر «المِرآة المدمجة» (يعمل دائمًا)\n"
            "• تأكد أن السيرفر متصل واضغط تحديث\n"
            "• إن كان السيرفر قديمًا (قبل التحديث) أعد إنشاءه ليأخذ مفتاح SSH")

    def _bring_window_front(self, pid, tries=25):
        """يجلب نافذة العملية للأمام — কারণ نوافذ scrcpy تُفتح خلف التطبيق."""
        try:
            import ctypes
            import ctypes.wintypes as wt
        except Exception:
            return False
        user32 = ctypes.windll.user32
        Proc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

        def find():
            hits = []
            def cb(hwnd, _l):
                p = wt.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
                if p.value == pid and user32.GetWindowTextLengthW(hwnd) > 0:
                    hits.append(hwnd)
                return True
            user32.EnumWindows(Proc(cb), 0)
            return hits

        for _ in range(tries):
            hs = find()
            if hs:
                for h in hs:
                    user32.ShowWindow(h, 9)          # SW_RESTORE
                    user32.SetForegroundWindow(h)
                    user32.BringWindowToTop(h)
                return True
            time.sleep(0.4)
        return False

    # ── الحافظة (نسخ/لصق بين الحاسوب والأندرويد) ──
    def _win_clipboard(self):
        try:
            return self.clipboard_get()
        except Exception:
            return ""

    @staticmethod
    def _as_url(text):
        t = (text or "").strip()
        if not t or "\n" in t:
            return ""
        if re.match(r"^https?://\S+$", t, re.I):
            return t
        if re.match(r"^[\w.-]+\.[a-z]{2,}(/\S*)?$", t, re.I):
            return "https://" + t
        return ""

    def open_clipboard_dialog(self):
        """نافذة النسخ واللصق: رابط، نص، أو حافظة الأندرويد."""
        if not self.require_sel():
            return
        r = self.selected
        if not r.get("online") or not r.get("ip"):
            messagebox.showinfo("تنبيه", "السيرفر غير متصل")
            return
        w = tk.Toplevel(self)
        w.title("الحافظة — نسخ ولصق")
        w.configure(bg=BG)
        w.geometry("560x300")
        w.transient(self)

        tk.Label(w, text="محتوى حافظة الحاسوب:", bg=BG, fg=MUTED).pack(anchor="e", padx=12, pady=(10, 2))
        box = tk.Text(w, height=4, bg="#0e0f14", fg=FG, relief="flat",
                      font=("Consolas", 9), wrap="word", padx=8, pady=6)
        box.pack(fill="x", padx=12)
        box.insert("1.0", self._win_clipboard())
        box.configure(state="normal")

        def refresh():
            box.delete("1.0", "end")
            box.insert("1.0", self._win_clipboard())

        btns = tk.Frame(w, bg=BG)
        btns.pack(fill="x", padx=12, pady=10)

        def do_open():
            url = self._as_url(box.get("1.0", "end"))
            if not url:
                messagebox.showinfo("تنبيه", "المحتوى ليس رابطًا صالحًا", parent=w)
                return
            self.ctl(f"open-url {shlex.quote(url)}")
            w.destroy()

        def do_paste():
            data = box.get("1.0", "end").rstrip("\n")
            if not data:
                messagebox.showinfo("تنبيه", "الحافظة فارغة", parent=w)
                return
            b64 = base64.b64encode(data.encode("utf-8")).decode()
            self.ctl(f"paste-b64 {b64}")
            w.destroy()

        def do_clip():
            data = box.get("1.0", "end").rstrip("\n")
            if not data:
                messagebox.showinfo("تنبيه", "الحافظة فارغة", parent=w)
                return
            b64 = base64.b64encode(data.encode("utf-8")).decode()
            self.ctl(f"ensure-clipper")
            time.sleep(0.2)
            self.ctl(f"clip-set-b64 {b64}")
            w.destroy()

        ttk.Button(btns, text="🔗 افتح في كروم", style="Accent.TButton",
                   command=do_open).pack(side="right", padx=3)
        ttk.Button(btns, text="⌨ لصق كنص في الحقل", command=do_paste).pack(side="right", padx=3)
        ttk.Button(btns, text="📋 ضع في حافظة الأندرويد", command=do_clip).pack(side="right", padx=3)
        ttk.Button(btns, text="⟳ تحديث", command=refresh).pack(side="left", padx=3)
        tk.Label(w, text="«افتح في كروم» يفتح الرابط مباشرة. «لصق كنص» يكتبه في الحقل المحدد. "
                         "«حافظة الأندرويد» يتيح الضغط المطوّل ← لصق في أي تطبيق.",
                 bg=PANEL, fg=MUTED, justify="right", wraplength=520,
                 font=("Segoe UI", 8), padx=8, pady=6).pack(fill="x", padx=12, pady=(0, 10))

    def open_mirror(self):
        """مِرآة مدمجة: بث الشاشة عبر SSH + تحكم (تعمل في وضعي Play وroot)."""
        if not self.require_sel():
            return
        r = self.selected
        if not r.get("online") or not r.get("ip"):
            messagebox.showinfo("تنبيه", "السيرفر غير متصل")
            return
        if not HAS_PIL:
            messagebox.showerror("تنبيه", "Pillow غير مثبّت (pip install pillow)")
            return
        MirrorWindow(self, dict(r))

    def install_ssh_key(self):
        """يثبّت مفتاح SSH على سيرفر قائم (مرة واحدة) — بعدها لا نحتاج كلمة السر."""
        if not self.require_sel():
            return
        r = self.selected
        if not r.get("online") or not r.get("ip"):
            messagebox.showinfo("تنبيه", "السيرفر غير متصل")
            return
        _key, pub = ensure_ssh_key()
        if not pub:
            messagebox.showerror("تنبيه", "تعذّر توليد مفتاح SSH محلي")
            return
        pw = self.password_of(r)
        if not pw:
            messagebox.showinfo(
                "تنبيه",
                "لتثبيت المفتاح لأول مرة نحتاج كلمة السر.\n"
                "استخدم «تعيين كلمة السر» ثم أعد المحاولة.")
            return

        def work():
            cmd = ("mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
                   f"grep -qF '{pub}' ~/.ssh/authorized_keys 2>/dev/null || "
                   f"echo '{pub}' >> ~/.ssh/authorized_keys; "
                   "chmod 600 ~/.ssh/authorized_keys; "
                   f"grep -qF '{pub}' ~/.ssh/authorized_keys && echo KEY_INSTALLED")
            out = self._ssh(cmd, timeout=30, row=r)
            self.after(0, lambda: self.log(f"مفتاح SSH: {out[:160]}"))
            if "KEY_INSTALLED" in (out or ""):
                self.after(0, lambda: messagebox.showinfo(
                    "تم", "ثُبّت مفتاح SSH ✓\nمن الآن تعمل كل الأزرار دون كلمة سر."))
            self.after(0, self.refresh)

        self._bg(work)

    def open_ssh(self):
        if not self.require_sel() or not self.selected.get("ip"):
            return
        pw = self.password_of(self.selected)
        if pw:
            self.clipboard_clear()
            self.clipboard_append(pw)
        popen(["cmd", "/c", "start", "cmd", "/k", f"ssh {RDP_USER}@{self.selected['ip']}"])
        self.log(f"SSH → {RDP_USER}@{self.selected['ip']} · كلمة السر في الحافظة")

    def show_stats(self):
        if not self.require_sel() or not self.selected.get("online"):
            return

        def work():
            out = self._ssh("IDX=0 ~/bin/ctl.sh stats")
            pk = self._ssh("IDX=0 ~/bin/ctl.sh pkgs")
            self.after(0, lambda: self._stats_window(out, pk))

        self._bg(work)

    def _stats_window(self, stats, pkgs):
        w = tk.Toplevel(self)
        w.title(f"الأداء — slot {self.selected.get('slot')}")
        w.configure(bg=BG)
        w.geometry("640x360")
        txt = tk.Text(w, bg="#0e0f14", fg="#8fe6a8", font=("Consolas", 9),
                      wrap="word", relief="flat", padx=10, pady=8)
        txt.pack(fill="both", expand=True, padx=8, pady=8)
        txt.insert("end", f"=== موارد السيرفر ===\n{stats}\n\n=== الحزم ===\n{pkgs}\n")
        txt.configure(state="disabled")
        ttk.Button(w, text="إغلاق", command=w.destroy).pack(pady=(0, 8))

    def screenshot(self):
        if not self.require_sel() or not self.selected.get("online"):
            return

        def work():
            out = self._ssh("IDX=0 ~/bin/ctl.sh shot /tmp/sm-shot.png")
            remote = out.strip().splitlines()[-1] if out.strip() else ""
            if not remote.startswith("/tmp/"):
                self.after(0, lambda: self.log(f"فشل التقاط الصورة: {out[:200]}"))
                return
            local = os.path.join(os.environ.get("TEMP", "."), "sm-shot.png")
            try:
                c = self._connect_ssh(self.selected)
                sftp = c.open_sftp()
                sftp.get(remote, local)
                sftp.close()
                c.close()
            except Exception as e:
                self.after(0, lambda: self.log(f"فشل النقل: {e}"))
                return
            self.after(0, lambda: self._show_image(local))

        self._bg(work)

    def _show_image(self, path):
        if not HAS_PIL:
            os.startfile(path)
            self.log(f"الصورة: {path}")
            return
        try:
            w = tk.Toplevel(self)
            w.title("شاشة الأندرويد")
            w.configure(bg=BG)
            img = Image.open(path)
            img.thumbnail((520, 920))
            ph = ImageTk.PhotoImage(img)
            lbl = tk.Label(w, image=ph, bg=BG)
            lbl.image = ph
            lbl.pack(padx=8, pady=8)
            self.log("صورة الشاشة ✓")
        except Exception as e:
            self.log(f"عرض الصورة: {e}")

    def install_apk(self):
        if not self.require_sel() or not self.selected.get("online"):
            return
        path = filedialog.askopenfilename(title="اختر ملف APK",
                                          filetypes=[("Android APK", "*.apk"), ("All", "*.*")])
        if not path:
            return

        def work():
            self.after(0, lambda: self.log(f"رفع {os.path.basename(path)}…"))
            try:
                c = self._connect_ssh(self.selected, timeout=20)
                sftp = c.open_sftp()
                sftp.put(path, "/tmp/up.apk")
                sftp.close()
                c.close()
            except Exception as e:
                self.after(0, lambda: self.log(f"فشل الرفع: {e}"))
                return
            out = self._ssh("IDX=0 ~/bin/ctl.sh install /tmp/up.apk", timeout=180)
            self.after(0, lambda: self.log(f"تثبيت APK: {out[:300]}"))

        self._bg(work)

    def act_root(self):
        self.ctl("root")

    def act_reboot(self):
        if not self.require_sel():
            return
        if not messagebox.askyesno("تأكيد", "إعادة تشغيل أندرويد على هذا السيرفر؟"):
            return
        self.ctl("reboot")

    def copy_row(self):
        if not self.require_sel():
            return
        r = self.selected
        pw = self.password_of(r) or "غير معروفة"
        txt = (f"slot: {r['slot']}\nIP: {r['ip']}\nRDP: {r['ip']}:3389\n"
               f"user: {RDP_USER}\npassword: {pw}\n"
               f"ADB: adb connect {r['ip']}:15555\nSSH: ssh {RDP_USER}@{r['ip']}\n"
               f"mode: {r['mode']}  root: {r['root']}  desktop: {r['desktop']}\n"
               f"android: {r['android']}  cores: {r['cores']}  mem: {r['mem']}MB\n"
               f"MAC: {r['mac'] or '-'}\nIMEI: {r['imei'] or '-'}\n"
               f"android_id: {r['aid'] or '-'}\nrun: {r['run']}")
        self.clipboard_clear()
        self.clipboard_append(txt)
        self.log("نُسخت بيانات السيرفر إلى الحافظة ✓")

    def set_password(self):
        if not self.require_sel():
            return
        r = self.selected
        val = simpledialog.askstring("كلمة سر السيرفر",
                                        "أدخل كلمة السر الحالية لهذا السيرفر:",
                                        parent=self)
        if not val:
            return
        self.store["servers"][str(r.get("run") or r.get("slot"))] = {
            "password": val.strip(), "slot": r.get("slot"), "ts": time.time()}
        save_store(self.store)
        self.log("حُفظت كلمة السر محليًا ✓")
        self.refresh()

    def show_details(self):
        if not self.require_sel():
            return
        r = self.selected
        pw = self.password_of(r) or "—"
        txt = (f"Slot: {r['slot']}\nIP: {r['ip'] or '—'}\nالحالة: {r['state']}\n"
               f"الوضع: {r['mode']} (root={r['root']})\nسطح المكتب: {r['desktop']}\n"
               f"كلمة السر: {pw}\nRun: {r['run'] or '—'}\nAndroid: {r['android']}\n"
               f"CPU: {r['cores'] or '—'} · RAM: {r['mem'] or '—'}MB\n"
               f"MAC: {r['mac'] or '—'}\nIMEI: {r['imei'] or '—'}\n"
               f"Android ID: {r['aid'] or '—'}\nPorts: {r['ports'] or '—'}\n"
               f"المتبقي: {(fmt_remaining(r['start']) or '—') if r['online'] else '—'}")
        messagebox.showinfo("بيانات السيرفر", txt)

    # ── تغيير من الخارج ──
    def set_geo(self):
        if not self.require_sel():
            return
        lat, lon = self.lat.get().strip(), self.lon.get().strip()
        try:
            float(lat)
            float(lon)
        except Exception:
            messagebox.showinfo("تنبيه", "أدخل إحداثيات صحيحة lat و lon")
            return
        self.ctl(f"geo {lat} {lon}")

    def auto_mac(self):
        if not self.require_sel():
            return
        if self.selected.get("root") != "1":
            messagebox.showinfo("تنبيه", "تغيير MAC يحتاج وضع root.\nأنشئ السيرفر بوضع root.")
            return
        self.mac.set(gen_mac())
        self.set_mac()

    def set_mac(self):
        if not self.require_sel():
            return
        if self.selected.get("root") != "1":
            messagebox.showinfo("تنبيه", "تغيير MAC يحتاج وضع root.")
            return
        mac = self.mac.get().strip().upper()
        if not re.fullmatch(r"([0-9A-F]{2}:){5}[0-9A-F]{2}", mac):
            messagebox.showinfo("تنبيه", "صيغة MAC غير صحيحة (02:AA:BB:CC:DD:EE)")
            return
        self.ctl(f"mac {mac}")

    def auto_imei(self):
        if not self.require_sel():
            return
        self.imei.set(gen_imei())
        self.set_imei()

    def set_imei(self):
        if not self.require_sel():
            return
        val = self.imei.get().strip()
        if not re.fullmatch(r"\d{15}", val):
            messagebox.showinfo("تنبيه", "IMEI يجب أن يكون 15 رقمًا")
            return
        if not messagebox.askyesno(
                "تغيير IMEI",
                f"سيتم ترقيع المحاكي وإعادة تشغيله بـ IMEI = {val}\n"
                "يستغرق ~60-120 ثانية ويبقى كل شيء داخل الجهاز (بيانات/تطبيقات).\n\nمتابعة؟"):
            return
        self.ctl(f"imei {val}")

    def auto_aid(self):
        if not self.require_sel():
            return
        self.aid.set(secrets.token_hex(8))
        self.set_aid()

    def set_aid(self):
        if not self.require_sel():
            return
        val = self.aid.get().strip().lower()
        if not re.fullmatch(r"[0-9a-f]{16}", val):
            messagebox.showinfo("تنبيه", "Android ID يجب أن يكون 16 محرفًا hex")
            return
        self.ctl(f"aid {val}")

    def set_proxy(self, off):
        if not self.require_sel():
            return
        if off:
            self.ctl("proxy off")
        else:
            val = self.proxy.get().strip()
            if not val:
                messagebox.showinfo("تنبيه", "أدخل host:port")
                return
            self.ctl(f"proxy {val}")


if __name__ == "__main__":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    App().mainloop()