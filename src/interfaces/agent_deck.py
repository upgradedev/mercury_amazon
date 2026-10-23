"""Interfaces Layer: the agent deck script served at /mcp/agent-deck.js.

The deck is appended to the cockpit page. It is quiet and it is honest:

1. It makes no call on page load and none when a departures row is selected. A call
   runs only when a viewer presses Center on a control that says what it does,
   'Ask the agent', 'Publish recorded demo handoff' or 'Check MCP handshake'.
2. Every answer card carries the data label the server returned (OFFLINE FIXTURE for
   a simulated service, LIVE for a production row read from CloudWatch) and the
   rollback dispatch mode (record-only).
3. The engine label names a model only when a model actually answered. Otherwise it
   says the brief is deterministic and why. A reply the claim guard discarded reads
   'model answer rejected (claim guard)'. Each field says whether the model wrote it
   or the deterministic template filled it (``model_fields``). An error response is
   drawn as an error.
4. It adds no stop to the hero's D-pad row, so the order the Android TV emulator run
   proved is unchanged. Its own controls sit in a section after the rollback screen.
5. A new answer or error card is scrolled up above the remote's key bar, without
   moving focus, so a second Center on 'Ask the agent' still asks again. It is only
   scrolled while the D-pad cursor is still in the deck, never so far that the focused
   control leaves the top of the screen, and again if the shared handoff the publish
   button refreshes grows above it. That refresh is a click on the page's own button;
   the cursor and the scroll position go back to where the viewer was afterwards, and
   when the call ends keyboard focus goes back to the deck control the cursor is still
   on (disabling it while the call ran had dropped focus to the page).
6. The board's own Publish handoff error card (a live row has no recorded demo
   handoff, so the server refuses it with a reason) is scrolled up above the key bar
   the same way, without moving focus, while the cursor is on Publish handoff.
"""
from __future__ import annotations

