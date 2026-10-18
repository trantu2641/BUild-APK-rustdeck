
#!/usr/bin/env python3
"""RustDesk Android Root Input V3.

Routes mouse, touch gestures and supported key input through Android's
root input command without filtering by active application/window package.
Falls back to RustDesk's original Accessibility path if root is unavailable.
"""

from pathlib import Path
import sys

RELATIVE = Path(
    "flutter/android/app/src/main/kotlin/com/carriez/flutter_hbb/InputService.kt"
)

MARKER = "// ROOT_INPUT_PATCH_V3"

HELPERS = r'''    // ROOT_INPUT_PATCH_V3

    private val rootInputExecutor = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "rustdesk-root-input").apply { isDaemon = true }
    }

    @Volatile
    private var rootInputReady = false

    private var rootPointerDown = false
    private var rootGestureMoved = false
    private var rootGestureStartX = 0
    private var rootGestureStartY = 0
    private var rootGestureStartAt = 0L

    /**
     * Check that Magisk/su actually grants UID 0.
     * No application-name or window-name filtering is performed.
     */
    private fun probeRootInput() {
        rootInputExecutor.execute {
            var process: Process? = null

            try {
                process = ProcessBuilder("su", "-c", "id -u")
                    .redirectErrorStream(true)
                    .start()

                if (!process.waitFor(30, TimeUnit.SECONDS)) {
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

    private fun shellQuote(value: String): String {
        return "'" + value.replace("'", "'\\''") + "'"
    }

    /**
     * Send an Android input command as root.
     * The queue preserves command order across down/up and key events.
     */
    private fun enqueueRootInput(vararg args: String) {
        if (!rootInputReady || args.isEmpty()) {
            Log.w(logTag, "Root input skipped: root is unavailable")
            return
        }

        val command = args.joinToString(" ") { shellQuote(it) }

        rootInputExecutor.execute {
            var process: Process? = null

            try {
                process = ProcessBuilder("su", "-c", command)
                    .redirectErrorStream(true)
                    .start()

                if (!process.waitFor(5, TimeUnit.SECONDS)) {
                    process.destroyForcibly()
                    Log.e(logTag, "Root command timed out: ${args.firstOrNull()}")
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
                        "Root command failed; exit=${process.exitValue()}, output=$output"
                    )
                    rootInputReady = false
                } else {
                    Log.d(
                        logTag,
                        "Root command succeeded: ${args.firstOrNull()}"
                    )
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
        if (!rootPointerDown) {
            return
        }

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
                elapsed.coerceIn(80L, 3000L).toString()
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

    /**
     * Root input is global: no package allowlist and no window-name checks.
     */
    private fun handleRootMouseInput(
        mask: Int,
        rawX: Int,
        rawY: Int
    ): Boolean {
        if (!rootInputReady) {
            return false
        }

        val x = max(0, rawX) * SCREEN_INFO.scale
        val y = max(0, rawY) * SCREEN_INFO.scale

        when (mask) {
            0, LEFT_MOVE -> {
                mouseX = x
                mouseY = y
                moveRootGesture(mouseX, mouseY)
            }

            LEFT_DOWN -> {
                mouseX = x
                mouseY = y
                beginRootGesture(mouseX, mouseY)
            }

            LEFT_UP -> {
                mouseX = x
                mouseY = y
                finishRootGesture(mouseX, mouseY)
            }

            RIGHT_UP -> {
                mouseX = x
                mouseY = y

                enqueueRootInput(
                    "/system/bin/input",
                    "swipe",
                    x.toString(),
                    y.toString(),
                    x.toString(),
                    y.toString(),
                    longPressDuration.toString()
                )
            }

            BACK_UP -> {
                enqueueRootInput(
                    "/system/bin/input",
                    "keyevent",
                    "4"
                )
            }

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
                mouseX = x
                mouseY = y

                if (y >= WHEEL_STEP) {
                    enqueueRootInput(
                        "/system/bin/input",
                        "swipe",
                        x.toString(),
                        y.toString(),
                        x.toString(),
                        (y - WHEEL_STEP).toString(),
                        WHEEL_DURATION.toString()
                    )
                }
            }

            WHEEL_UP -> {
                mouseX = x
                mouseY = y

                if (y >= WHEEL_STEP) {
                    enqueueRootInput(
                        "/system/bin/input",
                        "swipe",
                        x.toString(),
                        y.toString(),
                        x.toString(),
                        (y + WHEEL_STEP).toString(),
                        WHEEL_DURATION.toString()
                    )
                }
            }

            else -> return false
        }

        return true
    }

    /**
     * RustDesk touchpad pan events are converted to root tap/swipe commands.
     */
    private fun handleRootTouchInput(
        mask: Int,
        rawX: Int,
        rawY: Int
    ): Boolean {
        if (!rootInputReady) {
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

    /**
     * Android's input text command supports ASCII text and %s for spaces.
     * For unsupported text, leave the original RustDesk keyboard path intact.
     */
    private fun rootTextArgument(text: String): String? {
        if (
            text.any {
                it.code < 0x20 ||
                it.code > 0x7e ||
                it == '%'
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
        if (!rootInputReady) {
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
            event.keyCode != KeyEventAndroid.KEYCODE_UNKNOWN &&
            (
                keyEvent.getPress() ||
                (
                    keyEvent.getDown() &&
                    event.action == KeyEventAndroid.ACTION_DOWN
                )
            )
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


def replace_once(
    source: str,
    old: str,
    new: str,
    label: str,
) -> str:
    count = source.count(old)

    if count != 1:
        raise SystemExit(
            f"Patch stopped safely: expected one anchor for {label}, "
            f"found {count}. No patched file was written."
        )

    return source.replace(old, new, 1)


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
        print("Root Input V3 is already applied.")
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
        "mouse input route",
    )

    source = replace_once(
        source,
        "    fun onTouchInput(mask: Int, _x: Int, _y: Int) {\n"
        "        when (mask) {\n",
        "    fun onTouchInput(mask: Int, _x: Int, _y: Int) {\n"
        "        if (handleRootTouchInput(mask, _x, _y)) return\n"
        "        when (mask) {\n",
        "touch input route",
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
        "keyboard input route",
    )

    source = replace_once(
        source,
        '''        ctx = this
        notifyInputState()
''',
        '''        ctx = this
        probeRootInput()
        notifyInputState()
''',
        "root check on service connection",
    )

    target.write_text(source, encoding="utf-8")

    print(f"Patched: {target}")
    print("Root Input V3 installed.")
    print("Root input no longer filters by application or window package.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
