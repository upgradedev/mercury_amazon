package io.github.upgradedev.mercury.wallboard

import android.view.KeyEvent

/**
 * Translates Fire TV remote key codes into the direction names the cockpit page
 * understands, and builds the JavaScript that delivers them.
 *
 * Kept free of Android framework state so it can be unit tested on the JVM. The
 * only Android type it touches is the [KeyEvent] key code constants, which are
 * plain integers.
 */
object DpadBridge {

    /** Direction names accepted by `window.navigateDpad` in docs/firetv_nav.js. */
    const val UP = "UP"
    const val DOWN = "DOWN"
    const val LEFT = "LEFT"
    const val RIGHT = "RIGHT"
    const val SELECT = "SELECT"
    const val BACK = "BACK"

    /**
     * Map a remote key code to a cockpit direction, or null when the key is not
     * one the cockpit handles and the activity should let the system have it.
     *
     * Both D-pad centre and the enter keys map to SELECT, because Fire TV remotes,
     * game controllers and USB keyboards each send a different one of them.
     */
    fun directionFor(keyCode: Int): String? = when (keyCode) {
        KeyEvent.KEYCODE_DPAD_UP -> UP
        KeyEvent.KEYCODE_DPAD_DOWN -> DOWN
        KeyEvent.KEYCODE_DPAD_LEFT -> LEFT
        KeyEvent.KEYCODE_DPAD_RIGHT -> RIGHT
        KeyEvent.KEYCODE_DPAD_CENTER, KeyEvent.KEYCODE_ENTER, KeyEvent.KEYCODE_NUMPAD_ENTER -> SELECT
        KeyEvent.KEYCODE_BACK -> BACK
        else -> null
    }

    /**
     * Build the JavaScript that hands a direction to the page.
     *
     * The call is guarded so a page that has not finished loading, or a page that
     * is not the cockpit at all, returns false rather than throwing. The activity
     * reads that false and falls back to the platform's own handling, which is
     * what makes BACK still exit the app when the page does not consume it.
     */
    fun scriptFor(direction: String): String {
        require(direction in setOf(UP, DOWN, LEFT, RIGHT, SELECT, BACK)) {
            "Unsupported D-pad direction: $direction"
        }
        return "(function(){" +
            "if(typeof window.navigateDpad!=='function'){return false;}" +
            "return window.navigateDpad('$direction')===true;" +
            "})()"
    }

    /**
     * Interpret the string `evaluateJavascript` hands back. The WebView returns
     * JSON, so a boolean arrives as the literal text `true` or `false`, and a
     * failed evaluation arrives as `null`.
     */
    fun pageConsumedKey(evaluationResult: String?): Boolean = evaluationResult?.trim() == "true"
}
