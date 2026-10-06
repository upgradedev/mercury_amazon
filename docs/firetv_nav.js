/**
 * Mercury 10-foot spatial D-pad navigation.
 *
 * This is the only focus system in the cockpit. It is driven from two places and
 * both go through the same entry point, so keyboard and remote behave identically:
 *
 *   - a desktop keyboard, via the keydown listener installed here;
 *   - the Fire TV remote, via window.mercuryNav.move(direction), which the native
 *     Leanback MainActivity calls through its JavaScript bridge.
 *
 * Movement is geometric, not a list walk. For a pressed direction it keeps only
 * the candidates that actually lie in that direction, then picks the one with the
 * smallest weighted distance, where drift perpendicular to the direction of travel
 * is penalised. That makes a grid behave like a grid: pressing Right from a tile
 * lands on the tile beside it, not on whatever happens to be next in the DOM.
 */
(function () {
  'use strict';

  var FOCUSABLE_SELECTOR = '[data-tv-focusable]:not([disabled]):not([hidden])';
  var FOCUS_CLASS = 'tv-focused';
  var FOCUS_EVENT = 'mercury:focuschange';
  var PERPENDICULAR_PENALTY = 2.5;
  /* Sub-pixel rounding and 1px borders can put two boxes that sit edge to edge a
     fraction of a pixel into each other. This much overlap still counts as beside. */
  var EDGE_SLACK = 2;
  var DIRECTIONS = { UP: 'UP', DOWN: 'DOWN', LEFT: 'LEFT', RIGHT: 'RIGHT' };
  /* On a television, a direction that reaches a deferred cursor this soon after the
     answer that deferred it is not the viewer's next press: nobody has read the
     answer yet. The Android TV emulator footage for f423ba5 showed one arriving about
     half a second after RECORDED, with no key pressed, and the board scrolled away
     from its payoff. CENTER is never held, so the next Center always acts. */
  var DEFER_SETTLE_MS = 1500;

  var KEY_TO_DIRECTION = {
    ArrowUp: DIRECTIONS.UP,
    ArrowDown: DIRECTIONS.DOWN,
    ArrowLeft: DIRECTIONS.LEFT,
    ArrowRight: DIRECTIONS.RIGHT,
    Up: DIRECTIONS.UP,
    Down: DIRECTIONS.DOWN,
    Left: DIRECTIONS.LEFT,
    Right: DIRECTIONS.RIGHT
  };

  function isVisible(element) {
    if (!element || element.hidden) return false;
    var rect = element.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }

  function centreOf(element) {
    var rect = element.getBoundingClientRect();
    return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2, rect: rect };
  }

  /** Gap between two spans on one axis: 0 when they overlap. */
  function spanGap(aStart, aEnd, bStart, bEnd) {
    if (bStart >= aEnd) return bStart - aEnd;
    if (aStart >= bEnd) return aStart - bEnd;
    return 0;
  }

  /**
   * Score a candidate for a move, box to box. Returns null when the candidate does
   * not lie wholly in the pressed direction, otherwise a distance where lower wins.
   *
   * Distances are measured edge to edge, and drift across the direction of travel
   * costs nothing while the two boxes overlap on that axis. Centre to centre, a
   * full-width row sitting 21px under a narrow button scored as if it were 680px off
   * to the side, and DOWN from "Ask what changed" jumped 1400px past the whole
   * departures board to the next narrow button on the page.
   *
   * Exported for testing: the geometry is pure and does not need a browser.
   */
  function scoreCandidate(fromBox, toBox, direction) {
    var a = fromBox.rect;
    var b = toBox.rect;
    var along;
    var across;

    if (direction === DIRECTIONS.RIGHT) {
      if (b.left < a.right - EDGE_SLACK) return null;
      along = b.left - a.right; across = spanGap(a.top, a.bottom, b.top, b.bottom);
    } else if (direction === DIRECTIONS.LEFT) {
      if (b.right > a.left + EDGE_SLACK) return null;
      along = a.left - b.right; across = spanGap(a.top, a.bottom, b.top, b.bottom);
    } else if (direction === DIRECTIONS.DOWN) {
      if (b.top < a.bottom - EDGE_SLACK) return null;
      along = b.top - a.bottom; across = spanGap(a.left, a.right, b.left, b.right);
    } else if (direction === DIRECTIONS.UP) {
      if (b.bottom > a.top + EDGE_SLACK) return null;
      along = a.top - b.bottom; across = spanGap(a.left, a.right, b.left, b.right);
    } else return null;

    return Math.max(0, along) + across * PERPENDICULAR_PENALTY;
  }

  /**
   * The old centre-to-centre score, kept only as a fallback for UP and DOWN when no
   * control lies wholly above or below, so a staggered layout never strands one.
   * LEFT and RIGHT have no fallback: a full-width row has no neighbour to its right,
   * and RIGHT from it holds instead of jumping down the page.
   */
  function centreScore(fromBox, toBox, direction) {
    var dx = toBox.x - fromBox.x;
    var dy = toBox.y - fromBox.y;
    var along;
    var across;
    if (direction === DIRECTIONS.DOWN) { along = dy; across = Math.abs(dx); }
    else if (direction === DIRECTIONS.UP) { along = -dy; across = Math.abs(dx); }
    else return null;
    if (along <= 1) return null;
    return along + across * PERPENDICULAR_PENALTY;
  }

  /** Tie-break between equal scores: the box whose leading edge lines up with ours. */
  function alignment(fromBox, toBox, direction) {
    if (direction === DIRECTIONS.UP || direction === DIRECTIONS.DOWN) {
      return Math.abs(toBox.rect.left - fromBox.rect.left);
    }
    return Math.abs(toBox.rect.top - fromBox.rect.top);
  }

  /** Best available human-readable name for a control, for the key hint bar. */
  function labelOf(element) {
    var explicit = typeof element.getAttribute === 'function'
      ? (element.getAttribute('data-tv-label') || element.getAttribute('aria-label'))
      : null;
    if (explicit) return explicit;
    var text = element.textContent ? String(element.textContent).trim() : '';
    return text.length > 60 ? text.slice(0, 57) + '...' : text;
  }

  /**
   * Tell the page which control the cursor is on. The page renders this in its
   * key hint bar, the way a television application does, without registering a
   * second key handler of its own. Guarded because this file is also executed
   * outside a browser by the navigation spec.
   */
  function announceFocus(element, pending) {
    var CustomEventCtor = typeof window !== 'undefined' ? window.CustomEvent : null;
    if (typeof document.dispatchEvent !== 'function' || typeof CustomEventCtor !== 'function') return;
    document.dispatchEvent(new CustomEventCtor(FOCUS_EVENT, {
      detail: { element: element, label: labelOf(element), pending: pending === true }
    }));
  }

  function now() {
    return typeof performance !== 'undefined' && typeof performance.now === 'function'
      ? performance.now() : Date.now();
  }

  /** Bounded journey note for the Android TV logcat; a no-op outside the app. */
  function reportHost(event, detail) {
    try {
      var host = typeof window !== 'undefined' ? window.MercuryHost : null;
      if (host && typeof host.reportJourney === 'function') host.reportJourney(event, detail);
    } catch (ignored) { /* a browser has no native host */ }
  }

  function SpatialNavigator() {
    this.current = null;
    this.pending = false;
    this.deferredAt = 0;
    this.enabled = true;
    this.scope = null;
    this.scopeInset = null;
  }

  /** True when the element may be a stop: inside the open panel, if one is open. */
  SpatialNavigator.prototype.inScope = function (element) {
    if (!this.scope) return true;
    return !!element && typeof this.scope.contains === 'function' && this.scope.contains(element);
  };

  SpatialNavigator.prototype.candidates = function () {
    var self = this;
    return Array.prototype.slice
      .call(document.querySelectorAll(FOCUSABLE_SELECTOR))
      .filter(isVisible)
      .filter(function (element) { return self.inScope(element); });
  };

  /**
   * Keep the remote inside one region (an open panel) until release() is called.
   * The page calls this when a panel opens and releases it when BACK closes the
   * panel. Before, the ring walked out of an open panel to the board or to
   * Connection while the legend still said BACK leads back to the wall.
   *
   * Only the D-pad is contained. Tab and a mouse still reach every control, as a
   * keyboard user expects; the next arrow press brings the cursor back into the
   * region. options.bottomInset (a number, or a function returning one) is the
   * height of anything fixed over the bottom of the viewport, such as a key bar.
   */
  SpatialNavigator.prototype.contain = function (element, options) {
    this.scope = element || null;
    this.scopeInset = options && options.bottomInset !== undefined ? options.bottomInset : null;
  };

  SpatialNavigator.prototype.release = function () {
    this.scope = null;
    this.scopeInset = null;
  };

  /**
   * At the edge of a contained region, UP or DOWN scrolls the rest of the region
   * into view, a step at a time, instead of leaving it. That is how a long answer
   * in a panel is read with a remote. Returns true when the page scrolled.
   */
  SpatialNavigator.prototype.scrollScope = function (direction) {
    var scope = this.scope;
    if (!scope || typeof scope.getBoundingClientRect !== 'function') return false;
    if (typeof window === 'undefined' || typeof window.scrollBy !== 'function') return false;
    var height = window.innerHeight || 0;
    if (!height) return false;
    var inset = typeof this.scopeInset === 'function' ? this.scopeInset() : (this.scopeInset || 0);
    var visible = Math.max(1, height - inset);
    var step = Math.round(visible * 0.6);
    var rect = scope.getBoundingClientRect();
    // How far the region runs past the edge being pressed toward; nothing when it
    // already ends inside the viewport.
    var hidden;
    if (direction === DIRECTIONS.DOWN) hidden = rect.bottom - visible;
    else if (direction === DIRECTIONS.UP) hidden = -rect.top;
    else return false;
    if (!(hidden >= 1)) return false;
    var distance = Math.min(step, hidden);
    window.scrollBy(0, direction === DIRECTIONS.DOWN ? distance : -distance);
    return true;
  };

  /** True when the element's box is already wholly inside the viewport. */
  function isFullyInViewport(element) {
    var rect = element.getBoundingClientRect();
    var height = (window.innerHeight || 0);
    var width = (window.innerWidth || 0);
    if (!height || !width) return true;
    return rect.top >= 0 && rect.left >= 0 && rect.bottom <= height && rect.right <= width;
  }

  /**
   * Put the D-pad cursor on an element. Keyboard focus follows unless
   * options.domFocus is false, which the page passes on load outside a television
   * host so a desktop keyboard user's first Tab still reaches the skip link.
   */
  SpatialNavigator.prototype.setFocus = function (element, options) {
    if (!element) return;
    this.pending = false;
    var previous = document.querySelector('.' + FOCUS_CLASS);
    if (previous && previous !== element) previous.classList.remove(FOCUS_CLASS);
    element.classList.add(FOCUS_CLASS);
    this.current = element;
    var domFocus = !options || options.domFocus !== false;
    if (domFocus && typeof element.focus === 'function') element.focus({ preventScroll: true });
    // Scroll only when the target is not already wholly visible. Calling
    // scrollIntoView unconditionally made the page jump on load, which on a TV
    // reads as the wallboard glitching the moment it is switched on.
    if (typeof element.scrollIntoView === 'function' && !isFullyInViewport(element)) {
      element.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    }
    announceFocus(element);
  };

  /**
   * Make an element the next stop without moving the screen to it. The page uses
   * this after a result it wants left in view: the cursor belongs to the element,
   * so CENTER acts on it, but no ring is drawn and nothing scrolls until the next
   * D-pad press, which first brings it into view. Keyboard focus does not go to
   * the off-screen control either: it parks on options.park, something already on
   * screen (the page passes the board), so the ring, the readout and the browser's
   * focus all agree that nothing has moved yet. Enter there acts on the cursor.
   */
  SpatialNavigator.prototype.defer = function (element, options) {
    if (!element) return;
    var previous = document.querySelector('.' + FOCUS_CLASS);
    if (previous) previous.classList.remove(FOCUS_CLASS);
    this.current = element;
    this.pending = true;
    this.deferredAt = now();
    var park = options && options.park;
    if (park && typeof park.focus === 'function') park.focus({ preventScroll: true });
    // After focus(): the page's focusin listener names whatever took focus, and
    // this is the line the legend should end on.
    announceFocus(element, true);
  };

  /** Bring a deferred cursor into view with its ring. True when there was one. */
  SpatialNavigator.prototype.reveal = function () {
    if (!this.pending || !this.current) return false;
    this.setFocus(this.current);
    return true;
  };

  SpatialNavigator.prototype.focusFirst = function (options) {
    var all = this.candidates();
    if (!all.length) return;
    // Reading order: topmost, then leftmost.
    all.sort(function (a, b) {
      var ra = a.getBoundingClientRect();
      var rb = b.getBoundingClientRect();
      return (ra.top - rb.top) || (ra.left - rb.left);
    });
    this.setFocus(all[0], options);
  };

  /** The lowest score wins; a tie goes to the best-aligned leading edge, then DOM order. */
  function pick(from, all, current, direction, scorer) {
    var best = null;
    var bestScore = Infinity;
    var bestAlign = Infinity;
    for (var i = 0; i < all.length; i++) {
      if (all[i] === current) continue;
      var box = centreOf(all[i]);
      var score = scorer(from, box, direction);
      if (score === null) continue;
      var align = alignment(from, box, direction);
      if (score < bestScore - 0.5 || (Math.abs(score - bestScore) <= 0.5 && align < bestAlign)) {
        bestScore = score;
        bestAlign = align;
        best = all[i];
      }
    }
    return best;
  }

  /** Move focus one step in a direction. Returns the element focused, or null. */
  SpatialNavigator.prototype.move = function (direction) {
    if (!this.enabled) return null;
    // The first press after a deferred cursor only shows where it is, unless a
    // panel has opened since and the deferred control is outside it.
    if (this.pending && this.current && isVisible(this.current) && this.inScope(this.current)) {
      var waited = Math.round(now() - this.deferredAt);
      var held = onTelevision() && waited < DEFER_SETTLE_MS;
      // Named in logcat, so the next emulator run says where the press came from.
      reportHost('deferred_press', direction + ':' + lastInput + ':' + waited + 'ms:'
        + (held ? 'held' : 'revealed'));
      if (held) return this.current;
      this.reveal();
      return this.current;
    }
    var all = this.candidates();
    if (!all.length) return null;

    if (!this.current || all.indexOf(this.current) === -1 || !isVisible(this.current)) {
      this.focusFirst();
      return this.current;
    }

    var from = centreOf(this.current);
    var best = pick(from, all, this.current, direction, scoreCandidate);
    if (!best) best = pick(from, all, this.current, direction, centreScore);

    // No candidate in that direction: hold focus rather than wrapping, which is
    // what a 10-foot UI should do. Wrapping loses the viewer's place. Inside an
    // open panel, UP and DOWN at its edge scroll the rest of the panel instead.
    if (!best) {
      this.scrollScope(direction);
      return this.current;
    }
    this.setFocus(best);
    return best;
  };

  SpatialNavigator.prototype.select = function () {
    if (!this.current) {
      this.focusFirst();
      return null;
    }
    this.reveal();
    this.current.click();
    return this.current;
  };

  SpatialNavigator.prototype.back = function () {
    // Give the page a chance to close whatever is open. Returns true when the
    // page handled it, so the native host knows not to exit the activity.
    var handler = window.mercuryOnBack;
    if (typeof handler === 'function') return handler() === true;
    return false;
  };

  var navigator_ = new SpatialNavigator();
  /* Which path the last key came in by, for the journey note above. */
  var lastInput = 'none';

  function onKeyDown(event) {
    if (event.defaultPrevented) return;
    var target = event.target;
    // Never steal arrows from a text field.
    if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) {
      if (event.key !== 'Enter') return;
    }

    var direction = KEY_TO_DIRECTION[event.key];
    lastInput = event.repeat ? 'key-repeat' : 'key';
    if (direction) {
      event.preventDefault();
      navigator_.move(direction);
      return;
    }
    if (event.key === 'Enter' || event.key === 'Select') {
      if (target && target.tagName === 'INPUT') return;
      // A link or button outside the ring (the skip link) activates itself.
      if (target && typeof target.matches === 'function'
          && target.matches('a[href], button, select, textarea')
          && !target.matches(FOCUSABLE_SELECTOR)) return;
      event.preventDefault();
      navigator_.select();
      return;
    }
    if (event.key === 'Backspace' || event.key === 'Escape') {
      if (navigator_.back()) event.preventDefault();
    }
  }

  document.addEventListener('keydown', onKeyDown);
  function onTelevision() {
    var root = document.documentElement;
    return !!(root && root.classList && root.classList.contains('tv-host'));
  }

  document.addEventListener('DOMContentLoaded', function () {
    if (navigator_.current) return;
    if (onTelevision()) { navigator_.focusFirst(); return; }
    // Outside a television host the cursor is placed, but keyboard focus is left
    // where the browser puts it, at the top of the document.
    navigator_.focusFirst({ domFocus: false });
  });
  // Tab and the arrow keys have to agree about where the viewer is. When keyboard
  // focus lands on a control in the ring, the cursor follows it; when it lands on
  // something outside the ring (the skip link, a text field), the ring steps aside
  // until the next arrow press, so there is never a second focus indicator.
  document.addEventListener('focusin', function (event) {
    var target = event.target;
    if (!target || typeof target.matches !== 'function') return;
    if (target.matches(FOCUSABLE_SELECTOR)) {
      if (target !== navigator_.current) navigator_.setFocus(target, { domFocus: false });
    } else if (navigator_.current && navigator_.current.classList) {
      navigator_.current.classList.remove(FOCUS_CLASS);
    }
  });
  // A click with a mouse should move the D-pad cursor too, so the two agree.
  document.addEventListener('click', function (event) {
    var focusable = event.target && event.target.closest
      ? event.target.closest(FOCUSABLE_SELECTOR)
      : null;
    if (focusable) navigator_.setFocus(focusable);
  }, true);

  /**
   * Entry point for the native Fire TV MainActivity bridge.
   * Accepts UP, DOWN, LEFT, RIGHT, SELECT, BACK.
   * Returns true when the page consumed the key.
   */
  window.mercuryNav = navigator_;
  window.navigateDpad = function (direction) {
    lastInput = 'bridge';
    if (direction === 'SELECT') { navigator_.select(); return true; }
    if (direction === 'BACK') { return navigator_.back(); }
    if (DIRECTIONS[direction]) { navigator_.move(direction); return true; }
    return false;
  };

  // Exposed for the structural test suite and for debugging in a console.
  window.mercuryNavInternals = {
    scoreCandidate: scoreCandidate,
    FOCUSABLE_SELECTOR: FOCUSABLE_SELECTOR,
    FOCUS_CLASS: FOCUS_CLASS,
    FOCUS_EVENT: FOCUS_EVENT,
    PERPENDICULAR_PENALTY: PERPENDICULAR_PENALTY,
    DEFER_SETTLE_MS: DEFER_SETTLE_MS
  };
})();
