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
  function announceFocus(element) {
    var CustomEventCtor = typeof window !== 'undefined' ? window.CustomEvent : null;
    if (typeof document.dispatchEvent !== 'function' || typeof CustomEventCtor !== 'function') return;
    document.dispatchEvent(new CustomEventCtor(FOCUS_EVENT, {
      detail: { element: element, label: labelOf(element) }
    }));
  }

  function SpatialNavigator() {
    this.current = null;
    this.enabled = true;
  }

  SpatialNavigator.prototype.candidates = function () {
    return Array.prototype.slice
      .call(document.querySelectorAll(FOCUSABLE_SELECTOR))
      .filter(isVisible);
  };

  /** True when the element's box is already wholly inside the viewport. */
  function isFullyInViewport(element) {
    var rect = element.getBoundingClientRect();
    var height = (window.innerHeight || 0);
    var width = (window.innerWidth || 0);
    if (!height || !width) return true;
    return rect.top >= 0 && rect.left >= 0 && rect.bottom <= height && rect.right <= width;
  }

  SpatialNavigator.prototype.setFocus = function (element) {
    if (!element) return;
    var previous = document.querySelector('.' + FOCUS_CLASS);
    if (previous && previous !== element) previous.classList.remove(FOCUS_CLASS);
    element.classList.add(FOCUS_CLASS);
    this.current = element;
    if (typeof element.focus === 'function') element.focus({ preventScroll: true });
    // Scroll only when the target is not already wholly visible. Calling
    // scrollIntoView unconditionally made the page jump on load, which on a TV
    // reads as the wallboard glitching the moment it is switched on.
    if (typeof element.scrollIntoView === 'function' && !isFullyInViewport(element)) {
      element.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    }
    announceFocus(element);
  };

  SpatialNavigator.prototype.focusFirst = function () {
    var all = this.candidates();
    if (!all.length) return;
    // Reading order: topmost, then leftmost.
    all.sort(function (a, b) {
      var ra = a.getBoundingClientRect();
      var rb = b.getBoundingClientRect();
      return (ra.top - rb.top) || (ra.left - rb.left);
    });
    this.setFocus(all[0]);
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
    // what a 10-foot UI should do. Wrapping loses the viewer's place.
    if (!best) return this.current;
    this.setFocus(best);
    return best;
  };

  SpatialNavigator.prototype.select = function () {
    if (!this.current) {
      this.focusFirst();
      return null;
    }
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

  function onKeyDown(event) {
    if (event.defaultPrevented) return;
    var target = event.target;
    // Never steal arrows from a text field.
    if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) {
      if (event.key !== 'Enter') return;
    }

    var direction = KEY_TO_DIRECTION[event.key];
    if (direction) {
      event.preventDefault();
      navigator_.move(direction);
      return;
    }
    if (event.key === 'Enter' || event.key === 'Select') {
      if (target && target.tagName === 'INPUT') return;
      event.preventDefault();
      navigator_.select();
      return;
    }
    if (event.key === 'Backspace' || event.key === 'Escape') {
      if (navigator_.back()) event.preventDefault();
    }
  }

  document.addEventListener('keydown', onKeyDown);
  document.addEventListener('DOMContentLoaded', function () {
    navigator_.focusFirst();
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
    PERPENDICULAR_PENALTY: PERPENDICULAR_PENALTY
  };
})();
