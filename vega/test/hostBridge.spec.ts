import {
  BACK_FROM_APP,
  HOST_BOOTSTRAP,
  journeyLine,
  parseHostMessage,
  sanitizeDetail,
  sanitizeEvent,
} from '../src/hostBridge';

type FakeElement = {tagName: string; type?: string; isContentEditable?: boolean; blur?: jest.Mock};

/**
 * A window with just enough surface for the bootstrap: the bridge, the page's
 * navigateDpad, history and document.activeElement. addEventListener is
 * recorded, to show the bootstrap leaves every key to the page.
 */
function fakePage(
  options: {
    navigateDpad?: (direction: string) => boolean;
    historyLength?: number;
    active?: FakeElement | null;
    bridge?: boolean;
  } = {},
) {
  const posted: string[] = [];
  const listeners: string[] = [];
  const back = jest.fn();
  const win: Record<string, unknown> = {
    addEventListener: (type: string) => listeners.push(type),
    history: {length: options.historyLength ?? 1, back},
    navigateDpad: options.navigateDpad,
    document: {activeElement: options.active ?? null},
  };
  const attachBridge = () => {
    win.ReactNativeWebView = {postMessage: (data: string) => posted.push(data)};
  };
  if (options.bridge !== false) {
    attachBridge();
  }
  // The scripts only touch window, setTimeout and JSON. They are evaluated
  // here the way the WebView evaluates injected JavaScript.
  // eslint-disable-next-line no-new-func
  const run = (script: string) => new Function('window', script)(win);
  run(HOST_BOOTSTRAP);
  const pressBack = () => run(BACK_FROM_APP);
  return {win, posted, listeners, back, run, pressBack, attachBridge};
}

describe('HOST_BOOTSTRAP', () => {
  it('exposes the MercuryHost surface index.html checks for', () => {
    const {win} = fakePage();
    const host = win.MercuryHost as Record<string, () => unknown>;
    expect(host.isFireTvHost()).toBe(true);
    expect(host.hostName()).toBe('mercury-vega-webview');
  });

  it('carries reportJourney over postMessage', () => {
    const {win, posted} = fakePage();
    const host = win.MercuryHost as {reportJourney: (e: string, d: string) => void};
    host.reportJourney('what_changed', 'ANOMALY_ATTRIBUTED:checkout-api');
    expect(parseHostMessage(posted[0])).toEqual({
      type: 'journey',
      event: 'what_changed',
      detail: 'ANOMALY_ATTRIBUTED:checkout-api',
    });
  });

  it('holds journey events until the bridge exists, then sends them in order', () => {
    jest.useFakeTimers();
    try {
      const {win, posted, attachBridge} = fakePage({bridge: false});
      const host = win.MercuryHost as {reportJourney: (e: string, d: string) => void};
      host.reportJourney('what_changed', 'first');
      host.reportJourney('rollback_staged', 'second');
      expect(posted).toHaveLength(0);
      attachBridge();
      jest.advanceTimersByTime(100);
      expect(posted.map(data => (parseHostMessage(data) as {detail: string}).detail)).toEqual([
        'first',
        'second',
      ]);
    } finally {
      jest.useRealTimers();
    }
  });

  it('adds no key listener, so arrows, Enter, Escape and Backspace stay with firetv_nav.js', () => {
    const {listeners} = fakePage();
    expect(listeners).toEqual([]);
  });

  it('installs once even if injected twice', () => {
    const {win, posted, run, pressBack} = fakePage({navigateDpad: () => false});
    const first = win.mercuryVegaBack;
    run(HOST_BOOTSTRAP);
    expect(win.mercuryVegaBack).toBe(first);
    pressBack();
    expect(posted).toHaveLength(1);
  });
});

