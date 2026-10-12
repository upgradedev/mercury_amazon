/**
 * Vega OS host for the Mercury incident board.
 *
 * The Vega counterpart of app/src/main/kotlin/io/github/upgradedev/mercury/
 * wallboard/MainActivity.kt. The board itself is the page the Fire OS app,
 * GitHub Pages and the Lambda serve, so both Fire TV platforms show one war
 * room instead of two copies that can drift apart. What is native here:
 *
 *  - LaunchView (ShellScreens.tsx), drawn over the WebView until its first
 *    load, and OfflineView with a focusable Try again instead of a blank or
 *    white failure. shell.ts decides which one shows.
 *  - Focus: the WebView takes focus when it mounts (hasTVPreferredFocus, as
 *    Amazon's WebView guide sets it) and LaunchView has nothing focusable, so
 *    the board has the D-pad when LaunchView lifts. Try again mounts a fresh
 *    WebView, which takes focus back from the button.
 *  - BACK, through BackHandler. allowSystemKeyEvents stays false, so the page
 *    never receives the remote's BACK itself and every press comes here. On
 *    LaunchView and OfflineView it closes the app. On the board it goes to the
 *    page first (BACK_FROM_APP), then history, then the platform, which is
 *    MainActivity.handleBack's order.
 */
import {WebView} from '@amazon-devices/webview';
import type {
  WebViewErrorEvent,
  WebViewHttpErrorEvent,
  WebViewMessageEvent,
  WebViewMethods,
  WebViewNavigationEvent,
} from '@amazon-devices/webview/dist/types/WebViewTypes';
import * as React from 'react';
import {useCallback, useEffect, useReducer, useRef} from 'react';
import {BackHandler, StyleSheet, View} from 'react-native';
import {COCKPIT_URL, hostOf} from './cockpitUrl';
import {BACK_FROM_APP, HOST_BOOTSTRAP, TAG, journeyLine, parseHostMessage} from './hostBridge';
import {CONNECT_TIMEOUT_MS, INITIAL_SHELL, describeLoadError, shellReducer} from './shell';
import {LaunchView, OfflineView} from './ShellScreens';
import {BOARD} from './theme';

export const App = () => {
  const [{attempt, phase, reason}, dispatch] = useReducer(shellReducer, INITIAL_SHELL);
  const webRef = useRef<WebViewMethods>(null);
  // The WebView's own answer to "is there history?", from its last navigation
  // event: MainActivity asks webView.canGoBack() at the same point.
  const canGoBack = useRef(false);

  useEffect(() => {
    if (phase !== 'connecting') {
      return undefined;
    }
    console.info(`[${TAG}] Connecting to ${COCKPIT_URL} (attempt ${attempt})`);
    const timer = setTimeout(() => {
      console.warn(`[${TAG}] No load from ${hostOf(COCKPIT_URL)} in ${CONNECT_TIMEOUT_MS} ms`);
      dispatch({type: 'timed_out', attempt});
    }, CONNECT_TIMEOUT_MS);
    return () => clearTimeout(timer);
  }, [phase, attempt]);

  useEffect(() => {
    const subscription = BackHandler.addEventListener('hardwareBackPress', () => {
      const web = webRef.current;
      if (phase === 'board' && web) {
        web.injectJavaScript(BACK_FROM_APP);
      } else {
        // LaunchView or OfflineView: there is nothing to go back to.
        BackHandler.exitApp();
      }
      return true;
    });
    return () => subscription.remove();
  }, [phase]);

  const onMessage = useCallback((event: WebViewMessageEvent) => {
    const message = parseHostMessage(event.nativeEvent.data);
    if (!message) {
      return;
    }
    if (message.type === 'back_unhandled') {
      // The page had nothing open to close: history next, then leave.
      if (canGoBack.current && webRef.current) {
        webRef.current.goBack();
      } else {
        BackHandler.exitApp();
      }
      return;
    }
    console.info(`[${TAG}] ${journeyLine(message.event, message.detail)}`);
  }, []);

  const retry = useCallback(() => {
    console.info(`[${TAG}] Try again`);
    canGoBack.current = false;
    dispatch({type: 'retry'});
  }, []);

  return (
    <View style={styles.root}>
      {phase !== 'offline' && (
        <WebView
          key={attempt}
          ref={webRef}
          style={styles.webview}
          source={{uri: COCKPIT_URL}}
          hasTVPreferredFocus={true}
          allowSystemKeyEvents={false}
          javaScriptEnabled={true}
          domStorageEnabled={true}
          mediaPlaybackRequiresUserAction={false}
          mixedContentMode="never"
          injectedJavaScriptBeforeContentLoaded={HOST_BOOTSTRAP}
          onLoadStart={({nativeEvent}: WebViewNavigationEvent) => {
            canGoBack.current = nativeEvent.canGoBack === true;
          }}
          onLoad={({nativeEvent}: WebViewNavigationEvent) => {
            canGoBack.current = nativeEvent.canGoBack === true;
            console.info(`[${TAG}] journey:page_loaded:${nativeEvent.url || COCKPIT_URL}`);
            dispatch({type: 'loaded', attempt});
          }}
          onError={({nativeEvent}: WebViewErrorEvent) => {
            const failure = describeLoadError(nativeEvent.code, nativeEvent.description);
            console.warn(`[${TAG}] Cockpit failed to load: ${failure}`);
            dispatch({type: 'load_failed', attempt, reason: failure});
          }}
          onHttpError={({nativeEvent}: WebViewHttpErrorEvent) => {
            console.warn(
              `[${TAG}] HTTP ${nativeEvent.statusCode} at ${nativeEvent.url} (main frame: ${nativeEvent.isMainFrame})`,
            );
            if (nativeEvent.isMainFrame) {
              dispatch({type: 'main_frame_failed', attempt, reason: `HTTP ${nativeEvent.statusCode}`});
            }
          }}
          onMessage={onMessage}
          onCloseWindow={() => BackHandler.exitApp()}
        />
      )}
      {phase === 'connecting' && <LaunchView />}
      {phase === 'offline' && (
        <OfflineView host={hostOf(COCKPIT_URL)} reason={reason ?? 'unknown error'} onRetry={retry} />
      )}
    </View>
  );
};

export default App;

// flex: 1 on the container is what Vega needs for the WebView to take focus.
const styles = StyleSheet.create({
  root: {flex: 1, backgroundColor: BOARD.ground},
  webview: {flex: 1, backgroundColor: BOARD.ground},
});
