
#!/usr/bin/env python3

from pathlib import Path
import sys

RELATIVE = Path(
    "flutter/android/app/src/main/kotlin/com/carriez/flutter_hbb/InputService.kt"
)

MARKER = "// ROOT_INPUT_PATCH_V2"

HELPERS = r'''    // ROOT_INPUT_PATCH_V2

    private val rootInputExecutor = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "rustdesk-root-input").apply { isDaemon = true }
    }

    @Volatile
    private var rootInputReady = false

    @Volatile
    private var activeWindowPackageName: String? = null

    private val rootInputPackages = setOf(
        "android",
        "com.android.systemui",
        "com.android.settings",
        "com.android.permissioncontroller",
        "com.google.android.permissioncontroller",
        "com.android.packageinstaller",
        "com.google.android.packageinstaller",
        "com.android.providers.settings",
        "com.miui.securitycenter",
        "com.miui.permissioncontroller",
        "com.miui.guardprovider"
    )

    private var rootPointerDown = false
    private var rootGestureMoved = false
    private var rootGestureStartX = 0
    private var rootGestureStartY = 0
    private var rootGestureStartAt = 0L

    private fun isAllowedRootInputPackage(packageName: String?): Boolean {
        if (packageName.isNullOrBlank()) return false

        return rootInputPackages.contains(packageName) ||
            packageName.endsWith(".permissioncontroller") ||
            packageName.endsWith(".packageinstaller")
    }

    private fun probeRootInput() {
        rootInputExecutor.execute {
            var process: Process? = null

            try {
                process = ProcessBuilder("su", "-c", "id -u")
                    .redirectErrorStream(true)
                    .start()

                if (!process.waitFor(15, TimeUnit.SECONDS)) {
                    process.destroyForcibly()
                    rootInputReady = false
                    Log.e(logTag, "Root input check timed out")
                    return@execute
                }

                val output = process.inputStream
                    .bufferedReader()
                    .readText()
                    .trim()

                rootInputReady = process.exitValue() == 0 && output == "0"

                Log.i(
                    logTag,
                    "Root input available=$rootInputReady; uid=$output"
                )
            } catch (e: Exception) {
                rootInputReady = false
                Log.e(logTag, "Root input check failed: ${e.message}")
            } finally {
                try {
                    process?.destroy()
                } catch (_: Exception) {
                }
            }
        }
    }

    /*
     * Find the package belonging to the currently active/focused windows.
     * Do not rely solely on AccessibilityEvent.packageName: that value can
     * describe the event source rather than the window receiving the touch.
     */
    private fun currentWindowPackages(): Set<String> {
        val result = linkedSetOf<String>()

        try {
            val root = rootInActiveWindow
            val packageName = root?.packageName?.toString()

            if (!packageName.isNullOrBlank()) {
                result.add(packageName)
            }
        } catch (e: Exception) {
            Log.w(logTag, "Cannot read active accessibility root: ${e.message}")
        }

        try {
            for (window in windows) {
                if (!window.isActive && !window.isFocused) {
                    continue
                }

                try {
                    val packageName = window.root?.packageName?.toString()

                    if (!packageName.isNullOrBlank()) {
                        result.add(packageName)
                    }
                } catch (e: Exception) {
                    Log.d(logTag, "Cannot read window root: ${e.message}")
                }
            }
        } catch (e: Exception) {
            Log.w(logTag, "Cannot enumerate accessibility windows: ${e.message}")
        }

        return result
    }

    private fun shouldUseRootForCurrentWindow(): Boolean {
        if (!rootInputReady) {
            return false
        }

        val candidates = currentWindowPackages()

        val allowedPackage = candidates.firstOrNull {
            isAllowedRootInputPackage(it)
        }

        if (allowedPackage != null) {
            activeWindowPackageName = allowedPackage
            Log.d(
                logTag,
                "Root input selected for system window: $allowedPackage"
            )
            return true
        }

        activeWindowPackageName = candidates.firstOrNull()

        Log.d(
            logTag,
            "Using normal RustDesk input; current windows=$candidates"
        )

        return false
    }

    private fun shellQuote(value: String): String {
        return "'" + value.replace("'", "'\\''") + "'"
    }

    private fun enqueueRootInput(vararg args: String) {
        if (!rootInputReady || args.isEmpty()) {
            Log.w(logTag, "Root input ignored: root is unavailable")
            return
        }

        val command = args.joinToString(" ") {
            shellQuote(it)
        }

        rootInputExecutor.execute {
            var process: Process? = null

            try {
                process = ProcessBuilder("su", "-c", command)
                    .redirectErrorStream(true)
                    .start()

                if (!process.waitFor(3, TimeUnit.SECONDS)) {
                    process.destroyForcibly()
                    Log.e(logTag, "Root input timed out: ${args.firstOrNull()}")
                    rootInputReady = false
                    return@execute
                }

                val output = process.inputStream
                    .bufferedReader()
                    .readText()
                    .trim()

                if (process.exitValue() != 0) {
                    Log.e(
                        logTag,
                        "Root input failed; exit=${process.exitValue()}, output=$output"
                    )
                    rootInputReady = false
                } else {
                    Log.d(logTag, "Root input succeeded: ${args.firstOrNull()}")
                }
            } catch (e: Exception) {
                Log.e(logTag, "Root input exception: ${e.message}")
                rootInputReady = false
            } finally {
                try {
                    process?.destroy()
                } catch (_: Exception) {
                }
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
        if (
            rootPointerDown &&
            abs(x - rootGestureStartX) + abs(y - rootGestureStartY) > 8
        ) {
            rootGestureMoved = true
        }
    }

    private fun finishRootGesture(x: Int, y: Int) {
        if (!rootPointerDown) return

        val elapsed = (
            System.currentTimeMillis() - rootGestureStartAt
        ).coerceAtLeast(1L)

        rootPointerDown = false

        if (rootGestureMoved) {
            enqueueRootInput(
                "/system/bin/input",
                "swipe",
                rootGestureStartX.toString(),
                rootGestureStartY.toString(),
                x.toString(),
                y.toString(),
                elapsed.coerceIn(80L, 2000L).toString()
            )
        } else if (elapsed >= longPressDuration) {
            enqueueRootInput(
                "/system/bin/input",
                "swipe",
                x.toString(),
                y.toString(),
                x.toString(),
                y.toString(),
                elapsed.coerceIn(longPressDuration, 3000L).toString()
            )
        } else {
            enqueueRootInput(
                "/system/bin/input",
                "tap",
                x.toString(),
                y.toString()
            )
        }
    }

    private fun handleRootMouseInput(
        mask: Int,
        rawX: Int,
        rawY: Int
    ): Boolean {
        if (!shouldUseRootForCurrentWindow()) {
            return false
        }

        mouseX = max(0, rawX) * SCREEN_INFO.scale
        mouseY = max(0, rawY) * SCREEN_INFO.scale

        when (mask) {
            0, LEFT_MOVE -> moveRootGesture(mouseX, mouseY)

            LEFT_DOWN -> beginRootGesture(mouseX, mouseY)

            LEFT_UP -> finishRootGesture(mouseX, mouseY)

            RIGHT_UP -> enqueueRootInput(
                "/system/bin/input",
                "swipe",
                mouseX.toString(),
                mouseY.toString(),
                mouseX.toString(),
                mouseY.toString(),
                longPressDuration.toString()
            )

            BACK_UP -> enqueueRootInput(
                "/system/bin/input",
                "keyevent",
                "4"
            )

            WHEEL_BUTTON_DOWN -> {
                timer.purge()

                recentActionTask = object : TimerTask() {
                    override fun run() {
                        enqueueRootInput(
                            "/system/bin/input",
                            "keyevent",
                            "187"
                        )
                        recentActionTask = null
                    }
                }

                timer.schedule(recentActionTask, LONG_TAP_DELAY)
            }

            WHEEL_BUTTON_UP -> {
                if (recentActionTask != null) {
                    recentActionTask!!.cancel()
                    recentActionTask = null

                    enqueueRootInput(
                        "/system/bin/input",
                        "keyevent",
                        "3"
                    )
                }
            }

            WHEEL_DOWN -> {
                if (mouseY >= WHEEL_STEP) {
                    enqueueRootInput(
                        "/system/bin/input",
                        "swipe",
                        mouseX.toString(),
                        mouseY.toString(),
                        mouseX.toString(),
                        (mouseY - WHEEL_STEP).toString(),
                        WHEEL_DURATION.toString()
                    )
                }
            }

            WHEEL_UP -> {
                if (mouseY >= WHEEL_STEP) {
                    enqueueRootInput(
                        "/system/bin/input",
                        "swipe",
                        mouseX.toString(),
                        mouseY.toString(),
                        mouseX.toString(),
                        (mouseY + WHEEL_STEP).toString(),
                        WHEEL_DURATION.toString()
                    )
                }
            }

            else -> return false
        }

        return true
    }

    private fun handleRootTouchInput(
        mask: Int,
        rawX: Int,
        rawY: Int
    ): Boolean {
        if (!shouldUseRootForCurrentWindow()) {
            return false
        }

        when (mask) {
            TOUCH_PAN_START -> {
                mouseX = max(0, rawX) * SCREEN_INFO.scale
                mouseY = max(0, rawY) * SCREEN_INFO.scale
                beginRootGesture(mouseX, mouseY)
            }

            TOUCH_PAN_UPDATE -> {
                mouseX = max(
                    0,
                    mouseX - rawX * SCREEN_INFO.scale
                )
                mouseY = max(
                    0,
                    mouseY - rawY * SCREEN_INFO.scale
                )

                moveRootGesture(mouseX, mouseY)
            }

            TOUCH_PAN_END -> {
                finishRootGesture(mouseX, mouseY)
                mouseX = max(0, rawX) * SCREEN_INFO.scale
                mouseY = max(0, rawY) * SCREEN_INFO.scale
            }

            else -> return false
        }

        return true
    }

    private fun rootTextArgument(text: String): String? {
        if (
            text.any {
                it.code < 0x20 || it.code > 0x7e || it == '%'
            }
        ) {
            return null
        }

        return text.replace(" ", "%s")
    }

    private fun dispatchRootKeyEvent(
        keyEvent: KeyEvent,
        androidEvent: KeyEventAndroid?,
        text: String?
    ): Boolean {
        if (!shouldUseRootForCurrentWindow()) {
            return false
        }

        if (text != null) {
            val argument = rootTextArgument(text) ?: return false

            enqueueRootInput(
                "/system/bin/input",
                "text",
                argument
            )
            return true
        }

        val event = androidEvent

        if (
            event != null &&
            (
                keyEvent.getPress() ||
                (
                    keyEvent.getDown() &&
                    event.action == KeyEventAndroid.ACTION_DOWN
                )
            ) &&
            event.keyCode != KeyEventAndroid.KEYCODE_UNKNOWN
        ) {
            enqueueRootInput(
                "/system/bin/input",
                "keyevent",
                event.keyCode.toString()
            )
        }

        return true
    }
'''


