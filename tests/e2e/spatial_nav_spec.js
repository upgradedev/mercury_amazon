/**
 * Executes docs/firetv_nav.js in Node against a minimal DOM shim and asserts that
 * D-pad movement is genuinely spatial.
 *
 * This is not a string assertion over the source. The real navigator code runs,
 * against a real 3x3 grid of bounding rectangles, and the assertions are about
 * which element it lands on. Run directly with:  node tests/e2e/spatial_nav_spec.js
 */
'use strict';

const fs = require('fs');
const path = require('path');
const assert = require('assert');

const NAV_SOURCE = path.join(__dirname, '..', '..', 'docs', 'firetv_nav.js');

// ------------------------------------------------------------------- DOM shim

function makeElement(id, left, top, width, height) {
  const classes = new Set();
  const attributes = { 'data-tv-label': `label for ${id}` };
  return {
    id,
    tagName: 'BUTTON',
    hidden: false,
    disabled: false,
    clicked: 0,
    focused: 0,
    textContent: id,
    getAttribute: (name) => (name in attributes ? attributes[name] : null),
    classList: {
      add: (name) => classes.add(name),
      remove: (name) => classes.delete(name),
      contains: (name) => classes.has(name)
    },
    hasClass: (name) => classes.has(name),
    getBoundingClientRect: () => ({ left, top, width, height, right: left + width, bottom: top + height }),
    focus() { this.focused += 1; },
    scrollIntoView() {},
    click() { this.clicked += 1; },
    closest() { return null; }
  };
}

function installDom(elements) {
  const listeners = {};
  const document = {
    addEventListener: (type, handler) => {
      listeners[type] = listeners[type] || [];
      listeners[type].push(handler);
    },
    querySelectorAll: () => elements.slice(),
    querySelector: (selector) => {
      if (selector === '.tv-focused') return elements.find((e) => e.hasClass('tv-focused')) || null;
      return null;
    },
    dispatch: (type, event) => (listeners[type] || []).forEach((h) => h(event)),
    dispatchEvent: (event) => {
      (listeners[event.type] || []).forEach((h) => h(event));
      return true;
    }
  };
  global.document = document;
  // A minimal CustomEvent so the navigator's focus announcement runs here too,
  // which is the same code path the cockpit's key hint bar subscribes to.
  function CustomEventShim(type, init) {
    this.type = type;
    this.detail = init && init.detail;
  }
  global.window = { location: { protocol: 'http:' }, CustomEvent: CustomEventShim };
  return document;
}

function loadNavigator(elements) {
  const document = installDom(elements);
  // Fresh evaluation each time so state does not leak between cases.
  const source = fs.readFileSync(NAV_SOURCE, 'utf8');
  // eslint-disable-next-line no-new-func
  new Function(source)();
  return { nav: global.window.mercuryNav, bridge: global.window.navigateDpad, document };
}

/** A 3x3 grid, 200x100 tiles with 20px gaps, laid out in reading order. */
function grid() {
  const cells = [];
  for (let row = 0; row < 3; row += 1) {
    for (let col = 0; col < 3; col += 1) {
      cells.push(makeElement(`r${row}c${col}`, col * 220, row * 120, 200, 100));
    }
  }
  return cells;
}

function at(cells, row, col) { return cells[row * 3 + col]; }

// --------------------------------------------------------------------- Cases

const cases = [];
function test(name, fn) { cases.push([name, fn]); }

test('focusFirst lands on the top-left element in reading order', () => {
  const cells = grid();
  const { nav } = loadNavigator(cells);
  nav.focusFirst();
  assert.strictEqual(nav.current.id, 'r0c0');
  assert.ok(nav.current.hasClass('tv-focused'), 'focused element carries the focus class');
});

test('RIGHT from the middle lands on the tile to its right, not the next in DOM order', () => {
  const cells = grid();
  const { nav } = loadNavigator(cells);
  nav.setFocus(at(cells, 1, 1));
  assert.strictEqual(nav.move('RIGHT').id, 'r1c2');
});

test('DOWN from the middle lands directly below, not on the next DOM sibling', () => {
  const cells = grid();
  const { nav } = loadNavigator(cells);
  nav.setFocus(at(cells, 1, 1));
  // The next element in DOM order is r1c2, to the right. A list walk would pick it.
  assert.strictEqual(nav.move('DOWN').id, 'r2c1');
});

