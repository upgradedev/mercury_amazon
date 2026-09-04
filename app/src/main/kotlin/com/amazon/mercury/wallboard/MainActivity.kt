package com.amazon.mercury.wallboard

import android.annotation.SuppressLint
import android.app.Activity
import android.os.Bundle
import android.view.KeyEvent
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient

/**
 * Fire TV Leanback Activity for Mercury Engineering Cockpit.
 *
 * Hosts the 10-foot spatial navigation web interface and intercepts
 * D-Pad remote control key events for TV navigation.
 */
class MainActivity : Activity() {

    private lateinit var webView: WebView

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        webView = WebView(this).apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.cacheMode = WebSettings.LOAD_DEFAULT
            webViewClient = WebViewClient()
        }
        setContentView(webView)

        // Connect to production or local Mercury Cockpit
        val cockpitUrl = intent.getStringExtra("COCKPIT_URL")
            ?: "https://t7h6us4q0f.execute-api.eu-west-1.amazonaws.com/web"
        webView.loadUrl(cockpitUrl)
    }

    override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {
        return when (keyCode) {
            KeyEvent.KEYCODE_DPAD_UP -> {
                webView.evaluateJavascript("window.navigateDpad && window.navigateDpad('UP')", null)
                true
            }
            KeyEvent.KEYCODE_DPAD_DOWN -> {
                webView.evaluateJavascript("window.navigateDpad && window.navigateDpad('DOWN')", null)
                true
            }
            KeyEvent.KEYCODE_DPAD_LEFT -> {
                webView.evaluateJavascript("window.navigateDpad && window.navigateDpad('LEFT')", null)
                true
            }
            KeyEvent.KEYCODE_DPAD_RIGHT -> {
                webView.evaluateJavascript("window.navigateDpad && window.navigateDpad('RIGHT')", null)
                true
            }
            KeyEvent.KEYCODE_DPAD_CENTER, KeyEvent.KEYCODE_ENTER -> {
                webView.evaluateJavascript("window.navigateDpad && window.navigateDpad('SELECT')", null)
                true
            }
            KeyEvent.KEYCODE_BACK -> {
                if (webView.canGoBack()) {
                    webView.goBack()
                    true
                } else {
                    super.onKeyDown(keyCode, event)
                }
            }
            else -> super.onKeyDown(keyCode, event)
        }
    }
}
