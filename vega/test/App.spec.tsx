import * as React from 'react';
import {act, fireEvent, render, screen} from '@testing-library/react-native';
import {App} from '../src/App';
import {COCKPIT_URL, hostOf} from '../src/cockpitUrl';
import {BACK_FROM_APP, HOST_BOOTSTRAP} from '../src/hostBridge';
import {CONNECT_TIMEOUT_MS} from '../src/shell';
import {BOARD} from '../src/theme';

// The WebView as a host element, with the two ref methods the shell calls. Each
// mount is counted, so a test can tell a fresh WebView from a re-render.
const mockWebMethods = {injectJavaScript: jest.fn(), goBack: jest.fn()};
const mockWebMounted = jest.fn();
jest.mock('@amazon-devices/webview', () => {
  const MockReact = require('react');
  return {
    WebView: MockReact.forwardRef((props: object, ref: unknown) => {
      MockReact.useImperativeHandle(ref, () => mockWebMethods);
      MockReact.useEffect(() => {
        mockWebMounted();
      }, []);
      return MockReact.createElement('WebView', props);
    }),
  };
});

// react-native resolves to @amazon-devices/react-native-kepler (jest.config.json
// moduleNameMapper), so this replaces exactly what the app imports from it.
// BackHandler keeps Vega's rules (BackHandler.kepler.js): the newest listener
// runs first, the first that returns true ends the walk, and when none does
// the app exits.
const mockBackListeners: Array<() => boolean | null | undefined> = [];
jest.mock('@amazon-devices/react-native-kepler', () => {
  const flatten = (style: unknown): unknown =>
    Array.isArray(style) ? Object.assign({}, ...style.map(flatten)) : style;
  return {
    ActivityIndicator: 'ActivityIndicator',
    BackHandler: {
      addEventListener: jest.fn((_name: string, listener: () => boolean) => {
        mockBackListeners.push(listener);
        return {
          remove: () => {
            const index = mockBackListeners.indexOf(listener);
            if (index !== -1) {
              mockBackListeners.splice(index, 1);
            }
          },
        };
      }),
      exitApp: jest.fn(),
    },
    Image: 'Image',
    Pressable: 'Pressable',
    StyleSheet: {create: (styles: unknown) => styles, flatten},
    Text: 'Text',
    View: 'View',
  };
});

const {BackHandler, StyleSheet} = jest.requireMock('@amazon-devices/react-native-kepler') as {
  BackHandler: {exitApp: jest.Mock};
  StyleSheet: {flatten: (style: unknown) => Record<string, unknown>};
};

/** One press of the remote's BACK, delivered the way Vega's BackHandler does. */
function pressBack() {
  act(() => {
    for (let i = mockBackListeners.length - 1; i >= 0; i--) {
      if (mockBackListeners[i]()) {
        return;
      }
    }
    BackHandler.exitApp();
  });
}

function webViews() {
  return screen.UNSAFE_root.findAll(node => (node.type as unknown) === 'WebView');
}

/** The WebView's props, for a screen that must be showing it. */
function webView() {
  const found = webViews();
  if (found.length !== 1) {
    throw new Error(`expected one WebView on screen, found ${found.length}`);
  }
  return found[0].props;
}

function focusables() {
  return screen.UNSAFE_root.findAll(
    node => (node.type as unknown) === 'Pressable' || node.props.focusable === true,
  );
}

const loaded = (canGoBack = false) => ({nativeEvent: {url: COCKPIT_URL, canGoBack}});

function failBeforeLoad(description = 'net::ERR_NAME_NOT_RESOLVED', code = -2) {
  act(() => {
    webView().onError({nativeEvent: {code, description}});
  });
}

