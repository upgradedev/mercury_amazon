/**
 * The two native screens of the Vega shell. Both are React Native views, drawn
 * before or instead of the board, in the board's own colours (theme.ts).
 *
 * LaunchView covers the board while the WebView loads it, so a cold Lambda
 * shows Mercury's mark and a status line, not a blank or white screen. It has
 * nothing focusable: focus stays with the WebView underneath, which takes it
 * when it mounts (hasTVPreferredFocus), so the D-pad drives the board as soon
 * as LaunchView lifts.
 *
 * OfflineView replaces the board when it could not load. It names the host it
 * tried and what failed, and holds focus on its one button, Try again, which
 * the D-pad's Select presses. BACK on either screen closes the app (App.tsx).
 */
import * as React from 'react';
import {useState} from 'react';
import {ActivityIndicator, Image, Pressable, StyleSheet, Text, View} from 'react-native';
import {BOARD} from './theme';

/** The board's wordmark tile (docs/index.html), also the launcher icon in manifest.toml. */
const MARK = require('../assets/image/mercury_icon.png');

export const LaunchView = () => (
  <View style={styles.launch} testID="launch-view">
    <Image source={MARK} style={styles.markLarge} accessible={false} />
    <Text style={styles.name}>MERCURY</Text>
    <Text style={styles.tagline}>FIRE TV INCIDENT BOARD</Text>
    <Text style={styles.status}>Connecting to the incident board</Text>
    <ActivityIndicator style={styles.spinner} size="large" color={BOARD.ink2} />
  </View>
);

/**
 * The offline view's one control. It takes focus when it mounts, and Select on
 * the remote presses it. Vega draws no focus indicator on a Pressable, so the
 * ring comes from onFocus and onBlur (focus-management.html).
 */
const TryAgainButton = ({onPress}: {onPress: () => void}) => {
  const [focused, setFocused] = useState(false);
  return (
    <Pressable
      testID="retry"
      accessibilityRole="button"
      accessibilityLabel="Try again"
      hasTVPreferredFocus={true}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      onPress={onPress}
      style={[styles.button, focused && styles.buttonFocused]}>
      <Text style={styles.buttonLabel}>Try again</Text>
    </Pressable>
  );
};

export interface OfflineViewProps {
  /** The host the WebView tried, from the live board URL. */
  host: string;
  /** What failed: a network error, an HTTP status, or the connect timeout. */
  reason: string;
  onRetry: () => void;
}

export const OfflineView = ({host, reason, onRetry}: OfflineViewProps) => (
  <View style={styles.offline} testID="offline-view">
    <View style={styles.header}>
      <Image source={MARK} style={styles.markSmall} accessible={false} />
      <Text style={styles.headerName}>MERCURY</Text>
      <Text style={styles.headerTagline}>FIRE TV INCIDENT BOARD</Text>
    </View>
    <View style={styles.message}>
      <Text style={styles.kicker}>OFFLINE</Text>
      <Text style={styles.title}>Cannot reach the incident board</Text>
      <Text style={styles.detail}>{`Tried ${host}`}</Text>
      <Text style={styles.reason}>{`Reported: ${reason}`}</Text>
      <TryAgainButton onPress={onRetry} />
      <Text style={styles.hint}>Press BACK to close Mercury</Text>
    </View>
  </View>
);

// Sized for a 1920 x 1080 TV layout, inside the 5% title-safe margins.
const styles = StyleSheet.create({
  launch: {
    position: 'absolute',
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: BOARD.ground,
  },
  markLarge: {width: 168, height: 168, marginBottom: 40},
  name: {color: BOARD.ink, fontSize: 64, fontWeight: '700', letterSpacing: 10},
  tagline: {color: BOARD.amber, fontSize: 22, fontWeight: '600', letterSpacing: 5, marginTop: 10},
  status: {color: BOARD.ink2, fontSize: 32, marginTop: 64},
  spinner: {marginTop: 28},
  offline: {
    flex: 1,
    backgroundColor: BOARD.ground,
    paddingVertical: 54,
    paddingHorizontal: 96,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingBottom: 18,
    borderBottomWidth: 1,
    borderBottomColor: BOARD.rule,
  },
  markSmall: {width: 52, height: 52, marginRight: 18},
  headerName: {color: BOARD.ink, fontSize: 30, fontWeight: '700', letterSpacing: 5},
  headerTagline: {color: BOARD.amber, fontSize: 18, fontWeight: '600', letterSpacing: 4, marginLeft: 18},
  message: {flex: 1, justifyContent: 'center', maxWidth: 1400},
  kicker: {color: BOARD.critical, fontSize: 22, fontWeight: '700', letterSpacing: 5},
  title: {color: BOARD.ink, fontSize: 56, fontWeight: '700', marginTop: 14},
  detail: {color: BOARD.ink, fontSize: 30, marginTop: 28},
  reason: {color: BOARD.ink2, fontSize: 26, marginTop: 12},
  button: {
    alignSelf: 'flex-start',
    marginTop: 48,
    paddingVertical: 18,
    paddingHorizontal: 56,
    borderWidth: 4,
    borderRadius: 6,
    borderColor: BOARD.rule,
    backgroundColor: BOARD.flap,
  },
  // The board's 10-foot focus ring: amber, thick, and a size change, so it
  // reads from a sofa without relying on colour alone.
  buttonFocused: {
    borderColor: BOARD.amber,
    backgroundColor: BOARD.flapHi,
    transform: [{scale: 1.06}],
  },
  buttonLabel: {color: BOARD.ink, fontSize: 32, fontWeight: '700'},
  hint: {color: BOARD.ink2, fontSize: 22, marginTop: 36},
});
