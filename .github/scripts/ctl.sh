#!/usr/bin/env bash
# android-server control helper — runs on the GitHub runner, called over SSH
# by the desktop app. Every action prints a short human readable result.
#
#   IDX=0 ~/bin/ctl.sh stats
#   ~/bin/ctl.sh geo 33.5731 -7.5898
#   ~/bin/ctl.sh mac 02:AA:BB:CC:DD:EE
#   ~/bin/ctl.sh imei 356938035643809
set -uo pipefail

SDK="${ANDROID_SDK_ROOT:-/usr/local/lib/android/sdk}"
ADB="$SDK/platform-tools/adb"
IDX="${IDX:-0}"
DEV="emulator-$(( 5554 + IDX * 2 ))"
ENVF="/opt/android-server/inst-$IDX.env"
[ -f "$ENVF" ] && . "$ENVF"
START="/opt/android-server/start-$IDX.sh"
PRIS="/opt/android-server/qemu-pristine-$IDX"

case "${1:-help}" in
  stats)
    echo "CPU: $(nproc) cores | load $(cut -d' ' -f1-3 /proc/loadavg)"
    free -m | awk '/Mem:/{printf "RAM: %sMB used / %sMB total (%sMB free)\n",$3,$2,$4}'
    df -h / | tail -1 | awk '{printf "DISK: %s used of %s (%s)\n",$3,$2,$5}'
    echo "UPTIME: $(uptime -p)"
    echo "QEMU: $(pgrep -fc qemu-system-x86_64 2>/dev/null || echo 0) | xrdp: $(systemctl is-active xrdp 2>/dev/null || echo off) | ssh: $(systemctl is-active ssh 2>/dev/null || echo off)"
    echo "ANDROID boot_completed: $("$ADB" -s "$DEV" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')"
    "$ADB" -s "$DEV" shell "dumpsys cpuinfo 2>/dev/null | head -3" 2>/dev/null | head -3
    ;;
  geo)
    [ $# -ge 3 ] || { echo "usage: geo LAT LON"; exit 2; }
    "$ADB" -s "$DEV" emu geo fix "$3" "$2" >/dev/null 2>&1
    echo "gps=$2,$3"
    ;;
  geo-off)
    "$ADB" -s "$DEV" emu geo fix 0 0 >/dev/null 2>&1 || true
    echo "gps reset"
    ;;
  proxy)
    if [ "${2:-off}" = "off" ] || [ -z "${2:-}" ]; then
      "$ADB" -s "$DEV" shell settings put global http_proxy :0 >/dev/null 2>&1
      echo "proxy=off"
    else
      "$ADB" -s "$DEV" shell settings put global http_proxy "$2" >/dev/null 2>&1
      echo "proxy=$2"
    fi
    ;;
  mac)
    NEW=$(echo "${2:-}" | tr 'a-f' 'A-F')
    echo "$NEW" | grep -qE '^([0-9A-F]{2}:){5}[0-9A-F]{2}$' || { echo "bad mac (XX:XX:XX:XX:XX:XX)"; exit 2; }
    IFACE=$("$ADB" -s "$DEV" shell "ip -o link show" 2>/dev/null | grep -oE '(eth0|radio0)' | head -1)
    IFACE=${IFACE:-eth0}
    "$ADB" -s "$DEV" root >/dev/null 2>&1 || true
    sleep 2
    "$ADB" -s "$DEV" shell "su 0 ip link set $IFACE down" >/dev/null 2>&1 || true
    "$ADB" -s "$DEV" shell "su 0 ip link set $IFACE address $NEW" >/dev/null 2>&1
    "$ADB" -s "$DEV" shell "su 0 ip link set $IFACE up" >/dev/null 2>&1 || true
    sleep 1
    GOT=$("$ADB" -s "$DEV" shell "ip -o link show $IFACE" 2>/dev/null | grep -oE 'link/ether [0-9a-fA-F:]+' | awk '{print $2}')
    echo "iface=$IFACE mac($NEW) = ${GOT:-?}"
    ;;
  aid)
    echo "${2:-}" | grep -qE '^[0-9a-f]{16}$' || { echo "android_id must be 16 lowercase hex"; exit 2; }
    "$ADB" -s "$DEV" shell settings put secure android_id "${2}" >/dev/null 2>&1
    echo "android_id=${2} (يطبَّق بعد إعادة تشغيل التطبيقات)"
    ;;
  imei)
    echo "${2:-}" | grep -qE '^[0-9]{15}$' || { echo "imei must be 15 digits"; exit 2; }
    [ -f "$PRIS" ] || { echo "pristine qemu image missing"; exit 3; }
    [ -n "${QEMU:-}" ] || { echo "qemu path unknown"; exit 3; }
    [ -f /opt/android-server/patch-imei.py ] || { echo "patcher missing"; exit 3; }
    sudo -n cp -f "$PRIS" "$QEMU" 2>/dev/null || cp -f "$PRIS" "$QEMU" 2>/dev/null || { echo "cannot restore qemu"; exit 3; }
    sudo -n chmod u+w "$QEMU" 2>/dev/null || true
    sudo -n python3 /opt/android-server/patch-imei.py "$QEMU" "$2" \
      || python3 /opt/android-server/patch-imei.py "$QEMU" "$2"
    echo "$2" > "/opt/android-server/imei-$IDX"
    "$ADB" -s "$DEV" emu kill >/dev/null 2>&1 || true
    sleep 4
    nohup "$START" > "/tmp/emu$IDX.log" 2>&1 &
    echo "restarting emulator with IMEI=$2"
    ;;
  imei-show)
    cat "/opt/android-server/imei-$IDX" 2>/dev/null || echo "?"
    ;;
  read-imei)
    "$ADB" -s "$DEV" root >/dev/null 2>&1 || true
    sleep 2
    R=$("$ADB" -s "$DEV" shell "service call iphonesubinfo 1 s16 com.android.shell" 2>/dev/null)
    echo "$R" | grep -oE '[0-9]{15}' | head -1 || echo "unreadable"
    ;;
  root)
    "$ADB" -s "$DEV" root >/dev/null 2>&1 || true
    sleep 3
    for t in $(seq 1 20); do
      "$ADB" -s "$DEV" shell id 2>/dev/null | grep -q 'uid=0' && break
      sleep 1
    done
    "$ADB" -s "$DEV" shell id 2>/dev/null
    ;;
  nav)
    "$ADB" -s "$DEV" shell "cmd overlay enable-exclusive --category com.android.internal.systemui.navbar.threebutton" >/dev/null 2>&1
    "$ADB" -s "$DEV" shell settings put secure navigation_mode 0 >/dev/null 2>&1
    echo "three-button nav on"
    ;;
  play)
    "$ADB" -s "$DEV" shell pm enable com.android.vending >/dev/null 2>&1
    "$ADB" -s "$DEV" shell monkey -p com.android.vending -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
    echo "play store launched"
    ;;
  chrome)
    "$ADB" -s "$DEV" shell am start -n com.android.chrome/com.google.android.apps.chrome.Main >/dev/null 2>&1
    echo "chrome launched"
    ;;
  settings)
    "$ADB" -s "$DEV" shell am start -a android.settings.SETTINGS >/dev/null 2>&1
    echo "settings launched"
    ;;
  install)
    [ -f "${2:-}" ] || { echo "file not found: ${2:-}"; exit 2; }
    "$ADB" -s "$DEV" install -r -g "$2" 2>&1 | tail -2
    ;;
  shot)
    OUT="${2:-/tmp/screen-$IDX.png}"
    "$ADB" -s "$DEV" exec-out screencap -p > "$OUT" 2>/dev/null
    echo "$OUT"
    ;;
  key)
    "$ADB" -s "$DEV" shell input keyevent "$2"; echo "key $2"
    ;;
  tap)
    "$ADB" -s "$DEV" shell input tap "$2" "$3"; echo "tap $2 $3"
    ;;
  swipe)
    "$ADB" -s "$DEV" shell input swipe "$2" "$3" "$4" "$5" "${6:-300}"; echo "swipe done"
    ;;
  type)
    "$ADB" -s "$DEV" shell input text "$2"; echo "typed"
    ;;
  reboot)
    "$ADB" -s "$DEV" reboot; echo "android rebooting"
    ;;
  reboot-emulator)
    "$ADB" -s "$DEV" emu kill >/dev/null 2>&1 || true
    sleep 4
    nohup "$START" > "/tmp/emu$IDX.log" 2>&1 &
    echo "emulator restarted"
    ;;
  wake)
    "$ADB" -s "$DEV" shell "input keyevent KEYCODE_WAKEUP; wm dismiss-keyguard; settings put system screen_off_timeout 2147483647" >/dev/null 2>&1 || true
    echo "awake"
    ;;
  pkgs)
    echo "enabled=$("$ADB" -s "$DEV" shell pm list packages -e 2>/dev/null | wc -l) disabled=$("$ADB" -s "$DEV" shell pm list packages -d 2>/dev/null | wc -l)"
    ;;
  probe)
    IFACE=$("$ADB" -s "$DEV" shell "ip -o link show" 2>/dev/null | grep -oE '(eth0|radio0)' | head -1)
    IFACE=${IFACE:-eth0}
    MAC=$("$ADB" -s "$DEV" shell "ip -o link show $IFACE" 2>/dev/null | grep -oE 'link/ether [0-9a-fA-F:]+' | awk '{print $2}')
    AID=$("$ADB" -s "$DEV" shell settings get secure android_id 2>/dev/null | tr -d '\r')
    SER=$("$ADB" -s "$DEV" shell getprop ro.serialno 2>/dev/null | tr -d '\r')
    REL=$("$ADB" -s "$DEV" shell getprop ro.build.version.release 2>/dev/null | tr -d '\r')
    echo "mac=${MAC:-}"
    echo "aid=${AID:-}"
    echo "serial=${SER:-}"
    echo "android=${REL:-}"
    echo "iface=${IFACE}"
    ;; 
  imei-read)
    "$ADB" -s "$DEV" root >/dev/null 2>&1 || true
    sleep 2
    R=$("$ADB" -s "$DEV" shell "service call iphonesubinfo 1 s16 com.android.shell" 2>/dev/null)
    F=$(echo "$R" | grep -oE '[0-9]{15}' | head -1)
    echo "imei_from_android=${F:-unreadable}"
    echo "imei_configured=$(cat /opt/android-server/imei-$IDX 2>/dev/null || echo '?')"
    ;;
  *)
    echo "ctl.sh {stats|geo LAT LON|geo-off|proxy HOST:PORT|proxy off|mac XX:..|aid HEX16|imei 15digits|imei-show|read-imei|root|nav|play|chrome|settings|install FILE|shot [OUT]|key CODE|tap X Y|swipe X1 Y1 X2 Y2 [MS]|type TEXT|reboot|reboot-emulator|pkgs}"
    ;;
esac
