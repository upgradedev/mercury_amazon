package io.github.upgradedev.mercury.wallboard

/** Document lifecycle, independent of Android callbacks and view state. */
class CockpitLoadState(private val cockpitUrl: String) {
    var pageLoaded = false
        private set
    var offline = false
        private set

    fun beginLoad() {
        pageLoaded = false
        offline = false
    }

    /** Only main-document failures replace the cockpit; subresources stay local. */
    fun fail(isMainFrame: Boolean, statusCode: Int? = null): Boolean {
        if (!isMainFrame || (statusCode != null && statusCode < 400)) return false
        pageLoaded = false
        offline = true
        return true
    }

    fun finishLoad(): Boolean {
        if (offline) return false
        pageLoaded = true
        return true
    }

    /** Retry never accepts a new target from JavaScript or the failed document. */
    fun retry(): String {
        beginLoad()
        return cockpitUrl
    }
}
