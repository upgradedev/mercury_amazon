package com.amazon.mercury.wallboard

/**
 * Decides which Mercury cockpit the TV should load.
 *
 * Precedence, highest first:
 *  1. a `COCKPIT_URL` string extra on the launching intent, which is how
 *     `adb shell am start --es COCKPIT_URL http://<host>:8002/` points a device
 *     at a laptop running the server;
 *  2. the URL compiled into the build via `MERCURY_COCKPIT_URL`;
 *  3. the built-in default.
 *
 * A candidate is used only when it is an absolute http or https URL. Anything
 * else falls through to the next source rather than being loaded, so a malformed
 * or hostile extra cannot make the WebView open a `file://` or `javascript:` URL.
 */
object CockpitUrlResolver {

    const val EXTRA_COCKPIT_URL = "COCKPIT_URL"
    const val DEFAULT_URL = "https://leol25sezuvokpankox5cvjopm0gtvfa.lambda-url.eu-west-1.on.aws/"

    private val ALLOWED_SCHEMES = listOf("http://", "https://")

    /** True when [candidate] is an absolute http(s) URL with a host after the scheme. */
    fun isAcceptable(candidate: String?): Boolean {
        if (candidate.isNullOrBlank()) return false
        val trimmed = candidate.trim()
        val scheme = ALLOWED_SCHEMES.firstOrNull { trimmed.lowercase().startsWith(it) } ?: return false
        val remainder = trimmed.substring(scheme.length)
        if (remainder.isBlank()) return false
        // Reject embedded whitespace and control characters, which have no place
        // in a URL and are a common way to smuggle a second target past a check.
        return remainder.none { it.isWhitespace() || it.code < 0x20 }
    }

    /**
     * Resolve the cockpit URL from the three sources in precedence order.
     *
     * @param intentExtra the `COCKPIT_URL` extra, or null when absent.
     * @param buildConfigUrl the URL compiled into this build.
     */
    fun resolve(intentExtra: String?, buildConfigUrl: String? = null): String {
        if (isAcceptable(intentExtra)) return intentExtra!!.trim()
        if (isAcceptable(buildConfigUrl)) return buildConfigUrl!!.trim()
        return DEFAULT_URL
    }

    /**
     * Host part of a URL, for the offline error screen. Returns the whole string
     * when it cannot be parsed, because the error screen is better with a rough
     * answer than with nothing.
     */
    fun hostOf(url: String): String {
        val scheme = ALLOWED_SCHEMES.firstOrNull { url.lowercase().startsWith(it) } ?: return url
        return url.substring(scheme.length).substringBefore('/').ifBlank { url }
    }
}
