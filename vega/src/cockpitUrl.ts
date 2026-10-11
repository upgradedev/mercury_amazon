/**
 * Decides which Mercury cockpit the Vega app loads.
 *
 * A port of app/src/main/kotlin/io/github/upgradedev/mercury/wallboard/
 * CockpitUrlResolver.kt. Precedence, highest first:
 *  1. a launch-time URL (Vega has no counterpart of the Fire OS COCKPIT_URL
 *     intent extra wired up yet, so the app passes undefined);
 *  2. BUILD_CONFIG_URL, the counterpart of BuildConfig.MERCURY_COCKPIT_URL;
 *  3. DEFAULT_URL, the public demo the Fire OS build also defaults to.
 *
 * A candidate is used only when it is an absolute http or https URL, so a
 * malformed value cannot make the WebView open a file:// or javascript: URL.
 * Release builds still reach https only: Vega WebView 4.0.2 blocks cleartext
 * unless manifest.toml declares [network-traffic-policy.cleartext].
 */
export const DEFAULT_URL =
  'https://leol25sezuvokpankox5cvjopm0gtvfa.lambda-url.eu-west-1.on.aws/';

/** Empty means "use DEFAULT_URL". */
export const BUILD_CONFIG_URL = '';

const ALLOWED_SCHEMES = ['http://', 'https://'];

function schemeOf(url: string): string | undefined {
  const lower = url.toLowerCase();
  return ALLOWED_SCHEMES.find(scheme => lower.startsWith(scheme));
}

/** True when candidate is an absolute http(s) URL with a host after the scheme. */
export function isAcceptable(candidate: string | null | undefined): boolean {
  if (candidate == null || candidate.trim() === '') {
    return false;
  }
  const trimmed = candidate.trim();
  const scheme = schemeOf(trimmed);
  if (!scheme) {
    return false;
  }
  const remainder = trimmed.substring(scheme.length);
  if (remainder.trim() === '') {
    return false;
  }
  // Embedded whitespace and control characters have no place in a URL and are
  // a common way to smuggle a second target past a check.
  for (const ch of remainder) {
    if (/\s/.test(ch) || ch.charCodeAt(0) < 0x20) {
      return false;
    }
  }
  return true;
}

export function resolveCockpitUrl(
  launchUrl?: string | null,
  buildConfigUrl: string | null = BUILD_CONFIG_URL,
): string {
  if (isAcceptable(launchUrl)) {
    return (launchUrl as string).trim();
  }
  if (isAcceptable(buildConfigUrl)) {
    return (buildConfigUrl as string).trim();
  }
  return DEFAULT_URL;
}

/** Host part of a URL for the offline screen; the whole string when unparseable. */
export function hostOf(url: string): string {
  const scheme = schemeOf(url);
  if (!scheme) {
    return url;
  }
  const host = url.substring(scheme.length).split('/')[0];
  return host.trim() === '' ? url : host;
}

export const COCKPIT_URL = resolveCockpitUrl(undefined);
