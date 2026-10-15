/**
 * What the native shell shows around the board, as a reducer.
 *
 *   connecting -> board     the WebView reported its first load
 *   connecting -> offline   it failed, the main frame answered 4xx/5xx, or
 *                           CONNECT_TIMEOUT_MS passed without a load
 *   board      -> offline   only a main-frame HTTP error; a failed sub-resource
 *                           must not blank a working board (MainActivity's rule)
 *   offline    -> connecting  Try again: a new attempt, so a new WebView
 *
 * Every WebView event carries the attempt it belongs to. An event from a
 * WebView that Try again already replaced changes nothing.
 */
export const CONNECT_TIMEOUT_MS = 30000;

export type Phase = 'connecting' | 'board' | 'offline';

export interface ShellState {
  /** Starts at 1 and grows with every Try again. The WebView is keyed on it. */
  attempt: number;
  phase: Phase;
  /** What failed, for the offline screen. */
  reason: string | null;
}

export type ShellEvent =
  | {type: 'loaded'; attempt: number}
  | {type: 'load_failed'; attempt: number; reason: string}
  | {type: 'main_frame_failed'; attempt: number; reason: string}
  | {type: 'timed_out'; attempt: number}
  | {type: 'retry'};

export const INITIAL_SHELL: ShellState = {attempt: 1, phase: 'connecting', reason: null};

export function shellReducer(state: ShellState, event: ShellEvent): ShellState {
  if (event.type === 'retry') {
    return state.phase === 'offline'
      ? {attempt: state.attempt + 1, phase: 'connecting', reason: null}
      : state;
  }
  if (event.attempt !== state.attempt) {
    return state;
  }
  switch (event.type) {
    case 'loaded':
      return state.phase === 'connecting' ? {...state, phase: 'board'} : state;
    case 'load_failed':
      // Vega's onError has no isMainFrame flag. Before the first load the
      // failure is the board itself; after it, it is a sub-resource.
      return state.phase === 'connecting'
        ? {...state, phase: 'offline', reason: event.reason}
        : state;
    case 'main_frame_failed':
      return state.phase === 'offline'
        ? state
        : {...state, phase: 'offline', reason: event.reason};
    case 'timed_out':
      return state.phase === 'connecting'
        ? {...state, phase: 'offline', reason: `no answer in ${CONNECT_TIMEOUT_MS / 1000} s`}
        : state;
  }
}

/** The offline screen's "Reported:" line for a WebView onError event. */
export function describeLoadError(code: number | undefined, description: string | undefined): string {
  const text = description && description.trim() !== '' ? description.trim() : 'unknown error';
  return typeof code === 'number' ? `${text} (code ${code})` : text;
}