test('UP and LEFT are the exact inverses of DOWN and RIGHT', () => {
  const cells = grid();
  const { nav } = loadNavigator(cells);
  nav.setFocus(at(cells, 1, 1));
  assert.strictEqual(nav.move('UP').id, 'r0c1');
  assert.strictEqual(nav.move('DOWN').id, 'r1c1');
  assert.strictEqual(nav.move('LEFT').id, 'r1c0');
  assert.strictEqual(nav.move('RIGHT').id, 'r1c1');
});

test('focus is held at an edge rather than wrapping around', () => {
  const cells = grid();
  const { nav } = loadNavigator(cells);
  nav.setFocus(at(cells, 0, 0));
  assert.strictEqual(nav.move('UP').id, 'r0c0', 'UP at the top edge holds');
  assert.strictEqual(nav.move('LEFT').id, 'r0c0', 'LEFT at the left edge holds');
});

test('a ragged row still picks the nearest, not the first in the direction', () => {
  const near = makeElement('near', 300, 0, 100, 100);
  const far = makeElement('far', 900, 0, 100, 100);
  const origin = makeElement('origin', 0, 0, 100, 100);
  const { nav } = loadNavigator([origin, far, near]); // DOM order puts 'far' first
  nav.setFocus(origin);
  assert.strictEqual(nav.move('RIGHT').id, 'near');
});

test('perpendicular drift is penalised so a straight neighbour wins', () => {
  const straight = makeElement('straight', 300, 0, 100, 100);
  const diagonal = makeElement('diagonal', 260, 400, 100, 100);
  const origin = makeElement('origin', 0, 0, 100, 100);
  const { nav } = loadNavigator([origin, diagonal, straight]);
  nav.setFocus(origin);
  assert.strictEqual(nav.move('RIGHT').id, 'straight');
});

test('zero-size elements are skipped as invisible', () => {
  const hiddenTile = makeElement('hidden', 300, 0, 0, 0);
  const visible = makeElement('visible', 600, 0, 100, 100);
  const origin = makeElement('origin', 0, 0, 100, 100);
  const { nav } = loadNavigator([origin, hiddenTile, visible]);
  nav.setFocus(origin);
  assert.strictEqual(nav.move('RIGHT').id, 'visible');
});

test('the native bridge and a direct move produce identical focus', () => {
  const cellsA = grid();
  const viaBridge = loadNavigator(cellsA);
  viaBridge.nav.setFocus(at(cellsA, 1, 1));
  viaBridge.bridge('DOWN');
  const bridgeResult = viaBridge.nav.current.id;

  const cellsB = grid();
  const viaMove = loadNavigator(cellsB);
  viaMove.nav.setFocus(at(cellsB, 1, 1));
  viaMove.nav.move('DOWN');

  assert.strictEqual(bridgeResult, viaMove.nav.current.id);
});

test('SELECT through the bridge clicks the focused element exactly once', () => {
  const cells = grid();
  const { nav, bridge } = loadNavigator(cells);
  nav.setFocus(at(cells, 0, 1));
  assert.strictEqual(bridge('SELECT'), true);
  assert.strictEqual(at(cells, 0, 1).clicked, 1);
});

test('BACK reports false when the page has no handler, so the host can exit', () => {
  const { bridge } = loadNavigator(grid());
  assert.strictEqual(bridge('BACK'), false);
});

test('BACK reports true when the page consumes it', () => {
  const { bridge } = loadNavigator(grid());
  global.window.mercuryOnBack = () => true;
  assert.strictEqual(bridge('BACK'), true);
});

test('an unknown direction is rejected rather than moving focus', () => {
  const cells = grid();
  const { nav, bridge } = loadNavigator(cells);
  nav.setFocus(at(cells, 1, 1));
  assert.strictEqual(bridge('SIDEWAYS'), false);
  assert.strictEqual(nav.current.id, 'r1c1');
});

test('keyboard arrows drive the same navigator as the remote', () => {
  const cells = grid();
  const { nav, document } = loadNavigator(cells);
  nav.setFocus(at(cells, 1, 1));
  let prevented = false;
  document.dispatch('keydown', {
    key: 'ArrowDown', target: { tagName: 'BODY' },
    preventDefault: () => { prevented = true; }
  });
  assert.strictEqual(nav.current.id, 'r2c1');
  assert.ok(prevented, 'the arrow key is consumed so the page does not also scroll');
});

