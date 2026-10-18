#!/usr/bin/env python3
"""Patch RustDesk Android InputService with optional Magisk-su input dispatch.

Run from a patch-kit checkout:
  python3 apply_root_input_patch.py /path/to/rustdesk-source

Pinned/tested against the InputService.kt layout from RustDesk commit
53996e3c404ea5083df0775057e4149e49102084. This edits only InputService.kt.
"""
from pathlib import Path
import sys

RELATIVE = Path("flutter/android/app/src/main/kotlin/com/carriez/flutter_hbb/InputService.kt")
MARKER = "// ROOT_INPUT_PATCH_V1"

HELPERS = r'''    // ROOT_INPUT_PATCH_V1: Use Magisk su to inject user-requested input on system UI screens.
    // Root must already be authorized for com.carriez.flutter_hbb in Magisk.
    private val rootInputExecutor = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "rustdesk-root-input").apply { isDaemon = true }
    }

    @Volatile private var rootInputReady = false
    @Volatile private var activeWindowPackageName: String? = null
    private val rootInputPackages = setOf(
        "android",
        "com.android.systemui",
        "com.android.settings",
        "com.android.permissioncontroller",
        "com.google.android.permissioncontroller",
        "com.android.packageinstaller",
        "com.google.android.packageinstaller",
        "com.android.providers.settings"
    )
    private var rootPointerDown = false
    private var rootGestureMoved = false
    private var rootGestureStartX = 0
    private var rootGestureStartY = 0
    private var rootGestureStartAt = 0L

    private fun probeRootInput() {
        rootInputExecutor.execute {
            var process: Process? = null
            try {
                process = ProcessBuilder("su", "-c", "id -u")
                    .redirectErrorStream(true).start()
                val completed = process.waitFor(15, TimeUnit.SECONDS)
                if (!completed) {
                    process.destroyForcibly()
                    rootInputReady = false
                    Log.w(logTag, "Root input unavailable: su authorization timed out")
                    return@execute
                }
                val output = process.inputStream.bufferedReader().readText().trim()
                rootInputReady = process.exitValue() == 0 && output == "0"
                Log.i(logTag, "Root input available=$rootInputReady")
            } catch (e: Exception) {
                rootInputReady = false
                Log.w(logTag, "Root input probe failed: ${e.message}")
            } finally {
                try { process?.destroy() } catch (_: Exception) {}
            }
        }
    }

    private fun shouldUseRootForCurrentWindow(): Boolean {
        if (!rootInputReady) return false
        val packageName = activeWindowPackageName ?: return true
        return rootInputPackages.contains(packageName) ||
            packageName.contains("inputmethod", ignoreCase = true) ||
            packageName.contains("keyboard", ignoreCase = true)
    }

    private fun shellQuote(value: String): String = "'" + value.replace("'", "'\\''") + "'"

    private fun enqueueRootInput(vararg args: String) {
        if (!rootInputReady || args.isEmpty()) return
        val command = args.joinToString(" ") { shellQuote(it) }
        rootInputExecutor.execute {
            var process: Process? = null
            try {
                process = ProcessBuilder("su", "-c", command)
                    .redirectErrorStream(true).start()
                val completed = process.waitFor(3, TimeUnit.SECONDS)
                if (!completed) {
                    process.destroyForcibly()
                    Log.w(logTag, "Root input timed out: ${args.firstOrNull()}")
                    return@execute
                }
                val output = process.inputStream.bufferedReader().readText().trim()
                if (process.exitValue() != 0) {
                    Log.e(logTag, "Root input failed (${process.exitValue()}): $output")
                    rootInputReady = false
                }
            } catch (e: Exception) {
                Log.e(logTag, "Root input exception: ${e.message}")
                rootInputReady = false
            } finally {
                try { process?.destroy() } catch (_: Exception) {}
            }
        }
    }

    private fun beginRootGesture(x: Int, y: Int) {
        rootPointerDown = true
        rootGestureMoved = false
        rootGestureStartX = x
        rootGestureStartY = y
        rootGestureStartAt = System.currentTimeMillis()
    }

    private fun moveRootGesture(x: Int, y: Int) {
        if (rootPointerDown && abs(x - rootGestureStartX) + abs(y - rootGestureStartY) > 8) {
            rootGestureMoved = true
        }
    }

    private fun finishRootGesture(x: Int, y: Int) {
        if (!rootPointerDown) return
        val elapsed = (System.currentTimeMillis() - rootGestureStartAt).coerceAtLeast(1L)
        rootPointerDown = false
        if (rootGestureMoved) {
            val duration = elapsed.coerceIn(80L, 2000L).toString()
            enqueueRootInput("/system/bin/input", "swipe", rootGestureStartX.toString(), rootGestureStartY.toString(), x.toString(), y.toString(), duration)
        } else if (elapsed >= longPressDuration) {
            val duration = elapsed.coerceIn(longPressDuration, 3000L).toString()
            enqueueRootInput("/system/bin/input", "swipe", x.toString(), y.toString(), x.toString(), y.toString(), duration)
        } else {
            enqueueRootInput("/system/bin/input", "tap", x.toString(), y.toString())
        }
    }

    private fun handleRootMouseInput(mask: Int, rawX: Int, rawY: Int): Boolean {
        if (!shouldUseRootForCurrentWindow()) return false
        val x = max(0, rawX) * SCREEN_INFO.scale
        val y = max(0, rawY) * SCREEN_INFO.scale
        if (mask == 0 || mask == LEFT_MOVE || mask == LEFT_DOWN || mask == LEFT_UP) {
            mouseX = x
            mouseY = y
        }
        when (mask) {
            0, LEFT_MOVE -> moveRootGesture(mouseX, mouseY)
            LEFT_DOWN -> beginRootGesture(mouseX, mouseY)
            LEFT_UP -> finishRootGesture(mouseX, mouseY)
            RIGHT_UP -> enqueueRootInput("/system/bin/input", "swipe", mouseX.toString(), mouseY.toString(), mouseX.toString(), mouseY.toString(), longPressDuration.toString())
            BACK_UP -> enqueueRootInput("/system/bin/input", "keyevent", "4")
            WHEEL_BUTTON_DOWN -> {
                timer.purge()
                recentActionTask = object : TimerTask() {
                    override fun run() { enqueueRootInput("/system/bin/input", "keyevent", "187"); recentActionTask = null }
                }
                timer.schedule(recentActionTask, LONG_TAP_DELAY)
            }
            WHEEL_BUTTON_UP -> {
                if (recentActionTask != null) {
                    recentActionTask!!.cancel()
                    recentActionTask = null
                    enqueueRootInput("/system/bin/input", "keyevent", "3")
                }
            }
            WHEEL_DOWN -> if (mouseY >= WHEEL_STEP) enqueueRootInput("/system/bin/input", "swipe", mouseX.toString(), mouseY.toString(), mouseX.toString(), (mouseY - WHEEL_STEP).toString(), WHEEL_DURATION.toString())
            WHEEL_UP -> if (mouseY >= WHEEL_STEP) enqueueRootInput("/system/bin/input", "swipe", mouseX.toString(), mouseY.toString(), mouseX.toString(), (mouseY + WHEEL_STEP).toString(), WHEEL_DURATION.toString())
        }
        return true
    }

    private fun handleRootTouchInput(mask: Int, rawX: Int, rawY: Int): Boolean {
        if (!shouldUseRootForCurrentWindow()) return false
        when (mask) {
            TOUCH_PAN_START -> {
                mouseX = max(0, rawX) * SCREEN_INFO.scale
                mouseY = max(0, rawY) * SCREEN_INFO.scale
                beginRootGesture(mouseX, mouseY)
            }
            TOUCH_PAN_UPDATE -> {
                mouseX = max(0, mouseX - rawX * SCREEN_INFO.scale)
                mouseY = max(0, mouseY - rawY * SCREEN_INFO.scale)
                moveRootGesture(mouseX, mouseY)
            }
            TOUCH_PAN_END -> {
                finishRootGesture(mouseX, mouseY)
                mouseX = max(0, rawX) * SCREEN_INFO.scale
                mouseY = max(0, rawY) * SCREEN_INFO.scale
            }
        }
        return true
    }

    private fun rootTextArgument(text: String): String? {
        // Android's `input text` uses %s for spaces. Leave complex/non-ASCII text to RustDesk's existing IME path.
        if (text.any { it.code < 0x20 || it.code > 0x7e || it == '%' }) return null
        return text.replace(" ", "%s")
    }

    private fun dispatchRootKeyEvent(keyEvent: KeyEvent, androidEvent: KeyEventAndroid?, text: String?): Boolean {
        if (!shouldUseRootForCurrentWindow()) return false
        if (text != null) {
            val argument = rootTextArgument(text) ?: return false
            enqueueRootInput("/system/bin/input", "text", argument)
            return true
        }
        val event = androidEvent
        if (event != null && (keyEvent.getPress() || (keyEvent.getDown() && event.action == KeyEventAndroid.ACTION_DOWN))) {
            if (event.keyCode != KeyEventAndroid.KEYCODE_UNKNOWN) {
                enqueueRootInput("/system/bin/input", "keyevent", event.keyCode.toString())
            }
        }
        // Consume this key event in root mode so Accessibility/IME doesn't duplicate it.
        return true
    }

'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"Expected exactly one anchor for {label}, found {count}; source layout changed. No file written.")
    return text.replace(old, new, 1)


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python3 apply_root_input_patch.py /path/to/rustdesk-source", file=sys.stderr)
        return 2
    repo = Path(sys.argv[1]).resolve()
    target = repo / RELATIVE
    if not target.is_file():
        print(f"RustDesk InputService.kt not found: {target}", file=sys.stderr)
        return 2
    source = target.read_text(encoding="utf-8")
    if MARKER in source:
        print("Root input patch is already applied; leaving file unchanged.")
        return 0

    source = replace_once(
        source,
        "import java.util.*\nimport java.lang.Character\n",
        "import java.util.*\nimport java.util.concurrent.TimeUnit\nimport java.util.concurrent.Executors\nimport java.lang.Character\n",
        "imports",
    )
    source = replace_once(
        source,
        '    private val logTag = "input service"\n',
        '    private val logTag = "input service"\n\n' + HELPERS,
        "root-input helper methods",
    )
    source = replace_once(
        source,
        '    fun onMouseInput(mask: Int, _x: Int, _y: Int) {\n        val x = max(0, _x)\n',
        '    fun onMouseInput(mask: Int, _x: Int, _y: Int) {\n        if (handleRootMouseInput(mask, _x, _y)) return\n        val x = max(0, _x)\n',
        "mouse input routing",
    )
    source = replace_once(
        source,
        '    fun onTouchInput(mask: Int, _x: Int, _y: Int) {\n        when (mask) {\n',
        '    fun onTouchInput(mask: Int, _x: Int, _y: Int) {\n        if (handleRootTouchInput(mask, _x, _y)) return\n        when (mask) {\n',
        "touch input routing",
    )
    key_anchor = '''        ke?.let { event ->
            if (tryHandleVolumeKeyEvent(event)) {
                return
            } else if (tryHandlePowerKeyEvent(event)) {
                return
            }
        }

        if (Build.VERSION.SDK_INT >= 33) {
'''
    key_new = '''        ke?.let { event ->
            if (tryHandleVolumeKeyEvent(event)) {
                return
            } else if (tryHandlePowerKeyEvent(event)) {
                return
            }
        }

        if (dispatchRootKeyEvent(keyEvent, ke, textToCommit)) return

        if (Build.VERSION.SDK_INT >= 33) {
'''
    source = replace_once(source, key_anchor, key_new, "root keyboard routing")
    source = replace_once(
        source,
        '    override fun onAccessibilityEvent(event: AccessibilityEvent) {\n    }\n',
        '    override fun onAccessibilityEvent(event: AccessibilityEvent) {\n        if (event.eventType == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED ||\n            event.eventType == AccessibilityEvent.TYPE_WINDOWS_CHANGED) {\n            activeWindowPackageName = event.packageName?.toString()\n        }\n    }\n',
        "track active window package",
    )
    source = replace_once(
        source,
        '        ctx = this\n        notifyInputState()\n',
        '        ctx = this\n        activeWindowPackageName = try { getRootInActiveWindow()?.packageName?.toString() } catch (_: Exception) { null }\n        probeRootInput()\n        notifyInputState()\n',
        "root probe on service connection",
    )
    target.write_text(source, encoding="utf-8")
    print(f"Patched {target}")
    print("Root route is used only for SystemUI/Settings/permission/keyboard windows when `su -c id -u` returns 0; Accessibility remains the fallback elsewhere.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
