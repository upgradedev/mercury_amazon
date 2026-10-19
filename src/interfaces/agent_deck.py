"""Interfaces Layer: the agent deck script served at /mcp/agent-deck.js.

The deck is appended to the cockpit page. It is quiet and it is honest:

1. It makes no call on page load and none when a departures row is selected. A call
   runs only when a viewer presses Center on a control that says what it does,
   'Ask the agent', 'Publish recorded demo handoff' or 'Check MCP handshake'.
2. Every answer card carries the data label the server returned (OFFLINE FIXTURE on
   the public deployment) and the rollback dispatch mode (record-only).
3. The engine label names a model only when a model actually answered. Otherwise it
   says the brief is deterministic and why. An error response is drawn as an error.
4. It adds no stop to the hero's D-pad row, so the order the Android TV emulator run
   proved is unchanged. Its own controls sit in a section after the rollback screen.
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
    'Nothing here runs until you press a button. The agent reads the same answer the board shows, ' +
    'so its data is the board\'s offline fixture, and rollback dispatch is record-only. Each answer ' +
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

  /* An error is drawn as an error. It never borrows a brief's labels. */
  function showError(what, detail) {
    clearCard('card-agent-error');
    var card = mk('div', 'agent-card agent-card-error');
    card.id = 'card-agent-error';
    card.appendChild(mk('p', 'note', 'No answer from ' + what + ': ' + detail + '. Nothing was drafted or written.'));
    out.insertBefore(card, out.firstChild);
    latencySpan.textContent = what + ' failed (' + detail + ')';
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
    var why = syn.fallback_reason ? ' (' + syn.fallback_reason + ')' : '';
    var det = mk('span', 'agent-pill agent-pill-amber', 'Engine: deterministic, no model answered' + why);
    det.setAttribute('data-agent-engine', 'deterministic');
    return det;
  }

  var briefSeq = 0;
  async function runBrief() {
    var svc = activeService();
    var mySeq = ++briefSeq;
    btnBrief.disabled = true;
    btnBrief.setAttribute('aria-busy', 'true');
    latencySpan.textContent = 'Asking the agent about ' + svc + '…';
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

      card.appendChild(mk('p', 'agent-brief-10ft', syn.commander_brief_10ft || ''));
      card.appendChild(mk('p', 'note', 'What the evidence does and does not show: ' + (syn.root_cause_hypothesis || '')));
      card.appendChild(mk('p', 'note', 'Draft handoff. Action: ' + (draft.current_action || '') + ' Next step: ' + (draft.next_step || '')));
      card.appendChild(mk('p', 'note', 'Advisory only: ' + (syn.guardrail_attestation || '')));
      out.insertBefore(card, out.firstChild);
      latencySpan.textContent = 'POST /mcp/tools/agent_incident_brief (' + svc + ') · ' + (syn.latency_ms || elapsed) + ' ms';
    } catch (err) {
      if (mySeq === briefSeq) showError('agent_incident_brief', 'the request did not complete');
    } finally {
      if (mySeq === briefSeq) {
        btnBrief.disabled = false;
        btnBrief.setAttribute('aria-busy', 'false');
      }
    }
  }
  btnBrief.addEventListener('click', function () { runBrief(); });

  btnPublish.addEventListener('click', async function () {
    var svc = activeService();
    btnPublish.disabled = true;
    latencySpan.textContent = 'Publishing the recorded demo handoff for ' + svc + '…';
    try {
      var t0 = performance.now();
      var res = await postJson('/mcp/tools/demo_update_handoff', { service_name: svc });
      var elapsed = Math.round(performance.now() - t0);
      var d = res.body || {};
      if (!res.ok || d.revision === undefined) {
        showError('demo_update_handoff', res.ok ? 'the response carried no revision' : 'HTTP ' + res.status);
        return;
      }
      var refreshBtn = document.querySelector('[data-action="handoff-refresh"]');
      if (refreshBtn) refreshBtn.click();
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
      latencySpan.textContent = 'POST /mcp/tools/demo_update_handoff · revision ' + d.revision + ' (' + elapsed + ' ms)';
    } catch (err) {
      showError('demo_update_handoff', 'the request did not complete');
    } finally {
      btnPublish.disabled = false;
    }
  });

  async function runMcp() {
    btnMcp.disabled = true;
    latencySpan.textContent = 'Running the MCP 2025-11-25 handshake…';
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
      latencySpan.textContent = 'MCP handshake answered (' + tools.length + ' tools · ' + elapsed + ' ms)';
    } catch (err) {
      showError('MCP handshake', 'the request did not complete');
    } finally {
      btnMcp.disabled = false;
    }
  }
  btnMcp.addEventListener('click', runMcp);
})();
"""
