/**
 * The board's colours, for the native screens around it.
 *
 * Each value is a token from :root in docs/index.html, so the launch screen,
 * the offline screen and the board read as one surface on the TV. Amber is the
 * board's lettering and its focus ring and nothing else, here as there.
 */
export const BOARD = {
  /** --board: the page ground (html background-color, manifest.json background_color). */
  ground: '#0B0C0E',
  /** --flap: one flap panel. */
  flap: '#16181C',
  /** --flap-hi: the upper half of a flap. */
  flapHi: '#1D2025',
  /** --rule: hairlines between header and board. */
  rule: '#2A2E35',
  /** --ink: flap lettering, warm white. */
  ink: '#EEE7D8',
  /** --ink-2: secondary lettering. */
  ink2: '#ABA597',
  /** --amber: primary data and the focus ring. */
  amber: '#FFB23F',
  /** --critical: signal red. */
  critical: '#FF5B4C',
} as const;