describe('BACK on the board (BACK_FROM_APP)', () => {
  it('lets the page close what is open, and says so', () => {
    const navigateDpad = jest.fn((direction: string) => direction === 'BACK');
    const {posted, pressBack} = fakePage({navigateDpad});
    pressBack();
    expect(navigateDpad).toHaveBeenCalledWith('BACK');
    expect(posted.map(parseHostMessage)).toEqual([{type: 'back_handled'}]);
  });

  it('reports a BACK the page did not use, and leaves history to the app', () => {
    const {posted, back, pressBack} = fakePage({navigateDpad: () => false, historyLength: 3});
    pressBack();
    expect(back).not.toHaveBeenCalled();
    expect(posted.map(parseHostMessage)).toEqual([{type: 'back_unhandled'}]);
  });

  it('answers every press: two quick presses are two answers', () => {
    const {posted, pressBack} = fakePage({navigateDpad: () => false});
    pressBack();
    pressBack();
    expect(posted).toHaveLength(2);
  });

  it('takes a focused text field out of focus, does nothing else, and says so', () => {
    const fields: FakeElement[] = [
      {tagName: 'INPUT', type: 'text'},
      {tagName: 'INPUT', type: 'password'},
      {tagName: 'TEXTAREA'},
      {tagName: 'DIV', isContentEditable: true},
    ];
    for (const field of fields) {
      field.blur = jest.fn();
      const navigateDpad = jest.fn(() => false);
      const {posted, pressBack} = fakePage({navigateDpad, active: field});
      pressBack();
      expect(field.blur).toHaveBeenCalledTimes(1);
      expect(navigateDpad).not.toHaveBeenCalled();
      expect(posted.map(parseHostMessage)).toEqual([{type: 'back_handled'}]);
    }
  });

  it('treats a focused button or checkbox as the page, not as a text field', () => {
    for (const active of [{tagName: 'BUTTON'}, {tagName: 'INPUT', type: 'checkbox'}]) {
      const blur = jest.fn();
      const navigateDpad = jest.fn(() => false);
      const {posted, pressBack} = fakePage({navigateDpad, active: {...active, blur}});
      pressBack();
      expect(blur).not.toHaveBeenCalled();
      expect(navigateDpad).toHaveBeenCalledWith('BACK');
      expect(posted.map(parseHostMessage)).toEqual([{type: 'back_unhandled'}]);
    }
  });

  it('reaches the app even on a page without the bootstrap', () => {
    const posted: string[] = [];
    const win = {ReactNativeWebView: {postMessage: (data: string) => posted.push(data)}};
    // eslint-disable-next-line no-new-func
    new Function('window', BACK_FROM_APP)(win);
    expect(posted.map(parseHostMessage)).toEqual([{type: 'back_unhandled'}]);
  });
});

describe('journey sanitising', () => {
  it('matches the Kotlin bounds', () => {
    expect(sanitizeEvent('a b/c')).toBe('a_b_c');
    expect(sanitizeEvent('x'.repeat(80))).toHaveLength(64);
    expect(sanitizeDetail('y'.repeat(300))).toHaveLength(256);
    expect(journeyLine('ok', 'line1\nline2\r')).toBe('journey:ok:line1 line2 ');
    expect(journeyLine('rollback_confirmed', 'RECORDED_ONLY:DPAD_RECORD_ONLY_DEMO')).toBe(
      'journey:rollback_confirmed:RECORDED_ONLY:DPAD_RECORD_ONLY_DEMO',
    );
  });

  it('reads both BACK answers and keeps nothing else from them', () => {
    expect(parseHostMessage(JSON.stringify({type: 'back_handled', extra: 'x'}))).toEqual({type: 'back_handled'});
    expect(parseHostMessage('{"type":"back_unhandled"}')).toEqual({type: 'back_unhandled'});
  });

  it('drops anything that is not a host message', () => {
    expect(parseHostMessage('not json')).toBeNull();
    expect(parseHostMessage(JSON.stringify({type: 'exec'}))).toBeNull();
    expect(parseHostMessage(JSON.stringify({type: 'journey'}))).toBeNull();
    expect(parseHostMessage(42)).toBeNull();
    expect(parseHostMessage('x'.repeat(5000))).toBeNull();
  });
});
