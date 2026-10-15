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
 *    move twice). The bootstrap adds no key listener of its own, so Escape and
 *    Backspace also reach firetv_nav.js exactly as in a browser.
 *  - The remote's BACK never reaches the page as a key: the WebView keeps
 *    allowSystemKeyEvents false, so BACK goes to the app's BackHandler, and on
 *    the board the app injects BACK_FROM_APP. That runs window.mercuryVegaBack,
 *    which works like MainActivity.handleBack asking the page:
 *      1. A focused text field (INPUT of a text type, TEXTAREA,
 *         contentEditable) keeps BACK: the field loses focus and nothing else
 *         happens, so BACK never closes a panel or the app under a typist.
 *      2. The page closes what is open (window.navigateDpad('BACK')).
 *      In both cases the page posts back_handled.
 *      3. Otherwise the page posts back_unhandled. The app then goes back in
 *         history when the WebView reports canGoBack, and exits when it does
 *         not. history.length cannot make that call: it counts forward
 *         entries too, so a page could keep going "back" from its first entry.
 *    Every press gets one answer. If none comes within BACK_ANSWER_TIMEOUT_MS
 *    (a hung page, a page without the bootstrap or without the bridge), the
 *    app acts as if the page posted back_unhandled, so BACK can always close
 *    the app from the remote.
 */
export const TAG = 'MercuryCockpit';
export const HOST_NAME = 'mercury-vega-webview';
export const APP_VERSION = '1.0.0';

/**
 * How long the app waits for the page to answer a BACK press before it goes
 * back in history or exits on its own. ESTIMATE: no Vega device has timed the
 * injectJavaScript and postMessage round trip yet. It errs long, because an
 * answer that comes after it is ignored, and the app has already gone back or
 * exited by then, which is worse than a dead page holding BACK for 1.5 s.
 */
export const BACK_ANSWER_TIMEOUT_MS = 1500;

export type HostMessage =
  | {type: 'journey'; event: string; detail: string}
  | {type: 'back_handled'}
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
  var TEXT_INPUT_TYPES = /^(text|password|search|email|url|tel|number)$/i;
  function isTextField(node) {
    if (!node) { return false; }
    if (node.isContentEditable === true || node.tagName === 'TEXTAREA') { return true; }
    return node.tagName === 'INPUT' && TEXT_INPUT_TYPES.test(node.type || 'text');
  }
  window.mercuryVegaBack = function () {
    var active = window.document ? window.document.activeElement : null;
    if (isTextField(active) && typeof active.blur === 'function') {
      active.blur();
      send({ type: 'back_handled' });
      return;
    }
    if (typeof window.navigateDpad === 'function' && window.navigateDpad('BACK') === true) {
      send({ type: 'back_handled' });
      return;
    }
    send({ type: 'back_unhandled' });
  };
})();
true;`;

/**
 * What the app injects for a BACK press on the board. A page without the
 * bootstrap (it runs on every navigation, so this is a safety net) is treated
 * as having nothing open.
 */
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
  if (record.type === 'back_handled' || record.type === 'back_unhandled') {
    return {type: record.type};
  }
  if (record.type === 'journey' && typeof record.event === 'string') {
    const detail = typeof record.detail === 'string' ? record.detail : '';
    return {type: 'journey', event: record.event, detail};
  }
  return null;
}
