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
 *    MainActivity.handleBack's order. A page that does not answer within
 *    BACK_ANSWER_TIMEOUT_MS counts as having nothing open, so a hung page
 *    cannot trap the remote.
 *  - Startup KPIs: reportFullyDrawn (Vega Performance API) marks the first
 *    frame of the board, and again the first frame after a warm resume, so
 *    'vega exec perf kpi-visualizer' can report time to fully drawn (TTFD)
 *    next to the time to first frame (TTFF) the OS measures on its own
 *    (measure-app-kpis.html).
 */
import {useReportFullyDrawn} from '@amazon-devices/kepler-performance-api';
import {useKeplerAppStateManager} from '@amazon-devices/react-native-kepler';
import type {KeplerAppStateChangeData} from '@amazon-devices/react-native-kepler';
import {WebView} from '@amazon-devices/webview';
// The package root (dist/index.d.ts in 4.0.2) exports only WebView,
// CookieManager and Cookie, so the event and method types come from the file
// that declares them.
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
import {
  BACK_ANSWER_TIMEOUT_MS,
  BACK_FROM_APP,
  HOST_BOOTSTRAP,
  TAG,
  journeyLine,
  parseHostMessage,
} from './hostBridge';
import {CONNECT_TIMEOUT_MS, INITIAL_SHELL, describeLoadError, shellReducer} from './shell';
import {LaunchView, OfflineView} from './ShellScreens';
import {BOARD} from './theme';

export const App = () => {
  const [{attempt, phase, reason}, dispatch] = useReducer(shellReducer, INITIAL_SHELL);
  const webRef = useRef<WebViewMethods>(null);
  // The WebView's own answer to "is there history?", from its last navigation
  // event: MainActivity asks webView.canGoBack() at the same point. History
  // only moves on page loads: docs/index.html and docs/firetv_nav.js use no
  // pushState, replaceState or hash routing, so onLoadStart and onLoad see
  // every change.
  const canGoBack = useRef(false);
  // BACK presses the page has not answered yet, and the deadline for them.
  const pendingBack = useRef(0);
  const backTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reportFullyDrawn = useReportFullyDrawn();
  const appState = useKeplerAppStateManager();
  // The board has been drawn once, so a warm resume shows it at once.
  const boardDrawn = useRef(false);
  const phaseNow = useRef(phase);
  useEffect(() => {
    phaseNow.current = phase;
  }, [phase]);

  const markFullyDrawn = useCallback(
    (why: string) => {
      try {
        reportFullyDrawn();
        console.info(`[${TAG}] fully_drawn:${why}`);
      } catch (error) {
        console.warn(`[${TAG}] reportFullyDrawn failed: ${String(error)}`);
      }
    },
    [reportFullyDrawn],
  );

  const clearBackWait = useCallback(() => {
    pendingBack.current = 0;
    if (backTimer.current !== null) {
      clearTimeout(backTimer.current);
      backTimer.current = null;
    }
  }, []);

  // The page had nothing open to close: history next, then leave.
  const leaveBoard = useCallback(() => {
    if (canGoBack.current && webRef.current) {
      webRef.current.goBack();
    } else {
      BackHandler.exitApp();
    }
  }, []);

  useEffect(() => {
    if (phase === 'board' && !boardDrawn.current) {
      boardDrawn.current = true;
      markFullyDrawn('cold_start');
    }
  }, [phase, markFullyDrawn]);

  useEffect(() => {
    let last: KeplerAppStateChangeData = appState.getCurrentState();
    const subscription = appState.addAppStateListener('change', (next: KeplerAppStateChangeData) => {
      if (
        next === 'active' &&
        (last === 'background' || last === 'inactive') &&
        boardDrawn.current &&
        phaseNow.current === 'board'
      ) {
        markFullyDrawn('warm_start');
      }
      if (typeof next === 'string') {
        last = next;
      }
    });
    return () => subscription.remove();
  }, [appState, markFullyDrawn]);

  // Only the board waits for the page; leaving it drops any wait.
  useEffect(() => {
    if (phase !== 'board') {
      clearBackWait();
    }
  }, [phase, clearBackWait]);
  useEffect(() => clearBackWait, [clearBackWait]);

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
        pendingBack.current += 1;
        if (backTimer.current !== null) {
          clearTimeout(backTimer.current);
        }
        backTimer.current = setTimeout(() => {
          console.warn(`[${TAG}] BACK: no answer from the page in ${BACK_ANSWER_TIMEOUT_MS} ms`);
          clearBackWait();
          leaveBoard();
        }, BACK_ANSWER_TIMEOUT_MS);
        web.injectJavaScript(BACK_FROM_APP);
      } else {
        // LaunchView or OfflineView: there is nothing to go back to.
        BackHandler.exitApp();
      }
      return true;
    });
    return () => subscription.remove();
  }, [phase, clearBackWait, leaveBoard]);

  const onMessage = useCallback(
    (event: WebViewMessageEvent) => {
      const message = parseHostMessage(event.nativeEvent.data);
      if (!message) {
        return;
      }
      if (message.type === 'back_handled' || message.type === 'back_unhandled') {
        // An answer nobody waits for (it came after the deadline, or no BACK
        // was pressed) changes nothing: the app already acted, or never asked.
        if (pendingBack.current === 0) {
          return;
        }
        pendingBack.current -= 1;
        if (pendingBack.current === 0) {
          clearBackWait();
        }
        if (message.type === 'back_unhandled') {
          clearBackWait();
          leaveBoard();
        }
        return;
      }
      console.info(`[${TAG}] ${journeyLine(message.event, message.detail)}`);
    },
    [clearBackWait, leaveBoard],
  );

  const retry = useCallback(() => {
    console.info(`[${TAG}] Try again`);
    canGoBack.current = false;
    clearBackWait();
    dispatch({type: 'retry'});
  }, [clearBackWait]);

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
