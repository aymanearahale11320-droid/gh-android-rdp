#!/usr/bin/env python3
"""Patch the emulator's hardcoded IMEI constant inside qemu-system-x86_64.

The upstream Android emulator embeds exactly one literal 15-digit IMEI
(358240051111110) in the QEMU binary. Android's emulated modem reports it,
so replacing it with another 15-digit value changes the IMEI seen by Android
and by every application.

usage: patch-imei.py <qemu-binary> <15-digit-imei>
exit : 0 ok | 2 bad args/imei | 3 pattern not found
"""
import sys

OLD = b"358240051111110"


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: patch-imei.py <qemu-binary> <imei15>")
        return 2
    path, imei = sys.argv[1], sys.argv[2]
    if len(imei) != 15 or not imei.isdigit():
        print("IMEI_INVALID (must be exactly 15 digits)")
        return 2
    data = bytearray(open(path, "rb").read())
    new = imei.encode()
    if new in data and OLD not in data:
        print(f"already patched -> {imei}")
        return 0
    idx = data.find(OLD)
    if idx < 0:
        print("IMEI_PATTERN_MISSING (emulator binary layout changed)")
        return 3
    data[idx:idx + len(OLD)] = new
    with open(path, "wb") as fh:
        fh.write(data)
    print(f"patched offset {idx} -> {imei}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
