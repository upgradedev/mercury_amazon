import * as React from 'react';
import {render} from '@testing-library/react-native';
import {App} from '../src/App';
import {COCKPIT_URL} from '../src/cockpitUrl';

jest.mock('@amazon-devices/webview', () => ({
  WebView: 'WebView',
}));

// react-native resolves to @amazon-devices/react-native-kepler (jest.config.json
// moduleNameMapper), so this replaces exactly what App imports from it.
jest.mock('@amazon-devices/react-native-kepler', () => ({
  BackHandler: {
    addEventListener: jest.fn(() => ({remove: jest.fn()})),
    exitApp: jest.fn(),
  },
  StyleSheet: {create: (styles: unknown) => styles},
  Text: 'Text',
  View: 'View',
}));

describe('App', () => {
  it('points the WebView at the cockpit with the host bridge injected', () => {
    const {UNSAFE_root} = render(<App />);
    const webViews = UNSAFE_root.findAll(node => (node.type as unknown) === 'WebView');
    expect(webViews.length).toBeGreaterThan(0);
    const props = webViews[0].props;
    expect(props.source).toEqual({uri: COCKPIT_URL});
    expect(props.allowSystemKeyEvents).toBe(true);
    expect(props.hasTVPreferredFocus).toBe(true);
    expect(props.javaScriptEnabled).toBe(true);
    expect(props.injectedJavaScriptBeforeContentLoaded).toContain('MercuryHost');
  });
});
