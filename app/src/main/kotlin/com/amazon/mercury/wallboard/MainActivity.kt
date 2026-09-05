package com.amazon.mercury.wallboard

import android.annotation.SuppressLint
import android.app.Activity
import android.os.Bundle
import android.util.Log
import android.view.KeyEvent
import android.view.ViewGroup
import android.webkit.JavascriptInterface
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient

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
    private var pageLoaded = false

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
    }

    @SuppressLint("SetJavaScriptEnabled", "AddJavascriptInterface")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        cockpitUrl = CockpitUrlResolver.resolve(
            intentExtra = intent?.getStringExtra(CockpitUrlResolver.EXTRA_COCKPIT_URL),
            buildConfigUrl = BuildConfig.MERCURY_COCKPIT_URL,
        )
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
        setContentView(webView)
        webView.loadUrl(cockpitUrl)
    }

    private inner class CockpitWebViewClient : WebViewClient() {
        override fun onPageFinished(view: WebView?, url: String?) {
            pageLoaded = true
        }

        override fun onReceivedError(
            view: WebView?,
            request: WebResourceRequest?,
            error: WebResourceError?,
        ) {
            // Only replace the screen when the main document failed. A failed
            // sub-resource should not blank a working cockpit.
            if (request?.isForMainFrame != true) return
            pageLoaded = false
            val description = error?.description?.toString() ?: "unknown error"
            Log.w(TAG, "Cockpit failed to load: $description")
            view?.loadDataWithBaseURL(null, offlineHtml(description), "text/html", "utf-8", null)
        }
    }

    /**
     * The screen shown when the cockpit cannot be reached. It states the address
     * that failed and how to fix it, because a blank screen on a TV in a war room
     * is worse than an error with instructions.
     */
    private fun offlineHtml(reason: String): String {
        val host = CockpitUrlResolver.hostOf(cockpitUrl)
        return """
            <html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head>
            <body style="background:#060913;color:#f8fafc;font-family:sans-serif;padding:6vh 8vw;">
              <h1 style="color:#8b5cf6;font-size:5vh;">Mercury cockpit unreachable</h1>
              <p style="font-size:3vh;line-height:1.5;">
                This Fire TV could not load <code>${escape(cockpitUrl)}</code>.
              </p>
              <p style="font-size:2.4vh;color:#94a3b8;line-height:1.6;">
                Reported: ${escape(reason)}<br><br>
                Start the Mercury server, then relaunch pointing at it:<br>
                <code style="color:#38bdf8;">adb shell am start -n $packageName/.MainActivity
                --es COCKPIT_URL http://$host:8002/</code>
              </p>
            </body></html>
        """.trimIndent()
    }

    private fun escape(value: String): String = value
        .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {
        val direction = DpadBridge.directionFor(keyCode)
        if (direction == null || !pageLoaded) return super.onKeyDown(keyCode, event)

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
