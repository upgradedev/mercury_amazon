package io.github.upgradedev.mercury.wallboard

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * JVM unit tests for cockpit URL resolution. These run under `./gradlew test`
 * with no device and no emulator.
 */
class CockpitUrlResolverTest {

    @Test
    fun `intent extra wins over the compiled default`() {
        val resolved = CockpitUrlResolver.resolve(
            intentExtra = "http://192.168.1.20:8002/",
            buildConfigUrl = "https://example.invalid/",
        )
        assertEquals("http://192.168.1.20:8002/", resolved)
    }

    @Test
    fun `build config is used when no extra is supplied`() {
        val resolved = CockpitUrlResolver.resolve(null, "https://cockpit.example/")
        assertEquals("https://cockpit.example/", resolved)
    }

    @Test
    fun `default is used when neither source supplies a usable url`() {
        assertEquals(CockpitUrlResolver.DEFAULT_URL, CockpitUrlResolver.resolve(null, null))
        assertEquals(CockpitUrlResolver.DEFAULT_URL, CockpitUrlResolver.resolve("", ""))
    }

    @Test
    fun `compiled public candidate can be launched without an adb override`() {
        val publicCandidate = "https://leol25sezuvokpankox5cvjopm0gtvfa.lambda-url.eu-west-1.on.aws/"
        assertEquals(publicCandidate, CockpitUrlResolver.resolve(null, publicCandidate))
    }

    @Test
    fun `non http schemes are refused so the webview cannot be redirected`() {
        assertFalse(CockpitUrlResolver.isAcceptable("javascript:alert(1)"))
        assertFalse(CockpitUrlResolver.isAcceptable("file:///sdcard/evil.html"))
        assertFalse(CockpitUrlResolver.isAcceptable("content://media/external"))
        assertFalse(CockpitUrlResolver.isAcceptable("ftp://example.com/"))
    }

    @Test
    fun `a hostile extra falls through to the safe default`() {
        assertEquals(
            CockpitUrlResolver.DEFAULT_URL,
            CockpitUrlResolver.resolve("javascript:fetch('http://evil')", null),
        )
    }

    @Test
    fun `a scheme with no host is refused`() {
        assertFalse(CockpitUrlResolver.isAcceptable("http://"))
        assertFalse(CockpitUrlResolver.isAcceptable("https://   "))
    }

    @Test
    fun `whitespace and control characters inside a url are refused`() {
        assertFalse(CockpitUrlResolver.isAcceptable("http://good.example/ http://evil.example"))
        assertFalse(CockpitUrlResolver.isAcceptable("http://good.example/\npath"))
    }

    @Test
    fun `scheme comparison is case insensitive`() {
        assertTrue(CockpitUrlResolver.isAcceptable("HTTP://cockpit.example/"))
        assertTrue(CockpitUrlResolver.isAcceptable("HttpS://cockpit.example/"))
    }

    @Test
    fun `surrounding whitespace is trimmed rather than rejected`() {
        assertEquals("http://cockpit.example/", CockpitUrlResolver.resolve("  http://cockpit.example/  ", null))
    }

    @Test
    fun `host extraction handles ports and paths`() {
        assertEquals("192.168.1.20:8002", CockpitUrlResolver.hostOf("http://192.168.1.20:8002/web"))
        assertEquals("cockpit.example", CockpitUrlResolver.hostOf("https://cockpit.example"))
    }
}
