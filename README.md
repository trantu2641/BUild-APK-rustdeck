# RustDesk Root Input Patch (Android, ARM64)

This is a source patch kit for RustDesk Android, built from the Android `InputService.kt` structure at commit `53996e3c404ea5083df0775057e4149e49102084`.

## What it changes

- Adds a root input path for pointer tap, drag/swipe, long press, wheel/back/home/recents gestures and basic ASCII text/key events on SystemUI, Android Settings, permission-controller, and keyboard/IME windows.
- Keeps the existing RustDesk Accessibility path for ordinary app windows to reduce impact on normal remote-control gestures.
- Uses `/system/bin/input` via `su -c`; shell arguments are quoted and input coordinates are numeric.
- Enables the root route only when `su -c id -u` returns `0`. If root is unavailable, the existing RustDesk Accessibility/IME implementation remains the fallback.
- Does **not** modify screen capture, MediaProjection, screen-sharing confirmation, auto-confirm modules, status-bar indicators, or Android PIN/credential validation.

The root path is best-effort. It is selected using the active accessibility window package; package names on customized ROMs can differ, so some dialogs may still use the original Accessibility path. Whether `input` can inject events into every SystemUI/Keyguard surface depends on the ROM and Android security policy. It does not decrypt data or bypass the screen lock; it sends normal input events so the owner can enter valid credentials.

## Build with GitHub Actions

1. Create a GitHub repository for this patch kit and upload the files in this ZIP, preserving `.github/workflows/build-root-input-apk.yml`.
2. Open **Actions → Build RustDesk Root Input APK → Run workflow**.
3. Wait for the ARM64 build to finish. Download artifact `rustdesk-rootinput-arm64`.

The workflow checks out the pinned RustDesk source, applies the patch, builds the Android ARM64 APK, and uploads it as an artifact. The first build can take a long time because it compiles Rust and vcpkg dependencies.

## Install notes

- Grant root access to the RustDesk app in Magisk Superuser. The `InputService` probes root after it connects; if the root prompt times out or is denied, the old Accessibility path continues to be used.
- The build uses a debug signing key. It cannot update an official APK signed by a different key. Back up your RustDesk ID, password, server, and other settings before uninstalling the official version; uninstalling can erase app data.
- Keep your existing screen-share auto-confirm and Screen Guard modules enabled as separate modules. This patch does not touch their files or behavior.
- If the APK does not build, read the failed GitHub Actions step. If root input makes controls worse, disable/revert this APK and reinstall your prior RustDesk build.

## Manual patch

From a RustDesk source checkout matching the pinned commit:

```sh
python3 apply_root_input_patch.py /path/to/rustdesk
```

Then follow the Android build instructions in the RustDesk repository. The patcher refuses to write if an expected source anchor does not match, and is idempotent if the patch marker is already present.
