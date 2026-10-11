/**
 * The Mercury host contract on Vega OS.
 *
 * On Fire OS, MainActivity hands the page a Java object named MercuryHost
 * through addJavascriptInterface and asks the page about every remote key
 * through evaluateJavascript. Vega WebView has neither call. Its bridge is
 * window.ReactNativeWebView.postMessage (page to app, one string argument) and
 * injectJavaScript (app to page). HOST_BOOTSTRAP rebuilds the same MercuryHost
 * surface on top of postMessage, so docs/index.html and docs/firetv_nav.js run
 * unchanged on both platforms. index.html turns on its TV layout (the tv-host
 * class) when window.MercuryHost exists, and the bootstrap defines it before
 * the page's own scripts run.
 *
 * Key policy:
 *  - Arrows and Enter stay with the page. docs/firetv_nav.js already calls
 *    preventDefault on them, which is how a page turns off the WebView's
 *    built-in spatial navigation, so the app never forwards them (focus would
 *    move twice).
 *  - BACK reaches the page as key "GoBack", keyCode 27, because the WebView sets
 *    allowSystemKeyEvents. firetv_nav.js listens for Backspace and Escape only,
 *    so a capture listener handles GoBack first. The order matches
 *    MainActivity.handleBack: the page (window.navigateDpad('BACK')), then
 *    history, then the platform, which the app reaches when the page posts
 *    back_unhandled.
 *  - If the platform hands BACK to the app's BackHandler instead, the app
 *    injects BACK_FROM_APP, which runs the same routine. A 300 ms guard stops
 *    one press from being handled twice if both paths fire.
 */
export const TAG = 'MercuryCockpit';
export const HOST_NAME = 'mercury-vega-webview';
export const APP_VERSION = '1.0.0';

export type HostMessage =
  | {type: 'journey'; event: string; detail: string}
  | {type: 'back_unhandled'};

export const HOST_BOOTSTRAP = `(function () {
  if (typeof window.mercuryVegaBack === 'function') { return; }
  var queue = [];
  var attempts = 0;
  var scheduled = false;
  function bridge() {
    var candidate = window.ReactNativeWebView;
    return candidate && typeof candidate.postMessage === 'function' ? candidate : null;
  }
  function flush() {
    scheduled = false;
    var target = bridge();
    if (target) {
      while (queue.length) { target.postMessage(queue.shift()); }
      return;
    }
    if (queue.length && attempts < 50) {
      attempts += 1;
      scheduled = true;
      setTimeout(flush, 100);
    }
  }
  function send(payload) {
    queue.push(JSON.stringify(payload));
    if (!scheduled) { flush(); }
  }
  if (!window.MercuryHost) {
    window.MercuryHost = {
      isFireTvHost: function () { return true; },
      hostName: function () { return '${HOST_NAME}'; },
      appVersion: function () { return '${APP_VERSION}'; },
      reportJourney: function (event, detail) {
        send({ type: 'journey', event: String(event), detail: String(detail || '') });
      }
    };
  }
  var lastBack = 0;
  window.mercuryVegaBack = function () {
    var now = Date.now();
    if (now - lastBack < 300) { return; }
    lastBack = now;
    if (typeof window.navigateDpad === 'function' && window.navigateDpad('BACK') === true) { return; }
    if (window.history && window.history.length > 1) { window.history.back(); return; }
    send({ type: 'back_unhandled' });
  };
  function isBack(event) {
    return event.key === 'GoBack' || event.keyCode === 27;
  }
  window.addEventListener('keydown', function (event) {
    if (!isBack(event)) { return; }
    event.preventDefault();
    event.stopImmediatePropagation();
    if (!event.repeat) { window.mercuryVegaBack(); }
  }, true);
  window.addEventListener('keyup', function (event) {
    if (!isBack(event)) { return; }
    event.preventDefault();
    event.stopImmediatePropagation();
  }, true);
})();
true;`;

/** What the app injects when BACK reaches its BackHandler instead of the page. */
export const BACK_FROM_APP = `(function () {
  if (typeof window.mercuryVegaBack === 'function') { window.mercuryVegaBack(); return; }
  if (window.ReactNativeWebView) { window.ReactNativeWebView.postMessage('{"type":"back_unhandled"}'); }
})();
true;`;

/** Same bounds as MainActivity.MercuryHost.reportJourney. */
export function sanitizeEvent(event: string): string {
  return event.slice(0, 64).replace(/[^A-Za-z0-9_.:-]/g, '_');
}

export function sanitizeDetail(detail: string): string {
  return detail.slice(0, 256).replace(/[\r\n]/g, ' ');
}

export function journeyLine(event: string, detail: string): string {
  return `journey:${sanitizeEvent(event)}:${sanitizeDetail(detail)}`;
}

/** Parse one postMessage string. Anything unexpected is dropped, not trusted. */
export function parseHostMessage(data: unknown): HostMessage | null {
  if (typeof data !== 'string' || data.length > 4096) {
    return null;
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(data);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== 'object') {
    return null;
  }
  const record = parsed as Record<string, unknown>;
  if (record.type === 'back_unhandled') {
    return {type: 'back_unhandled'};
  }
  if (record.type === 'journey' && typeof record.event === 'string') {
    const detail = typeof record.detail === 'string' ? record.detail : '';
    return {type: 'journey', event: record.event, detail};
  }
  return null;
}
