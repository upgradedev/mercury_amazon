import {CONNECT_TIMEOUT_MS, INITIAL_SHELL, describeLoadError, shellReducer} from '../src/shell';
import type {ShellEvent, ShellState} from '../src/shell';

const run = (...events: ShellEvent[]): ShellState => events.reduce(shellReducer, INITIAL_SHELL);

describe('shellReducer', () => {
  it('starts on the launch view, attempt 1', () => {
    expect(INITIAL_SHELL).toEqual({attempt: 1, phase: 'connecting', reason: null});
  });

  it('shows the board after the first load', () => {
    expect(run({type: 'loaded', attempt: 1}).phase).toBe('board');
  });

  it('goes offline when the load fails before the board loads', () => {
    expect(run({type: 'load_failed', attempt: 1, reason: 'net::ERR_TIMED_OUT'})).toEqual({
      attempt: 1,
      phase: 'offline',
      reason: 'net::ERR_TIMED_OUT',
    });
  });

  it('keeps the board when a later load error is a sub-resource', () => {
    const state = run({type: 'loaded', attempt: 1}, {type: 'load_failed', attempt: 1, reason: 'img'});
    expect(state.phase).toBe('board');
  });

  it('stays offline when the WebView reports a load for its error page', () => {
    const state = run(
      {type: 'load_failed', attempt: 1, reason: 'net::ERR_NAME_NOT_RESOLVED'},
      {type: 'loaded', attempt: 1},
    );
    expect(state.phase).toBe('offline');
  });

  it('goes offline on a main-frame HTTP error, before or after the first load', () => {
    expect(run({type: 'main_frame_failed', attempt: 1, reason: 'HTTP 502'}).reason).toBe('HTTP 502');
    const later = run({type: 'loaded', attempt: 1}, {type: 'main_frame_failed', attempt: 1, reason: 'HTTP 503'});
    expect(later).toEqual({attempt: 1, phase: 'offline', reason: 'HTTP 503'});
  });

  it('keeps the first reason when a second failure follows', () => {
    const state = run(
      {type: 'main_frame_failed', attempt: 1, reason: 'HTTP 502'},
      {type: 'load_failed', attempt: 1, reason: 'later'},
      {type: 'timed_out', attempt: 1},
    );
    expect(state.reason).toBe('HTTP 502');
  });

  it('times out only while connecting', () => {
    expect(run({type: 'timed_out', attempt: 1}).reason).toBe(`no answer in ${CONNECT_TIMEOUT_MS / 1000} s`);
    expect(run({type: 'loaded', attempt: 1}, {type: 'timed_out', attempt: 1}).phase).toBe('board');
  });

  it('retries from the offline view only, as a new attempt', () => {
    expect(run({type: 'retry'})).toBe(INITIAL_SHELL);
    const retried = run({type: 'timed_out', attempt: 1}, {type: 'retry'});
    expect(retried).toEqual({attempt: 2, phase: 'connecting', reason: null});
    expect(run({type: 'timed_out', attempt: 1}, {type: 'retry'}, {type: 'loaded', attempt: 2}).phase).toBe(
      'board',
    );
  });

  it('ignores every event from a WebView that a retry replaced', () => {
    const retried = run({type: 'load_failed', attempt: 1, reason: 'x'}, {type: 'retry'});
    for (const late of [
      {type: 'loaded', attempt: 1},
      {type: 'load_failed', attempt: 1, reason: 'y'},
      {type: 'main_frame_failed', attempt: 1, reason: 'HTTP 500'},
      {type: 'timed_out', attempt: 1},
    ] as ShellEvent[]) {
      expect(shellReducer(retried, late)).toBe(retried);
    }
  });
});

describe('describeLoadError', () => {
  it('reports the description and the code', () => {
    expect(describeLoadError(-2, 'net::ERR_NAME_NOT_RESOLVED')).toBe('net::ERR_NAME_NOT_RESOLVED (code -2)');
    expect(describeLoadError(undefined, ' net::ERR_FAILED ')).toBe('net::ERR_FAILED');
    expect(describeLoadError(-1, '')).toBe('unknown error (code -1)');
  });
});