describe('App', () => {
  let info: jest.SpyInstance;
  let warn: jest.SpyInstance;

  beforeEach(() => {
    jest.useFakeTimers();
    mockBackListeners.length = 0;
    mockWebMounted.mockClear();
    mockWebMethods.injectJavaScript.mockClear();
    mockWebMethods.goBack.mockClear();
    BackHandler.exitApp.mockClear();
    info = jest.spyOn(console, 'info').mockImplementation(() => {});
    warn = jest.spyOn(console, 'warn').mockImplementation(() => {});
  });

  afterEach(() => {
    jest.useRealTimers();
    info.mockRestore();
    warn.mockRestore();
  });

  it('shows the native launch view while the board loads underneath', () => {
    render(<App />);
    expect(screen.getByTestId('launch-view')).toBeTruthy();
    expect(screen.getByText('MERCURY')).toBeTruthy();
    expect(screen.getByText('Connecting to the incident board')).toBeTruthy();
    const props = webView();
    expect(props.source).toEqual({uri: COCKPIT_URL});
    expect(props.injectedJavaScriptBeforeContentLoaded).toBe(HOST_BOOTSTRAP);
    expect(props.allowSystemKeyEvents).toBe(false);
    expect(props.style).toEqual(expect.objectContaining({backgroundColor: BOARD.ground}));
  });

  it('leaves focus to the board: the WebView takes it, the launch view offers none', () => {
    render(<App />);
    expect(webView().hasTVPreferredFocus).toBe(true);
    expect(focusables()).toHaveLength(0);
    act(() => {
      webView().onLoad(loaded());
    });
    expect(screen.queryByTestId('launch-view')).toBeNull();
    expect(webView().hasTVPreferredFocus).toBe(true);
    expect(focusables()).toHaveLength(0);
    // The same WebView, not a second load: the launch view only lifted.
    expect(mockWebMounted).toHaveBeenCalledTimes(1);
    expect(info).toHaveBeenCalledWith(`[MercuryCockpit] journey:page_loaded:${COCKPIT_URL}`);
  });

  it('exits on BACK while the launch view is up', () => {
    render(<App />);
    pressBack();
    expect(BackHandler.exitApp).toHaveBeenCalledTimes(1);
    expect(mockWebMethods.injectJavaScript).not.toHaveBeenCalled();
  });

  it('shows the offline view, naming the host, when the board fails before its first load', () => {
    render(<App />);
    failBeforeLoad();
    expect(webViews()).toHaveLength(0);
    expect(screen.queryByTestId('launch-view')).toBeNull();
    expect(screen.getByText('Cannot reach the incident board')).toBeTruthy();
    expect(screen.getByText(`Tried ${hostOf(COCKPIT_URL)}`)).toBeTruthy();
    expect(screen.getByText('Reported: net::ERR_NAME_NOT_RESOLVED (code -2)')).toBeTruthy();
    expect(screen.getByTestId('retry').props.hasTVPreferredFocus).toBe(true);
    expect(focusables().map(node => node.props.testID)).toEqual(['retry']);
  });

  it('draws the amber focus ring on Try again only while it has focus', () => {
    render(<App />);
    failBeforeLoad();
    const ring = () => StyleSheet.flatten(screen.getByTestId('retry').props.style);
    expect(ring().borderColor).not.toBe(BOARD.amber);
    fireEvent(screen.getByTestId('retry'), 'focus');
    expect(ring().borderColor).toBe(BOARD.amber);
    expect(ring().borderWidth).toBe(4);
    fireEvent(screen.getByTestId('retry'), 'blur');
    expect(ring().borderColor).not.toBe(BOARD.amber);
  });

  it('exits on BACK from the offline view', () => {
    render(<App />);
    failBeforeLoad();
    pressBack();
    expect(BackHandler.exitApp).toHaveBeenCalledTimes(1);
  });

  it('retries with a fresh WebView on Select, and the board loads the second time', () => {
    render(<App />);
    const first = webView();
    failBeforeLoad();
    // On the TV, Select on the focused button is a press.
    fireEvent.press(screen.getByText('Try again'));
    expect(screen.getByTestId('launch-view')).toBeTruthy();
    expect(mockWebMounted).toHaveBeenCalledTimes(2);
    // A late event from the replaced WebView changes nothing.
    act(() => {
      first.onLoad(loaded());
    });
    expect(screen.getByTestId('launch-view')).toBeTruthy();
    act(() => {
      webView().onLoad(loaded());
    });
    expect(screen.queryByTestId('launch-view')).toBeNull();
    expect(screen.queryByTestId('offline-view')).toBeNull();
    expect(webView().source).toEqual({uri: COCKPIT_URL});
  });

  it('keeps a loaded board when a later sub-resource fails', () => {
    render(<App />);
    act(() => {
      webView().onLoad(loaded());
    });
    act(() => {
      webView().onError({nativeEvent: {code: -6, description: 'sub-resource failed'}});
    });
    expect(webViews()).toHaveLength(1);
    expect(screen.queryByTestId('offline-view')).toBeNull();
  });

  it('treats a main-frame HTTP error as offline and a sub-resource one as noise', () => {
    render(<App />);
    act(() => {
      webView().onHttpError({nativeEvent: {statusCode: 404, url: `${COCKPIT_URL}favicon.ico`, isMainFrame: false}});
    });
    expect(screen.getByTestId('launch-view')).toBeTruthy();
    act(() => {
      webView().onHttpError({nativeEvent: {statusCode: 502, url: COCKPIT_URL, isMainFrame: true}});
    });
    expect(screen.getByText('Reported: HTTP 502')).toBeTruthy();
  });

  it('gives up after the connect timeout, and not once the board has loaded', () => {
    render(<App />);
    act(() => {
      jest.advanceTimersByTime(CONNECT_TIMEOUT_MS - 1);
    });
    expect(screen.getByTestId('launch-view')).toBeTruthy();
    act(() => {
      jest.advanceTimersByTime(1);
    });
    expect(screen.getByText(`Reported: no answer in ${CONNECT_TIMEOUT_MS / 1000} s`)).toBeTruthy();

    fireEvent.press(screen.getByText('Try again'));
    act(() => {
      webView().onLoad(loaded());
    });
    act(() => {
      jest.advanceTimersByTime(CONNECT_TIMEOUT_MS * 2);
    });
    expect(screen.queryByTestId('offline-view')).toBeNull();
  });

  it('asks the page first on BACK in the board', () => {
    render(<App />);
    act(() => {
      webView().onLoad(loaded());
    });
    pressBack();
    expect(mockWebMethods.injectJavaScript).toHaveBeenCalledWith(BACK_FROM_APP);
    expect(BackHandler.exitApp).not.toHaveBeenCalled();
  });

  it('exits when the page reports a BACK it did not use and there is no history', () => {
    render(<App />);
    act(() => {
      webView().onLoad(loaded(false));
    });
    act(() => {
      webView().onMessage({nativeEvent: {data: '{"type":"journey","event":"x"}'}});
    });
    expect(BackHandler.exitApp).not.toHaveBeenCalled();
    act(() => {
      webView().onMessage({nativeEvent: {data: '{"type":"back_unhandled"}'}});
    });
    expect(BackHandler.exitApp).toHaveBeenCalledTimes(1);
    expect(mockWebMethods.goBack).not.toHaveBeenCalled();
  });

  it('goes back in history before exiting when the WebView can', () => {
    render(<App />);
    act(() => {
      webView().onLoad(loaded(true));
    });
    act(() => {
      webView().onMessage({nativeEvent: {data: '{"type":"back_unhandled"}'}});
    });
    expect(mockWebMethods.goBack).toHaveBeenCalledTimes(1);
    expect(BackHandler.exitApp).not.toHaveBeenCalled();
  });

  it('logs journey events with the Kotlin bounds', () => {
    render(<App />);
    act(() => {
      webView().onMessage({
        nativeEvent: {data: JSON.stringify({type: 'journey', event: 'what changed', detail: 'a\nb'})},
      });
    });
    expect(info).toHaveBeenCalledWith('[MercuryCockpit] journey:what_changed:a b');
  });
});
