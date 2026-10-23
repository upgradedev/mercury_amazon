package io.github.upgradedev.mercury.wallboard

import android.annotation.SuppressLint
import android.app.Activity
import android.content.res.ColorStateList
import android.graphics.Bitmap
import android.graphics.Color
import android.os.Bundle
import android.util.Log
import android.view.KeyEvent
import android.view.View
import android.view.ViewGroup
import android.webkit.JavascriptInterface
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

/**
 * Fire TV Leanback activity hosting the Mercury cockpit.
 *
 * The cockpit itself is the same page GitHub Pages serves and the same page the
 * Python server serves, so there is one implementation of the war room rather
 * than a TV copy that can drift from the web one. This activity supplies what a
 * browser cannot: the physical remote.
 *
 * Key handling is deliberately asynchronous. `evaluateJavascript` is the only way
 * to ask the page whether it consumed a key, and it answers on a callback, so
 * BACK is resolved by asking the page first and letting the platform close the
 * activity only when the page says it did not handle it.
 */
class MainActivity : Activity() {

    private lateinit var webView: WebView
    private lateinit var cockpitUrl: String
    private lateinit var loadState: CockpitLoadState
    private lateinit var root: FrameLayout
    private var offlinePanel: View? = null

    /**
     * The object the page can call back into. Exposed to JavaScript under the
     * name `MercuryHost`. Deliberately tiny: it reports the host environment and
     * nothing else, so a compromised page gains no device capability from it.
     */
    inner class MercuryHost {
        @JavascriptInterface
        fun isFireTvHost(): Boolean = true

        @JavascriptInterface
        fun hostName(): String = "mercury-firetv-leanback"

        @JavascriptInterface
        fun appVersion(): String = BuildConfig.VERSION_NAME

        /** Bounded, non-secret journey evidence consumed by the emulator smoke job. */
        @JavascriptInterface
        fun reportJourney(event: String, detail: String) {
            val safeEvent = event.take(64).replace(Regex("[^A-Za-z0-9_.:-]"), "_")
            val safeDetail = detail.take(256).replace(Regex("[\r\n]"), " ")
            Log.i(TAG, "journey:$safeEvent:$safeDetail")
        }
    }

    @SuppressLint("SetJavaScriptEnabled", "AddJavascriptInterface")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        cockpitUrl = CockpitUrlResolver.resolve(
            intentExtra = intent?.getStringExtra(CockpitUrlResolver.EXTRA_COCKPIT_URL),
            buildConfigUrl = BuildConfig.MERCURY_COCKPIT_URL,
        )
        loadState = CockpitLoadState(cockpitUrl)
        Log.i(TAG, "Loading Mercury cockpit from $cockpitUrl")

