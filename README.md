# gh-android-rdp

Ubuntu 24.04 + KVM + Android emulator + xfce desktop + Chrome, reachable over Tailscale.

## Required secrets

| Name | Required | Purpose |
|---|---|---|
| `TAILSCALE_AUTHKEY` | yes | joins the runner to your tailnet |
| `RDP_PASSWORD` | no | desktop login (random one is generated if absent) |

## Usage

Actions -> final-android-desktop -> Run workflow.
Connect via RDP to `<ip>:3389`, or from your PC: `adb connect <ip>:5555` then `scrcpy`.

Hard limit: GitHub-hosted jobs are killed at 6 hours.
