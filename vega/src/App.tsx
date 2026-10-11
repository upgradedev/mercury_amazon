/**
 * Vega OS host for the Mercury cockpit.
 *
 * The Vega counterpart of app/src/main/kotlin/io/github/upgradedev/mercury/
 * wallboard/MainActivity.kt. It loads the same cockpit page that the Fire OS
 * app, GitHub Pages and the Lambda serve, so both Fire TV platforms show one
 * war room instead of two copies that can drift apart. The shell adds what a
 * browser lacks: the remote's BACK key, the MercuryHost bridge and an offline
 * screen.
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
import {useCallback, useEffect, useRef, useState} from 'react';
import {BackHandler, StyleSheet, Text, View} from 'react-native';
import {COCKPIT_URL, hostOf} from './cockpitUrl';
import {
  BACK_FROM_APP,
  HOST_BOOTSTRAP,
  TAG,
  journeyLine,
  parseHostMessage,
} from './hostBridge';

const BACKGROUND = '#060913';

export const App = () => {
  const webRef = useRef<WebViewMethods>(null);
  const pageLoaded = useRef(false);
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    console.info(`[${TAG}] Loading Mercury cockpit from ${COCKPIT_URL}`);
  }, []);

  // Normally the WebView takes BACK itself (allowSystemKeyEvents) and the page
  // handles it. If the platform delivers it here instead, run the page's own
  // BACK routine. On the offline screen there is no WebView, so returning false
  // lets the platform default close the app.
  useEffect(() => {
    const subscription = BackHandler.addEventListener('hardwareBackPress', () => {
      const web = webRef.current;
      if (!web || failure !== null) {
        return false;
      }
      web.injectJavaScript(BACK_FROM_APP);
      return true;
    });
    return () => subscription.remove();
  }, [failure]);

  const onMessage = useCallback((event: WebViewMessageEvent) => {
    const message = parseHostMessage(event.nativeEvent.data);
    if (!message) {
      return;
    }
    if (message.type === 'back_unhandled') {
      // The page and its history had nothing to close: leave, as
      // MainActivity.handleBack does with finish().
      BackHandler.exitApp();
      return;
    }
    console.info(`[${TAG}] ${journeyLine(message.event, message.detail)}`);
  }, []);

  if (failure !== null) {
    return (
      <View style={styles.offline}>
        <Text style={styles.offlineTitle}>Mercury cockpit unreachable</Text>
        <Text style={styles.offlineBody}>
          This Fire TV could not load {COCKPIT_URL}
        </Text>
        <Text style={styles.offlineHint}>Reported: {failure}</Text>
        <Text style={styles.offlineHint}>
          Check that {hostOf(COCKPIT_URL)} is reachable, then relaunch. Press
          BACK to close.
        </Text>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <WebView
        ref={webRef}
        style={styles.webview}
        source={{uri: COCKPIT_URL}}
        hasTVPreferredFocus={true}
        javaScriptEnabled={true}
        domStorageEnabled={true}
        mediaPlaybackRequiresUserAction={false}
        mixedContentMode="never"
        allowSystemKeyEvents={true}
        injectedJavaScriptBeforeContentLoaded={HOST_BOOTSTRAP}
        onLoad={(event: WebViewNavigationEvent) => {
          pageLoaded.current = true;
          const url = event.nativeEvent.url || COCKPIT_URL;
          console.info(`[${TAG}] journey:page_loaded:${url}`);
        }}
        onError={({nativeEvent}: WebViewErrorEvent) => {
          const description = nativeEvent.description || 'unknown error';
          console.warn(`[${TAG}] Cockpit failed to load: ${nativeEvent.code} ${description}`);
          // Vega's onError has no isMainFrame flag. A failure before the first
          // successful load is the main document; a later sub-resource failure
          // must not blank a working cockpit (MainActivity's rule).
          if (!pageLoaded.current) {
            setFailure(description);
          }
        }}
        onHttpError={({nativeEvent}: WebViewHttpErrorEvent) => {
          console.warn(
            `[${TAG}] HTTP ${nativeEvent.statusCode} at ${nativeEvent.url} (main frame: ${nativeEvent.isMainFrame})`,
          );
        }}
        onMessage={onMessage}
        onCloseWindow={() => BackHandler.exitApp()}
      />
    </View>
  );
};

export default App;

// flex: 1 on the container is what Vega needs for the WebView to take focus.
const styles = StyleSheet.create({
  container: {flex: 1, backgroundColor: BACKGROUND},
  webview: {flex: 1, backgroundColor: BACKGROUND},
  offline: {
    flex: 1,
    backgroundColor: BACKGROUND,
    paddingVertical: 60,
    paddingHorizontal: 150,
  },
  offlineTitle: {color: '#8b5cf6', fontSize: 52, marginBottom: 24},
  offlineBody: {color: '#f8fafc', fontSize: 30, marginBottom: 20},
  offlineHint: {color: '#94a3b8', fontSize: 24, marginBottom: 12},
});
