import {
  BACK_FROM_APP,
  HOST_BOOTSTRAP,
  journeyLine,
  parseHostMessage,
  sanitizeDetail,
  sanitizeEvent,
} from '../src/hostBridge';

type Listener = (event: Record<string, unknown>) => void;

type FakeEvent = {
  key: string;
  keyCode: number;
  target: Record<string, unknown> | null;
  repeat: boolean;
  prevented: boolean;
  stopped: boolean;
  preventDefault: () => void;
  stopImmediatePropagation: () => void;
};

/** A window with just enough surface for the bootstrap: listeners, history, the bridge. */
function fakePage(options: {navigateDpad?: (direction: string) => boolean; historyLength?: number} = {}) {
  const listeners: Record<string, Listener[]> = {};
  const posted: string[] = [];
  const back = jest.fn();
  const win: Record<string, unknown> = {
    ReactNativeWebView: {postMessage: (data: string) => posted.push(data)},
    addEventListener: (type: string, fn: Listener) => {
      (listeners[type] = listeners[type] || []).push(fn);
    },
    history: {length: options.historyLength ?? 1, back},
    navigateDpad: options.navigateDpad,
  };
  // The bootstrap only touches window, setTimeout, Date and JSON.
  const install = (script: string) => new Function('window', script)(win);
  install(HOST_BOOTSTRAP);
  const press = (key: string, keyCode: number, target: Record<string, unknown> | null = null): FakeEvent => {
    const event: FakeEvent = {
      key,
      keyCode,
      target,
      repeat: false,
      prevented: false,
      stopped: false,
      preventDefault() {
        this.prevented = true;
      },
      stopImmediatePropagation() {
        this.stopped = true;
      },
    };
    (listeners.keydown || []).forEach(fn => fn(event as unknown as Record<string, unknown>));
    return event;
  };
  return {win, posted, press, back, install};
}

describe('HOST_BOOTSTRAP', () => {
  let now = 1_000_000;
  beforeEach(() => {
    now += 10_000;
    jest.spyOn(Date, 'now').mockImplementation(() => now);
  });
  afterEach(() => jest.restoreAllMocks());

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

  it('lets the page consume GoBack', () => {
    const {posted, press} = fakePage({navigateDpad: direction => direction === 'BACK'});
    const event = press('GoBack', 27);
    expect(event.prevented).toBe(true);
    expect(event.stopped).toBe(true);
    expect(posted).toHaveLength(0);
  });

  it('goes back in history before asking the app to exit', () => {
    const {posted, press, back} = fakePage({navigateDpad: () => false, historyLength: 3});
    press('GoBack', 27);
    expect(back).toHaveBeenCalledTimes(1);
    expect(posted).toHaveLength(0);
  });

  it('reports GoBack the page and its history did not use', () => {
    const {posted, press} = fakePage({navigateDpad: () => false});
    press('GoBack', 27);
    expect(parseHostMessage(posted[0])).toEqual({type: 'back_unhandled'});
  });

  it('handles one press once when the key and the app both deliver it', () => {
    const {posted, press, install} = fakePage({navigateDpad: () => false});
    press('GoBack', 27);
    install(BACK_FROM_APP);
    expect(posted).toHaveLength(1);
  });

  it('runs the same routine when BACK reaches the app instead', () => {
    const {posted, install} = fakePage({navigateDpad: () => false});
    install(BACK_FROM_APP);
    expect(parseHostMessage(posted[0])).toEqual({type: 'back_unhandled'});
  });

  it('leaves Escape in a text field to the field', () => {
    const navigateDpad = jest.fn(() => false);
    const {posted, press} = fakePage({navigateDpad});
    for (const target of [{tagName: 'INPUT'}, {tagName: 'TEXTAREA'}, {tagName: 'DIV', isContentEditable: true}]) {
      const event = press('Escape', 27, target);
      expect(event.prevented).toBe(false);
      expect(event.stopped).toBe(false);
    }
    expect(navigateDpad).not.toHaveBeenCalled();
    expect(posted).toHaveLength(0);
  });

  it('still takes the remote BACK while a text field has focus', () => {
    const {posted, press} = fakePage({navigateDpad: () => false});
    const event = press('GoBack', 27, {tagName: 'INPUT'});
    expect(event.prevented).toBe(true);
    expect(parseHostMessage(posted[0])).toEqual({type: 'back_unhandled'});
  });

  it('takes Escape outside a text field as BACK', () => {
    const {posted, press} = fakePage({navigateDpad: () => false});
    expect(press('Escape', 27, {tagName: 'BUTTON'}).prevented).toBe(true);
    expect(parseHostMessage(posted[0])).toEqual({type: 'back_unhandled'});
  });

  it('leaves arrows and Enter to firetv_nav.js', () => {
    const {posted, press} = fakePage({navigateDpad: () => true});
    expect(press('ArrowRight', 39).prevented).toBe(false);
    expect(press('Enter', 13).prevented).toBe(false);
    expect(posted).toHaveLength(0);
  });

  it('installs once even if injected twice', () => {
    const {win, posted, press, install} = fakePage({navigateDpad: () => false});
    install(HOST_BOOTSTRAP);
    press('GoBack', 27);
    expect(posted).toHaveLength(1);
    expect(typeof win.mercuryVegaBack).toBe('function');
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

  it('drops anything that is not a host message', () => {
    expect(parseHostMessage('not json')).toBeNull();
    expect(parseHostMessage(JSON.stringify({type: 'exec'}))).toBeNull();
    expect(parseHostMessage(JSON.stringify({type: 'journey'}))).toBeNull();
    expect(parseHostMessage(42)).toBeNull();
    expect(parseHostMessage('x'.repeat(5000))).toBeNull();
  });
});