AGENT_DECK_JS = r"""(function () {
  if (document.getElementById('bedrockAgentSection')) return;
  var anchor = document.getElementById('rollback') || document.getElementById('hero');
  if (!anchor || !anchor.parentNode) return;

  function syncTvViewport() {
    if (!window.MercuryHost && window.innerWidth >= 900 && window.innerWidth < 1400 && window.innerHeight <= 600) {
      document.documentElement.classList.add('tv-host');
    }
  }
  syncTvViewport();
  window.addEventListener('resize', syncTvViewport);

  var style = document.createElement('style');
  style.textContent = [
    '#bedrockAgentSection, #bedrockAgentSection * { box-sizing:border-box; max-width:100%; overflow-wrap:anywhere; }',
    '#bedrockAgentSection .agent-pills { display:flex; flex-wrap:wrap; gap:0.5rem; margin:0.65rem 0; }',
    '#bedrockAgentSection .agent-pill { font-family:var(--mono, monospace); font-size:var(--fs-small, 1rem); padding:0.2rem 0.6rem; border:1px solid var(--rule, #2A2E37); background:var(--board, #0E1014); color:var(--ink-2, #A7B0C0); }',
    '#bedrockAgentSection .agent-pill-ok { border-color:var(--ok, #3DD68C); color:var(--ok, #3DD68C); font-weight:600; }',
    '#bedrockAgentSection .agent-pill-amber { border-color:var(--amber, #FFB23F); color:var(--amber, #FFB23F); font-weight:600; }',
    '#bedrockAgentSection .agent-card { border-top:2px solid var(--amber, #FFB23F); background:var(--flap, #14171D); padding:0.9rem 1rem; margin-top:0.75rem; }',
    '#bedrockAgentSection .agent-card-error { border-top-color:var(--critical, #FF5A5F); }',
    '#bedrockAgentSection .agent-brief-10ft { font-family:var(--display, sans-serif); font-size:var(--fs-row, 1.25rem); color:var(--ink, #F3F5F8); line-height:1.35; margin:0.4rem 0 0.6rem; }',
    '#bedrockAgentSection .agent-pre { white-space:pre-wrap; word-break:break-word; overflow-x:auto; max-width:100%; font-family:var(--mono, monospace); font-size:var(--fs-small, 1rem); padding:0.75rem; background:var(--board, #0E1014); border:1px solid var(--rule, #2A2E37); color:var(--ink-2, #A7B0C0); margin-top:0.5rem; }'
  ].join('\n');
  document.head.appendChild(style);

  function mk(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = String(text);
    return e;
  }

  function button(id, text, title) {
    var b = mk('button', 'btn', text);
    b.id = id;
    b.type = 'button';
    b.setAttribute('data-tv-focusable', '');
    b.setAttribute('data-tv-label', text);
    b.title = title;
    return b;
  }

  function activeService() {
    var btn = document.querySelector('.btn-demo[aria-pressed="true"]');
    return (btn && btn.getAttribute('data-service')) || 'checkout-api';
  }

  /* The page's own stamps: tag-fixture for anything that is not live data. */
  function dataStamp(label) {
    var text = label || 'UNLABELLED DATA';
    return mk('span', 'tag ' + (text === 'LIVE' ? 'tag-live' : 'tag-fixture'), text);
  }

  function dispatchStamp(mode) {
    return mk('span', 'tag tag-standin', 'Dispatch: ' + (mode || 'unknown'));
  }

  var sec = mk('section', 'screen');
  sec.id = 'bedrockAgentSection';
  sec.setAttribute('aria-labelledby', 'bedrockAgentTitle');

  sec.appendChild(mk('p', 'section-kicker', 'Agent deck · advisory · MCP 2025-11-25'));
  var h2 = mk('h2', null, 'Ask the agent about the selected service');
  h2.id = 'bedrockAgentTitle';
  sec.appendChild(h2);
  sec.appendChild(mk('p', 'note',
    'Nothing here runs until you press a button. The agent reads the same answer the board shows ' +
    'for the selected row, and its card carries that answer\'s own data label: OFFLINE FIXTURE for a ' +
    'simulated service; on a production function\'s row, the label says whether CloudWatch was read. ' +
    'Rollback dispatch is record-only. Each answer ' +
    'names its engine: deterministic, unless a model actually answered. A named commit is a temporal ' +
    'candidate, not proof of cause, and the correlator\'s rollback rules stay in charge.'
  ));

  var bar = mk('div', 'actions-bar');
  bar.style.marginTop = '0.85rem';
  var btnBrief = button('btnAgentBrief', 'Ask the agent',
    'Call POST /mcp/tools/agent_incident_brief once for the selected service');
  btnBrief.className = 'btn btn-primary';
  var btnPublish = button('btnAgentPublishHandoff', 'Publish recorded demo handoff',
    'Write the fixed, labelled demo handoff (record-only, no external effect) for the selected service');
  var btnMcp = button('btnAgentMcpHandshake', 'Check MCP handshake',
    'Run JSON-RPC initialize, tools/list and an agent_status call against POST /mcp');
  bar.appendChild(btnBrief);
  bar.appendChild(btnPublish);
  bar.appendChild(btnMcp);
  sec.appendChild(bar);

  // Present before any request: completion/error messages reach a screen reader
  // while keyboard focus stays on the remote control. The initial page is quiet.
  var status = mk('p', 'sr-only');
  status.id = 'bedrockAgentStatus';
  status.setAttribute('role', 'status');
  status.setAttribute('aria-live', 'polite');
  status.setAttribute('aria-atomic', 'true');
  sec.appendChild(status);

  var consoleBox = mk('div', 'console');
  consoleBox.style.marginTop = '0.85rem';
  var header = mk('div', 'console-header');
  header.appendChild(mk('span', null, 'Agent answers'));
  var latencySpan = mk('span', 'latency', 'No agent call made yet');
  latencySpan.id = 'bedrockAgentLatency';
  header.appendChild(latencySpan);
  consoleBox.appendChild(header);

  var out = mk('div');
  out.id = 'bedrockAgentOutput';
  var empty = mk('div', 'empty-state-card',
    'Select a service on the board, then press Ask the agent. No call is made until you do.'
  );
  empty.id = 'bedrockAgentEmpty';
  out.appendChild(empty);
  consoleBox.appendChild(out);
  sec.appendChild(consoleBox);

  anchor.parentNode.insertBefore(sec, anchor.nextSibling);

  function clearCard(id) {
    var old = document.getElementById('bedrockAgentEmpty');
    if (old) old.remove();
    var prev = document.getElementById(id);
    if (prev) prev.remove();
  }

  /* The remote's key bar is fixed over the bottom of the screen, and the deck sits at
     the end of the page, so a new card used to render behind it: only the console's
     header line showed. This scrolls the window, never the focus, until the card's
     first lines (its stamps, the engine pill and the brief) clear the bar, and never
     so far that the card's own top leaves the screen. */
  function keybarTop() {
    var bar = document.querySelector('.keybar');
    var view = window.innerHeight || document.documentElement.clientHeight;
    if (!bar) return view;
    var box = bar.getBoundingClientRect();
    if (!box.height || box.top >= view || getComputedStyle(bar).display === 'none') return view;
    return box.top;
  }

  /* The control the D-pad cursor is on, or null when the page has no navigator. */
  function cursor() {
    var nav = window.mercuryNav;
    return (nav && nav.current) || null;
  }

  /* Only while the viewer is still in the deck: an answer that lands after they moved
     up to the board (a slow answer, a cold start) must not scroll the screen away from
     the control they are on. And never so far that the focused control leaves the top. */
  function revealCard(card, upTo) {
    try {
      var focused = cursor();
      if (focused && !sec.contains(focused)) return;
      var gap = 16;
      var floor = keybarTop() - gap;
      var overflow = (upTo || card).getBoundingClientRect().bottom - floor;
      if (overflow <= 0) return;
      var margin = Math.max(gap, Math.round((window.innerHeight || 0) * 0.04));
      var room = card.getBoundingClientRect().top - margin;
      if (focused) room = Math.min(room, focused.getBoundingClientRect().top - margin);
      var distance = Math.min(overflow, Math.max(room, 0));
      if (distance > 0) window.scrollBy(0, distance);
    } catch (e) { /* measuring the layout must never break the deck */ }
  }

  /* Reveal again whenever the page grows something above the card for a while after
     it lands: the shared handoff the publish refreshes renders above the deck after
     the card does, and pushed it back under the key bar. */
  function keepRevealed(card, upTo, watched) {
    if (!watched || typeof MutationObserver !== 'function') return;
    var frame = 0;
    var watcher = new MutationObserver(function () {
      if (frame) return;
      var raf = window.requestAnimationFrame || function (f) { return setTimeout(f, 16); };
      frame = raf(function () {
        frame = 0;
        if (card.isConnected) revealCard(card, upTo);
      });
    });
    watcher.observe(watched, { childList: true, subtree: true, characterData: true });
    setTimeout(function () { watcher.disconnect(); }, 4000);
  }

  /* The board's own Publish handoff (docs/index.html, not edited here) brings its
     answer up above the key bar, but not its error card, which rendered behind the
     bar while the cursor stayed on Publish: a TV viewer saw only the HTTP status in
     the console header, never the reason. On a live production row that error is the
     normal answer (it has no recorded demo handoff). This scrolls the window, never
     the focus, until the card clears the bar, only while the cursor is on Publish
     handoff, and never so far that Publish handoff leaves the top of the screen. */
  function revealBoardError(card) {
    try {
      var publish = document.getElementById('btnHandoff');
      if (!publish || cursor() !== publish) return;
      var gap = 16;
      var overflow = card.getBoundingClientRect().bottom - (keybarTop() - gap);
      if (overflow <= 0) return;
      var room = publish.getBoundingClientRect().top - gap;
      var distance = Math.min(overflow, Math.max(room, 0));
      if (distance > 0) window.scrollBy(0, distance);
    } catch (e) { /* measuring the layout must never break the board */ }
  }
  var boardHandoff = document.getElementById('handoffOutput');
  if (boardHandoff && typeof MutationObserver === 'function') {
    new MutationObserver(function (records) {
      for (var i = 0; i < records.length; i++) {
        var added = records[i].addedNodes;
        for (var j = 0; j < added.length; j++) {
          var node = added[j];
          if (node.nodeType === 1 && node.classList && node.classList.contains('error-card')) {
            revealBoardError(node);
            return;
          }
        }
      }
    }).observe(boardHandoff, { childList: true });
  }

  /* Disabling a focused button drops keyboard focus to the page, and the shared
     handoff refresh is a click on the page's own button, which takes keyboard focus
     there. The D-pad cursor never left the deck control, so when its call ends, and
     only if that control had keyboard focus when it was pressed and the cursor is
     still on it, keyboard focus goes back to it: Tab and Shift+Tab then start from
     where the viewer is. It never moves the cursor to another control. */
  function keepKeyboardFocus(control, hadFocus) {
    try {
      var nav = window.mercuryNav;
      if (!hadFocus || !nav || nav.current !== control || control.disabled) return;
      if (document.activeElement === control || typeof nav.setFocus !== 'function') return;
      nav.setFocus(control);
    } catch (e) { /* focus bookkeeping must never break the deck */ }
  }

  /* An error is drawn as an error. It never borrows a brief's labels. ``said`` is the
     server's own reason when it answered with a refusal, so a refusal is shown as
     one rather than as no answer. */
  function showError(what, detail, said) {
    clearCard('card-agent-error');
    var card = mk('div', 'agent-card agent-card-error');
    card.id = 'card-agent-error';
    card.appendChild(mk('p', 'note', said
      ? 'The server refused ' + what + ': ' + detail + '. ' + said + ' Nothing was drafted or written.'
      : 'No answer from ' + what + ': ' + detail + '. Nothing was drafted or written.'));
    out.insertBefore(card, out.firstChild);
    revealCard(card);
    latencySpan.textContent = what + (said ? ' refused (' : ' failed (') + detail + ')';
    status.textContent = card.textContent;
  }

  async function postJson(url, body, headers) {
    var r = await fetch(url, {
      method: 'POST',
      headers: Object.assign({ 'Content-Type': 'application/json' }, headers || {}),
      body: JSON.stringify(body)
    });
    var data = null;
    try { data = await r.json(); } catch (e) { data = null; }
    return { ok: r.ok, status: r.status, body: data, headers: r.headers };
  }

  function enginePill(syn) {
    if (syn.synthesis_mode === 'bedrock' && syn.model_answered) {
      var ok = mk('span', 'agent-pill agent-pill-ok', 'Engine: model answered · ' + syn.model_answered);
      ok.setAttribute('data-agent-engine', 'model');
      return ok;
    }
    if (syn.fallback_reason === 'model_claim_rejected') {
      // A model did answer; its reply claimed a cause or a staged rollback and was discarded.
      var rej = mk('span', 'agent-pill agent-pill-amber', 'Engine: model answer rejected (claim guard), deterministic brief shown');
      rej.setAttribute('data-agent-engine', 'rejected');
      return rej;
    }
    var why = syn.fallback_reason ? ' (' + syn.fallback_reason + ')' : '';
    var det = mk('span', 'agent-pill agent-pill-amber', 'Engine: deterministic, no model answered' + why);
    det.setAttribute('data-agent-engine', 'deterministic');
    return det;
  }

  var briefSeq = 0;
  async function runBrief() {
    var svc = activeService();
    var mySeq = ++briefSeq;
    var hadFocus = document.activeElement === btnBrief;
    btnBrief.disabled = true;
    btnBrief.setAttribute('aria-busy', 'true');
    latencySpan.textContent = 'Asking the agent about ' + svc + '…';
    status.textContent = 'Asking the agent about ' + svc + '.';
    try {
      var t0 = performance.now();
      var res = await postJson('/mcp/tools/agent_incident_brief',
        { service_name: svc, environment: 'production', time_window_minutes: 60, prefer_bedrock: true });
      if (mySeq !== briefSeq) return;
      var elapsed = Math.round(performance.now() - t0);
      var d = res.body || {};
      if (!res.ok || !d.agent_synthesis) {
        clearCard('card-agent-brief');
        showError('agent_incident_brief', res.ok ? 'the response carried no brief' : 'HTTP ' + res.status);
        return;
      }
      var syn = d.agent_synthesis;
      var draft = syn.responder_handoff_draft || {};
      clearCard('card-agent-error');
      clearCard('card-agent-brief');

      var card = mk('div', 'agent-card');
      card.id = 'card-agent-brief';
      var stamps = mk('div', 'agent-pills');
      stamps.appendChild(dataStamp(d.data_label));
      stamps.appendChild(dispatchStamp(d.rollback_dispatch));
      card.appendChild(stamps);
      var pills = mk('div', 'agent-pills');
      pills.appendChild(mk('span', 'agent-pill agent-pill-amber', 'Service: ' + (d.service || svc)));
      pills.appendChild(enginePill(syn));
      pills.appendChild(mk('span', 'agent-pill', 'Verdict: ' + (d.verdict || 'none returned')));
      pills.appendChild(mk('span', 'agent-pill', 'Latency: ' + (syn.latency_ms || elapsed) + ' ms'));
      card.appendChild(pills);

      var byModel = syn.synthesis_mode === 'bedrock' ? (syn.model_fields || []) : [];
      function source(field) {
        return byModel.indexOf(field) >= 0 ? 'model' : 'deterministic template';
      }
      var brief = mk('p', 'agent-brief-10ft', syn.commander_brief_10ft || '');
      card.appendChild(brief);
      card.appendChild(mk('p', 'note', 'Brief above: ' + source('commander_brief_10ft') + '.'));
      card.appendChild(mk('p', 'note', 'What the evidence does and does not show (' + source('root_cause_hypothesis') + '): ' + (syn.root_cause_hypothesis || '')));
      card.appendChild(mk('p', 'note', 'Draft handoff (' + source('responder_handoff_draft') + '). Action: ' + (draft.current_action || '') + ' Next step: ' + (draft.next_step || '')));
      card.appendChild(mk('p', 'note', 'Advisory only: ' + (syn.guardrail_attestation || '')));
      out.insertBefore(card, out.firstChild);
      revealCard(card, brief);
      latencySpan.textContent = 'POST /mcp/tools/agent_incident_brief (' + svc + ') · ' + (syn.latency_ms || elapsed) + ' ms';
      status.textContent = 'Agent answer for ' + (d.service || svc) + '. '
        + (d.data_label || 'UNLABELLED DATA') + '. Dispatch: '
        + (d.rollback_dispatch || 'unknown') + '. ' + enginePill(syn).textContent
        + '. ' + brief.textContent + ' Details in Agent answers.';
    } catch (err) {
      if (mySeq === briefSeq) showError('agent_incident_brief', 'the request did not complete');
    } finally {
      if (mySeq === briefSeq) {
        btnBrief.disabled = false;
        btnBrief.setAttribute('aria-busy', 'false');
        keepKeyboardFocus(btnBrief, hadFocus);
      }
    }
  }
  btnBrief.addEventListener('click', function () { runBrief(); });

  btnPublish.addEventListener('click', async function () {
    var svc = activeService();
    var hadFocus = document.activeElement === btnPublish;
    btnPublish.disabled = true;
    latencySpan.textContent = 'Publishing the recorded demo handoff for ' + svc + '…';
    status.textContent = 'Publishing the recorded demo handoff for ' + svc + '.';
    try {
      var t0 = performance.now();
      var res = await postJson('/mcp/tools/demo_update_handoff', { service_name: svc });
      var elapsed = Math.round(performance.now() - t0);
      var d = res.body || {};
      if (!res.ok || d.revision === undefined) {
        // A live row has no recorded demo handoff, and the server says so (422).
        var said = !res.ok && typeof d.detail === 'string' ? d.detail : '';
        showError('demo_update_handoff', res.ok ? 'the response carried no revision' : 'HTTP ' + res.status, said);
        return;
      }
      var refreshBtn = document.querySelector('[data-action="handoff-refresh"]');
      if (refreshBtn) {
        /* The page refreshes its shared handoff on a click, and the navigator moves the
           cursor to whatever is clicked (and scrolls to it). The viewer is still on this
           deck, so the cursor and the screen go back where they were. */
        var before = cursor();
        var keepY = window.pageYOffset;
        refreshBtn.click();
        if (before && cursor() !== before && window.mercuryNav.setFocus) window.mercuryNav.setFocus(before);
        if (window.pageYOffset !== keepY) window.scrollTo(window.pageXOffset, keepY);
      }
      clearCard('card-agent-error');
      clearCard('card-agent-handoff');

      var card = mk('div', 'agent-card');
      card.id = 'card-agent-handoff';
      var stamps = mk('div', 'agent-pills');
      stamps.appendChild(mk('span', 'tag tag-standin', 'Recorded demo handoff'));
      stamps.appendChild(mk('span', 'tag tag-standin', 'Authorization: ' + (d.authorization_mode || 'not stated')));
      stamps.appendChild(mk('span', 'tag tag-standin', 'External effect: ' + (d.external_effect || 'not stated')));
      card.appendChild(stamps);
      var pills = mk('div', 'agent-pills');
      pills.appendChild(mk('span', 'agent-pill', 'Revision: ' + d.revision));
      pills.appendChild(mk('span', 'agent-pill', 'Incident: ' + (d.incident_id || 'not stated')));
      pills.appendChild(mk('span', 'agent-pill', 'Responder: ' + (d.responder || 'not stated')));
      pills.appendChild(mk('span', 'agent-pill', 'Write: ' + elapsed + ' ms'));
      card.appendChild(pills);
      card.appendChild(mk('p', 'note', 'This is the fixed demo handoff, not an agent draft. Current action: ' + (d.current_action || '')));
      card.appendChild(mk('p', 'note', 'Next step: ' + (d.next_step || '')));
      out.insertBefore(card, out.firstChild);
      revealCard(card, pills);
      keepRevealed(card, pills, document.getElementById('handoffOutput'));
      latencySpan.textContent = 'POST /mcp/tools/demo_update_handoff · revision ' + d.revision + ' (' + elapsed + ' ms)';
      status.textContent = 'Recorded demo handoff published for ' + svc + '. Revision '
        + d.revision + '. External effect: ' + (d.external_effect || 'not stated')
        + '. Current action: ' + (d.current_action || 'not stated')
        + '. Next step: ' + (d.next_step || 'not stated') + '.';
    } catch (err) {
      showError('demo_update_handoff', 'the request did not complete');
    } finally {
      btnPublish.disabled = false;
      keepKeyboardFocus(btnPublish, hadFocus);
    }
  });

  async function runMcp() {
    var hadFocus = document.activeElement === btnMcp;
    btnMcp.disabled = true;
    latencySpan.textContent = 'Running the MCP 2025-11-25 handshake…';
    status.textContent = 'Running the MCP handshake.';
    var mcpHeaders = { 'MCP-Protocol-Version': '2025-11-25' };
    try {
      var t0 = performance.now();
      var init = await postJson('/mcp', {
        jsonrpc: '2.0', id: 1, method: 'initialize',
        params: { protocolVersion: '2025-11-25', clientInfo: { name: 'mercury-firetv-cockpit', version: '0.2.0' }, capabilities: {} }
      });
      if (!init.ok || !init.body || !init.body.result) {
        showError('MCP initialize', init.ok ? 'no result' : 'HTTP ' + init.status);
        return;
      }
      var sessionId = init.headers.get('MCP-Session-Id') || 'stateless';
      await postJson('/mcp', { jsonrpc: '2.0', method: 'notifications/initialized', params: {} }, mcpHeaders);
      var list = await postJson('/mcp', { jsonrpc: '2.0', id: 2, method: 'tools/list', params: {} }, mcpHeaders);
      var call = await postJson('/mcp', {
        jsonrpc: '2.0', id: 3, method: 'tools/call', params: { name: 'agent_status', arguments: {} }
      }, mcpHeaders);
      var elapsed = Math.round(performance.now() - t0);
      var callResult = call.body && call.body.result;
      if (!list.ok || !call.ok || !callResult || callResult.isError) {
        showError('MCP tools', !list.ok ? 'tools/list HTTP ' + list.status
          : !call.ok ? 'tools/call HTTP ' + call.status : 'agent_status returned an error');
        return;
      }
      var tools = (list.body && list.body.result && list.body.result.tools) || [];
      clearCard('card-agent-error');
      clearCard('card-agent-mcp');

      var card = mk('div', 'agent-card');
      card.id = 'card-agent-mcp';
      var pills = mk('div', 'agent-pills');
      pills.appendChild(mk('span', 'agent-pill agent-pill-ok', 'MCP protocol: ' + init.body.result.protocolVersion));
      pills.appendChild(mk('span', 'agent-pill', 'Tools published: ' + tools.length));
      pills.appendChild(mk('span', 'agent-pill', 'Session: ' + sessionId.slice(0, 16) + '…'));
      pills.appendChild(mk('span', 'agent-pill', 'Round trip: ' + elapsed + ' ms'));
      card.appendChild(pills);
      card.appendChild(mk('p', 'note', 'Published tools (' + tools.length + '): ' + tools.map(function (t) { return t.name; }).join(', ')));
      card.appendChild(mk('pre', 'agent-pre', JSON.stringify(callResult.structuredContent || {}, null, 2)));
      out.appendChild(card);
      revealCard(card, pills);
      latencySpan.textContent = 'MCP handshake answered (' + tools.length + ' tools · ' + elapsed + ' ms)';
      status.textContent = 'MCP handshake complete. Protocol '
        + init.body.result.protocolVersion + '. ' + tools.length
        + ' tools published. Details in Agent answers.';
    } catch (err) {
      showError('MCP handshake', 'the request did not complete');
    } finally {
      btnMcp.disabled = false;
      keepKeyboardFocus(btnMcp, hadFocus);
    }
  }
  btnMcp.addEventListener('click', runMcp);
})();
"""