        webView = WebView(this).apply {
            layoutParams = ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT,
            )
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.cacheMode = WebSettings.LOAD_DEFAULT
            settings.mediaPlaybackRequiresUserGesture = false
            // A TV has no soft keyboard worth using and no pinch gesture.
            settings.builtInZoomControls = false
            settings.displayZoomControls = false
            // The page owns focus; the WebView must not draw its own highlight.
            isFocusableInTouchMode = true
            webViewClient = CockpitWebViewClient()
            addJavascriptInterface(MercuryHost(), "MercuryHost")
        }
        root = FrameLayout(this).apply { addView(webView) }
        setContentView(root)
        webView.loadUrl(cockpitUrl)
    }

    private inner class CockpitWebViewClient : WebViewClient() {
        override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
            if (!loadState.offline) loadState.beginLoad()
        }

        override fun onPageFinished(view: WebView?, url: String?) {
            if (!loadState.finishLoad()) return
            webView.requestFocus()
            Log.i(TAG, "journey:page_loaded:${url ?: cockpitUrl}")
        }

        override fun onReceivedError(
            view: WebView?,
            request: WebResourceRequest?,
            error: WebResourceError?,
        ) {
            // Only replace the screen when the main document failed. A failed
            // sub-resource should not blank a working cockpit.
            if (!loadState.fail(request?.isForMainFrame == true)) return
            val description = error?.description?.toString() ?: "unknown error"
            Log.w(TAG, "Cockpit failed to load: $description")
            showOffline(description)
        }

        override fun onReceivedHttpError(
            view: WebView?,
            request: WebResourceRequest?,
            response: WebResourceResponse?,
        ) {
            val status = response?.statusCode ?: return
            if (!loadState.fail(request?.isForMainFrame == true, status)) return
            showOffline("HTTP $status")
        }
    }

    /**
     * The screen shown when the cockpit cannot be reached. It states the address
     * that failed and offers native remote recovery even when no page loaded.
     * Native text views render the error as text, never as executable HTML.
     */
    private fun showOffline(reason: String) {
        offlinePanel?.let { root.removeView(it) }
        webView.visibility = View.GONE
        val content = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(40), dp(32), dp(40), dp(32))
            setBackgroundColor(Color.rgb(6, 9, 19))
            accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
        }
        fun text(value: String, size: Float): TextView = TextView(this).apply {
            this.text = value
            textSize = size
            setTextColor(Color.rgb(248, 250, 252))
            setPadding(0, 0, 0, dp(20))
        }
        content.addView(text("Mercury cockpit unreachable", 32f).apply {
            isAccessibilityHeading = true
        })
        content.addView(text("Could not load $cockpitUrl\nReported: $reason", 22f))
        content.addView(text("Check the network and Mercury server, then select Try again. Press Back to exit.", 22f))
        val retry = Button(this).apply {
            this.text = "Try again"
            textSize = 24f
            minHeight = dp(64)
            isFocusable = true
            setTextColor(Color.WHITE)
            backgroundTintList = ColorStateList(
                arrayOf(intArrayOf(android.R.attr.state_focused), intArrayOf()),
                intArrayOf(Color.rgb(37, 99, 235), Color.rgb(51, 65, 85)),
            )
            setOnClickListener { retryCockpit() }
        }
        content.addView(retry)
        val panel = ScrollView(this).apply {
            isFillViewport = true
            addView(content)
        }
        offlinePanel = panel
        root.addView(panel, FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT,
        ))
        retry.requestFocus()
    }

    private fun retryCockpit() {
        val target = loadState.retry()
        offlinePanel?.let { root.removeView(it) }
        offlinePanel = null
        webView.visibility = View.VISIBLE
        webView.requestFocus()
        webView.loadUrl(target)
    }

    private fun dp(value: Int): Int = (value * resources.displayMetrics.density).toInt()

    override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {
        val direction = DpadBridge.directionFor(keyCode)
        if (loadState.offline && direction == DpadBridge.BACK) {
            finish()
            return true
        }
        if (direction == null || !loadState.pageLoaded) return super.onKeyDown(keyCode, event)

        if (direction == DpadBridge.BACK) {
            handleBack()
            return true
        }
        webView.evaluateJavascript(DpadBridge.scriptFor(direction), null)
        return true
    }

    /**
     * BACK is the one key where the wrong answer is destructive: swallowing it
     * traps the viewer, and forwarding it blindly closes the war room mid-incident.
     * So the page is asked first, then history, then the platform.
     */
    private fun handleBack() {
        webView.evaluateJavascript(DpadBridge.scriptFor(DpadBridge.BACK)) { result ->
            if (DpadBridge.pageConsumedKey(result)) return@evaluateJavascript
            if (webView.canGoBack()) {
                webView.goBack()
            } else {
                finish()
            }
        }
    }

    override fun onDestroy() {
        webView.removeJavascriptInterface("MercuryHost")
        webView.destroy()
        super.onDestroy()
    }

    private companion object {
        const val TAG = "MercuryCockpit"
    }
}
