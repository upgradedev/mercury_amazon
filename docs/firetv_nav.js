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

  /**
   * Score a candidate for a move. Returns null when the candidate is not in the
   * pressed direction at all, otherwise a distance where lower wins.
   *
   * Exported for testing: the geometry is pure and does not need a browser.
   */
  function scoreCandidate(fromCentre, toCentre, direction) {
    var dx = toCentre.x - fromCentre.x;
    var dy = toCentre.y - fromCentre.y;
    var along;
    var across;

    if (direction === DIRECTIONS.RIGHT) { along = dx; across = Math.abs(dy); }
    else if (direction === DIRECTIONS.LEFT) { along = -dx; across = Math.abs(dy); }
    else if (direction === DIRECTIONS.DOWN) { along = dy; across = Math.abs(dx); }
    else if (direction === DIRECTIONS.UP) { along = -dy; across = Math.abs(dx); }
    else return null;

    // Must make real progress in the pressed direction.
    if (along <= 1) return null;
    return along + across * PERPENDICULAR_PENALTY;
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
    var best = null;
    var bestScore = Infinity;

    for (var i = 0; i < all.length; i++) {
      if (all[i] === this.current) continue;
      var score = scoreCandidate(from, centreOf(all[i]), direction);
      if (score !== null && score < bestScore) {
        bestScore = score;
        best = all[i];
      }
    }

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
