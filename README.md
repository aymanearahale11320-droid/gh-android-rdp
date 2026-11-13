# gh-android-rdp

سيرفر أندرويد كامل على GitHub Actions: Ubuntu 24.04 + KVM + محاكي أندرويد +
Tailscale، يُدار من تطبيق سطح المكتب `server-manager.pyw`.

## أوضاع التشغيل

| الوضع | الصورة | Google Play | Root | تغيير MAC |
|---|---|---|---|---|
| `play` (الافتراضي) | `google_apis_playstore` | ✅ عامل | ❌ | ❌ |
| `root` | `google_apis` | ❌ (stub) | ✅ كامل | ✅ |

> Play Store يحتاج صورة موقّعة بمفتاح release ⇒ `adb root` ممنوع فيها.
> لذلك لا يمكن الجمع بين المتجر والروت في نفس المحاكي (إلا بـ Magisk/rootAVD).

## المدخلات (workflow_dispatch)

| الاسم | الافتراضي | المعنى |
|---|---|---|
| `slot` | 1 | رقم السيرفر 1-10 (كل slot مستقل، له ملف حالة خاص) |
| `instances` | 1 | عدد المحاكيات (1-3) |
| `api_level` | 30 | أندرويد 11 |
| `mode` | play | `play` أو `root` |
| `desktop` | false | `true` = سطح مكتب xfce + RDP (يأكل موارد) |
| `password` | "" | كلمة سر السيرفر (فارغة = من `RDP_PASSWORD` ثم عشوائية) |
| `imei` | "" | IMEI مخصص 15 رقمًا (فارغ = توليد فريد Luhn) |

## الوصول

| القناة | العنوان |
|---|---|
| SSH | `ssh runner@<IP>` (كلمة السر) |
| RDP | `<IP>:3389` — فقط إذا `desktop=true` |
| ADB (الأفضل) | `adb -H <IP> -P 15037 devices` ثم `-s emulator-5554` |
| scrcpy | `ANDROID_ADB_SERVER_ADDRESS=<IP> ANDROID_ADB_SERVER_PORT=15037 scrcpy -s emulator-5554` |

> منفذ `15037` = adb **server** الخاص بالمضيف (مصرّح مسبقًا) — يتجاوز مصادقة
> `adbd` في صور Play حيث `ro.adb.secure=1`. المنفذ `15555` يبقى موجّهًا إلى
> `adbd` ويعمل مباشرة في وضع root.
>
> `scrcpy` مرفق مع المشروع على هذا الجهاز. المنافذ كلها مفتوحة على tailnet فقط.

## أدوات التحكم على المضيف

```bash
~/bin/ctl.sh stats            # موارد + حالة
~/bin/ctl.sh probe            # mac / android_id / serial / iface
~/bin/ctl.sh geo 33.57 -7.59  # GPS
~/bin/ctl.sh proxy HOST:PORT  # أو: proxy off
~/bin/ctl.sh mac 02:AA:BB:CC:DD:EE     # وضع root فقط
~/bin/ctl.sh imei 356938035643809      # ترقيع qemu + إعادة تشغيل المحاكي
~/bin/ctl.sh aid 0123456789abcdef      # Android ID
~/bin/ctl.sh root | nav | play | chrome | settings
~/bin/ctl.sh install /tmp/app.apk | shot /tmp/s.png
~/bin/ctl.sh key 3 | tap X Y | swipe X1 Y1 X2 Y2 | type "text"
~/bin/ctl.sh reboot | reboot-emulator
```

## ملاحظات تقنية

- **IMEI**: المحاكي يضم ثابت IMEI واحد (`358240051111110`) داخل
  `qemu-system-x86_64`، ويُستبدل بسلسلة 15 رقمًا فريدة (ترقيع ثنائي).
  تم التحقق أن الثابت يقع بين أوامر GSM (`+CRRSTR`, `+CGLA`) أي أنه هوية
  المودم. **لا يمكن قراءة القيمة من داخل أندرويد** على API 30
  (`iphonesubinfo` يعيد null حتى مع root) — التغيير يقع على مستوى المودم فقط.
- **الأداء**: المحاكي يحصل على كل موارد الجهاز (4 أنوية، حتى 8GB)،
  وسطح المكتب معطّل افتراضيًا. المحاكي يُطلق قبل Tailscale لتقليل زمن الجاهزية
  (≈ ١٠٠ ثانية في الاختبار الفعلي).
- **كاش**: صورة النظام تُحفظ في Actions cache (أسرع بكثير بعد أول تشغيل).
- **Watchdog**: يعيد تشغيل المحاكي/socat/xrdp عند السقوط.
- **الحد الصلب**: 6 ساعات لكل job على GitHub-hosted.