def replace_once(text: str, old: str, new: str, name: str) -> str:
    count = text.count(old)

    if count != 1:
        raise SystemExit(
            f"Patch stopped safely: expected one anchor for {name}, "
            f"found {count}. No patched file was written."
        )

    return text.replace(old, new, 1)


def main() -> int:
    if len(sys.argv) != 2:
        print(
            "Usage: python3 apply_root_input_patch.py /path/to/rustdesk-source",
            file=sys.stderr,
        )
        return 2

    repo = Path(sys.argv[1]).resolve()
    target = repo / RELATIVE

    if not target.is_file():
        print(f"InputService.kt not found: {target}", file=sys.stderr)
        return 2

    source = target.read_text(encoding="utf-8")

    if MARKER in source:
        print("Root input V2 patch is already applied.")
        return 0

    source = replace_once(
        source,
        "import java.util.*\nimport java.lang.Character\n",
        (
            "import java.util.*\n"
            "import java.util.concurrent.TimeUnit\n"
            "import java.util.concurrent.Executors\n"
            "import java.lang.Character\n"
        ),
        "imports",
    )

    source = replace_once(
        source,
        '    private val logTag = "input service"\n',
        '    private val logTag = "input service"\n\n' + HELPERS,
        "root input helpers",
    )

    source = replace_once(
        source,
        "    fun onMouseInput(mask: Int, _x: Int, _y: Int) {\n"
        "        val x = max(0, _x)\n",
        "    fun onMouseInput(mask: Int, _x: Int, _y: Int) {\n"
        "        if (handleRootMouseInput(mask, _x, _y)) return\n"
        "        val x = max(0, _x)\n",
        "mouse input routing",
    )

    source = replace_once(
        source,
        "    fun onTouchInput(mask: Int, _x: Int, _y: Int) {\n"
        "        when (mask) {\n",
        "    fun onTouchInput(mask: Int, _x: Int, _y: Int) {\n"
        "        if (handleRootTouchInput(mask, _x, _y)) return\n"
        "        when (mask) {\n",
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

    key_replacement = '''        ke?.let { event ->
            if (tryHandleVolumeKeyEvent(event)) {
                return
            } else if (tryHandlePowerKeyEvent(event)) {
                return
            }
        }

        if (dispatchRootKeyEvent(keyEvent, ke, textToCommit)) return

        if (Build.VERSION.SDK_INT >= 33) {
'''

    source = replace_once(
        source,
        key_anchor,
        key_replacement,
        "keyboard routing",
    )

    source = replace_once(
        source,
        '''    override fun onAccessibilityEvent(event: AccessibilityEvent) {
    }
''',
        '''    override fun onAccessibilityEvent(event: AccessibilityEvent) {
        val eventPackage = event.packageName?.toString()

        if (
            event.eventType == AccessibilityEvent.TYPE_WINDOWS_CHANGED ||
            event.eventType == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED
        ) {
            val packages = currentWindowPackages()

            val selected = packages.firstOrNull {
                isAllowedRootInputPackage(it)
            } ?: packages.firstOrNull() ?: eventPackage

            if (!selected.isNullOrBlank()) {
                activeWindowPackageName = selected
            }

            Log.d(
                logTag,
                "Window event=${event.eventType}; " +
                    "eventPackage=$eventPackage; " +
                    "currentPackages=$packages; " +
                    "selected=$activeWindowPackageName"
            )
        }
    }
''',
        "window event handler",
    )

    source = replace_once(
        source,
        '''        val info = AccessibilityServiceInfo()
        if (Build.VERSION.SDK_INT >= 33) {
''',
        '''        val info = AccessibilityServiceInfo()

        // The service must continue receiving window changes after setServiceInfo.
        info.eventTypes =
            AccessibilityEvent.TYPE_WINDOWS_CHANGED or
            AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED
        info.feedbackType = AccessibilityServiceInfo.FEEDBACK_GENERIC
        info.notificationTimeout = 50

        if (Build.VERSION.SDK_INT >= 33) {
''',
        "accessibility event configuration",
    )

    source = replace_once(
        source,
        '''        setServiceInfo(info)
        fakeEditTextForTextStateCalculation = EditText(this)
''',
        '''        setServiceInfo(info)

        activeWindowPackageName = try {
            rootInActiveWindow?.packageName?.toString()
        } catch (_: Exception) {
            null
        }

        probeRootInput()

        fakeEditTextForTextStateCalculation = EditText(this)
''',
        "root input initialization",
    )

    target.write_text(source, encoding="utf-8")

    print(f"Patched: {target}")
    print("Applied Root Input V2 with live system-window detection.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
