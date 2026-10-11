import * as React from 'react';
import {act, render} from '@testing-library/react-native';
import {App, SPLASH_LIMIT_MS} from '../src/App';
import {COCKPIT_URL} from '../src/cockpitUrl';

jest.mock('@amazon-devices/webview', () => ({
  WebView: 'WebView',
}));

// react-native resolves to @amazon-devices/react-native-kepler (jest.config.json
// moduleNameMapper), so this replaces exactly what App imports from it.
const mockHideSplash = jest.fn();
jest.mock('@amazon-devices/react-native-kepler', () => ({
  BackHandler: {
    addEventListener: jest.fn(() => ({remove: jest.fn()})),
    exitApp: jest.fn(),
  },
  StyleSheet: {create: (styles: unknown) => styles},
  Text: 'Text',
  View: 'View',
  usePreventHideSplashScreen: jest.fn(),
  useHideSplashScreenCallback: () => mockHideSplash,
}));

const {BackHandler} = jest.requireMock('@amazon-devices/react-native-kepler') as {
  BackHandler: {exitApp: jest.Mock};
};

type Rendered = ReturnType<typeof render>;

function webViewProps(screen: Rendered) {
  const webViews = screen.UNSAFE_root.findAll(node => (node.type as unknown) === 'WebView');
  return webViews.length > 0 ? webViews[0].props : null;
}

/** The WebView's props, for a screen that must be showing it. */
function webView(screen: Rendered) {
  const props = webViewProps(screen);
  if (!props) {
    throw new Error('the WebView is not on screen');
  }
  return props;
}

function textOf(screen: Rendered): string {
  return JSON.stringify(screen.toJSON());
}

describe('App', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    mockHideSplash.mockClear();
    BackHandler.exitApp.mockClear();
  });
  afterEach(() => jest.useRealTimers());

  it('points the WebView at the cockpit with the host bridge injected', () => {
    const props = webView(render(<App />));
    expect(props.source).toEqual({uri: COCKPIT_URL});
    expect(props.allowSystemKeyEvents).toBe(true);
    expect(props.hasTVPreferredFocus).toBe(true);
    expect(props.javaScriptEnabled).toBe(true);
    expect(props.injectedJavaScriptBeforeContentLoaded).toContain('MercuryHost');
  });

  it('exits when the page reports a BACK it did not use', () => {
    const screen = render(<App />);
    act(() => {
      webView(screen).onMessage({nativeEvent: {data: '{"type":"journey","event":"x"}'}});
    });
    expect(BackHandler.exitApp).not.toHaveBeenCalled();
    act(() => {
      webView(screen).onMessage({nativeEvent: {data: '{"type":"back_unhandled"}'}});
    });
    expect(BackHandler.exitApp).toHaveBeenCalledTimes(1);
  });

  it('shows the offline screen when the cockpit fails before its first load', () => {
    const screen = render(<App />);
    expect(mockHideSplash).not.toHaveBeenCalled();
    act(() => {
      webView(screen).onError({nativeEvent: {code: -2, description: 'net::ERR_NAME_NOT_RESOLVED'}});
    });
    expect(webViewProps(screen)).toBeNull();
    expect(textOf(screen)).toContain('Mercury cockpit unreachable');
    expect(textOf(screen)).toContain('net::ERR_NAME_NOT_RESOLVED');
    // The splash must not cover the offline screen.
    expect(mockHideSplash).toHaveBeenCalledTimes(1);
  });

  it('keeps a loaded cockpit when a later sub-resource fails', () => {
    const screen = render(<App />);
    act(() => {
      webView(screen).onLoad({nativeEvent: {url: COCKPIT_URL}});
    });
    expect(mockHideSplash).toHaveBeenCalledTimes(1);
    act(() => {
      webView(screen).onError({nativeEvent: {code: -6, description: 'sub-resource failed'}});
    });
    expect(webViewProps(screen)).not.toBeNull();
    expect(textOf(screen)).not.toContain('Mercury cockpit unreachable');
    expect(mockHideSplash).toHaveBeenCalledTimes(1);
  });

  it('never holds the splash past its limit', () => {
    render(<App />);
    act(() => {
      jest.advanceTimersByTime(SPLASH_LIMIT_MS - 1);
    });
    expect(mockHideSplash).not.toHaveBeenCalled();
    act(() => {
      jest.advanceTimersByTime(1);
    });
    expect(mockHideSplash).toHaveBeenCalledTimes(1);
  });
});