test('arrow keys are left alone while typing in a text field', () => {
  const cells = grid();
  const { nav, document } = loadNavigator(cells);
  nav.setFocus(at(cells, 1, 1));
  document.dispatch('keydown', {
    key: 'ArrowDown', target: { tagName: 'INPUT' }, preventDefault: () => {}
  });
  assert.strictEqual(nav.current.id, 'r1c1', 'focus does not move away from a field being typed in');
});

test('each focus change is announced to the page with the control label', () => {
  const cells = grid();
  const { nav, document } = loadNavigator(cells);
  const announced = [];
  document.addEventListener('mercury:focuschange', (event) => {
    announced.push([event.detail.element.id, event.detail.label]);
  });
  nav.setFocus(at(cells, 0, 0));
  nav.move('RIGHT');
  assert.deepStrictEqual(announced, [
    ['r0c0', 'label for r0c0'],
    ['r0c1', 'label for r0c1']
  ], 'the key hint bar is fed by the navigator, not by a second key handler');
});

test('only one element carries the focus class at a time', () => {
  const cells = grid();
  const { nav } = loadNavigator(cells);
  nav.setFocus(at(cells, 0, 0));
  nav.move('RIGHT');
  const focused = cells.filter((c) => c.hasClass('tv-focused'));
  assert.strictEqual(focused.length, 1);
  assert.strictEqual(focused[0].id, 'r0c1');
});

/**
 * The board at 1920x1080, from the positions measured in the page: the narrow
 * primary button, Stage beside it, five full-width departure rows 21px below, and
 * the next narrow button on the page 1400px further down. Centre to centre, DOWN
 * from Ask scored the full-width row as 680px off to the side and jumped to the
 * far button, skipping the whole board.
 */
function board() {
  const ask = makeElement('ask', 80, 470, 400, 78);
  const stage = makeElement('stage', 495, 470, 326, 78);
  const rows = [0, 1, 2, 3, 4].map((i) => makeElement(`row${i}`, 86, 569 + i * 61, 1748, 58));
  const handoff = makeElement('handoff', 86, 1891, 210, 50);
  const spend = makeElement('spend', 1250, 2400, 580, 160);
  return { ask, stage, rows, handoff, spend, all: [ask, stage, ...rows, handoff, spend] };
}

test('DOWN from a narrow button lands on the full-width row directly under it', () => {
  const b = board();
  const { nav } = loadNavigator(b.all);
  nav.setFocus(b.ask);
  assert.strictEqual(nav.move('DOWN').id, 'row0', 'the board is not skipped');
  assert.strictEqual(nav.move('DOWN').id, 'row1');
});

test('UP from a full-width row returns to the button whose edge lines up with it', () => {
  const b = board();
  const { nav } = loadNavigator(b.all);
  nav.setFocus(b.rows[0]);
  // Ask and Stage are the same distance above the row; Ask shares its left edge.
  assert.strictEqual(nav.move('UP').id, 'ask');
});

test('RIGHT from a full-width row holds instead of jumping down the page', () => {
  const b = board();
  const { nav } = loadNavigator(b.all);
  nav.setFocus(b.rows[2]);
  assert.strictEqual(nav.move('RIGHT').id, 'row2');
  assert.strictEqual(nav.move('LEFT').id, 'row2');
});

test('the remote smoke path still reaches Stage from Ask, and DOWN from Stage enters the board', () => {
  const b = board();
  const { nav, bridge } = loadNavigator(b.all);
  nav.setFocus(b.ask);
  bridge('RIGHT');
  assert.strictEqual(nav.current.id, 'stage');
  bridge('DOWN');
  assert.strictEqual(nav.current.id, 'row0');
});

test('DOWN from the last row moves on to the next control below the board', () => {
  const b = board();
  const { nav } = loadNavigator(b.all);
  nav.setFocus(b.rows[4]);
  assert.strictEqual(nav.move('DOWN').id, 'handoff');
});

// ---------------------------------------------------------------------- Runner

let failures = 0;
for (const [name, fn] of cases) {
  try {
    fn();
    console.log(`ok   ${name}`);
  } catch (error) {
    failures += 1;
    console.log(`FAIL ${name}\n     ${error.message}`);
  }
}
console.log(`\n${cases.length - failures}/${cases.length} spatial navigation assertions passed`);
process.exit(failures === 0 ? 0 : 1);
