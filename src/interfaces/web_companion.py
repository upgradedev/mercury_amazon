"""Web Companion HTML and Static Assets for Mercury Voice CTO Cockpit (Fire TV & Alexa+)."""

COMPANION_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Mercury: Fire TV & Voice CTO War Room</title>
  <style>
    :root {
      --bg: #090d16;
      --card-bg: #111827;
      --card-focus: #1f2937;
      --accent: #a855f7;
      --accent-hover: #9333ea;
      --text: #f9fafb;
      --text-muted: #9ca3af;
      --border: #374151;
      --focus-border: #38bdf8;
      --success: #10b981;
      --danger: #ef4444;
      --warning: #f59e0b;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    body { background: var(--bg); color: var(--text); padding: 24px; line-height: 1.5; font-size: 18px; }
    .container { max-width: 1400px; margin: 0 auto; }
    header { border-bottom: 2px solid var(--border); padding-bottom: 20px; margin-bottom: 30px; display: flex; justify-content: space-between; align-items: center; }
    h1 { font-size: 2.2rem; color: var(--accent); letter-spacing: -0.5px; }
    .badge { background: #374151; padding: 6px 14px; border-radius: 999px; font-size: 0.9rem; color: #c084fc; font-weight: 600; }
    .tv-mode-badge { background: #0369a1; color: #bae6fd; margin-right: 8px; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 28px; }
    @media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }
    .card { background: var(--card-bg); border: 2px solid var(--border); border-radius: 12px; padding: 24px; transition: transform 0.2s, border-color 0.2s; }
    .card:focus-within, .card.tv-focused { border-color: var(--focus-border); transform: scale(1.01); background: var(--card-focus); }
    .card h2 { font-size: 1.5rem; margin-bottom: 15px; color: var(--accent); }
    button { background: var(--accent); color: white; border: 2px solid transparent; padding: 14px 24px; border-radius: 8px; cursor: pointer; font-weight: 700; font-size: 1rem; margin-top: 12px; transition: all 0.2s; outline: none; }
    button:hover, button:focus { background: var(--accent-hover); border-color: var(--focus-border); box-shadow: 0 0 12px rgba(56, 189, 248, 0.4); }
    .btn-secondary { background: #4b5563; margin-left: 10px; }
    .btn-secondary:hover, .btn-secondary:focus { background: #6b7280; }
    .output-box { background: #090d16; border: 1px solid var(--border); border-radius: 8px; padding: 18px; margin-top: 20px; min-height: 140px; font-size: 1.05rem; }
    .tag { display: inline-block; padding: 4px 10px; border-radius: 6px; font-size: 0.85rem; font-weight: bold; }
    .tag-elite { background: #065f46; color: #a7f3d0; }
    .tag-anomaly { background: #991b1b; color: #fecaca; }
    .keyboard-nav-hint { margin-top: 24px; text-align: center; color: var(--text-muted); font-size: 0.85rem; }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div>
        <h1>Mercury: Big Screen CTO War Room</h1>
        <p style="color: var(--text-muted); font-size: 1.1rem; margin-top: 4px;">Amazon Fire TV & Alexa+ | DORA Velocity Radar & AWS Cloud Cost Cockpit</p>
      </div>
      <div>
        <span class="badge tv-mode-badge">Fire TV 10-Foot UI</span>
        <span class="badge">Streamable HTTP MCP Active</span>
      </div>
    </header>

    <div class="grid">
      <!-- Panel 1: DORA & PR Radar -->
      <div class="card" id="card1" tabindex="0">
        <h2>1. DORA Metrics & PR Bottlenecks</h2>
        <p style="font-size: 0.95rem; color: var(--text-muted); margin-bottom: 14px;">
          Query real-time engineering velocity and review SLAs via conversational voice or D-Pad navigation.
        </p>
        <div>
          <button id="btnDora" onclick="fetchDORA()">Query DORA Velocity</button>
          <button id="btnPr" class="btn-secondary" onclick="fetchPRBottlenecks()">Inspect Stalled PRs</button>
        </div>
        <div class="output-box" id="doraOutput">
          <span style="color: var(--text-muted);">Awaiting CTO query dispatch...</span>
        </div>
      </div>

      <!-- Panel 2: AWS Cost Radar & Rollback -->
      <div class="card" id="card2" tabindex="0">
        <h2>2. AWS Cost Radar & Governed Rollback</h2>
        <p style="font-size: 0.95rem; color: var(--text-muted); margin-bottom: 14px;">
          Detect cloud spend anomalies and safely stage rollbacks with 300-second voice token leases.
        </p>
        <div>
          <button id="btnCost" onclick="fetchCostRadar()">Inspect Cloud Burn Rate</button>
          <button id="btnRollback" class="btn-secondary" style="background:#dc2626;" onclick="stageRollback()">Stage Rollback</button>
        </div>
        <div class="output-box" id="costOutput">
          <span style="color: var(--text-muted);">Awaiting telemetry fetch...</span>
        </div>
      </div>
    </div>

    <div class="keyboard-nav-hint">
      📺 <strong>Fire TV Remote / Keyboard Navigation:</strong> Use [TAB] or Arrow Keys to navigate cards, [ENTER] to execute actions.
    </div>
  </div>

  <script>
    async function fetchDORA() {
      document.getElementById('doraOutput').innerHTML = '<span style="color:#a855f7;">Calculating DORA metrics...</span>';
      try {
        const res = await fetch('/mcp/tools/get_dora_velocity_report', { method: 'POST' });
        const data = await res.json();
        let html = '<strong>Tier:</strong> <span class="tag tag-elite">' + data.tier + '</span><br>' +
                   '<strong>Voice Digest:</strong> ' + data.voice_summary + '<br><br>' +
                   'Deploy Frequency: ' + data.metrics.deployment_frequency_per_day + '/day | ' +
                   'Lead Time: ' + data.metrics.lead_time_hours + 'h | ' +
                   'Change Failure Rate: ' + data.metrics.change_failure_rate_pct + '%';
        document.getElementById('doraOutput').innerHTML = html;
      } catch (err) {
        document.getElementById('doraOutput').innerHTML = '<span style="color:#ef4444;">Error: ' + err.message + '</span>';
      }
    }

    async function fetchPRBottlenecks() {
      document.getElementById('doraOutput').innerHTML = '<span style="color:#a855f7;">Inspecting PR radar...</span>';
      try {
        const res = await fetch('/mcp/tools/get_pr_bottlenecks', { method: 'POST' });
        const data = await res.json();
        let html = '<strong>Voice Digest:</strong> ' + data.voice_summary + '<br>' +
                   '<strong>Total Open:</strong> ' + data.total_open + '<br>';
        data.stale_prs.forEach(pr => {
          html += '<div>⚠️ #' + pr.id + ' (' + pr.repo + '): "' + pr.title + '" — Open ' + pr.hours_open + 'h</div>';
        });
        document.getElementById('doraOutput').innerHTML = html;
      } catch (err) {
        document.getElementById('doraOutput').innerHTML = '<span style="color:#ef4444;">Error: ' + err.message + '</span>';
      }
    }

    async function fetchCostRadar() {
      document.getElementById('costOutput').innerHTML = '<span style="color:#a855f7;">Scanning AWS Cost Explorer...</span>';
      try {
        const res = await fetch('/mcp/tools/get_aws_cost_anomalies', { method: 'POST' });
        const data = await res.json();
        let html = '<strong>Voice Digest:</strong> ' + data.voice_summary + '<br>' +
                   '<strong>Month-to-Date:</strong> $' + data.month_to_date_usd.toFixed(2) + '<br>' +
                   '<strong>Projected EOM:</strong> $' + data.projected_usd.toFixed(2) + '<br>';
        data.anomalies.forEach(a => {
          html += '<div style="margin-top:6px;"><span class="tag tag-anomaly">Surge +' + a.increase_pct + '%</span> ' + a.service + ': ' + a.root_cause + '</div>';
        });
        document.getElementById('costOutput').innerHTML = html;
      } catch (err) {
        document.getElementById('costOutput').innerHTML = '<span style="color:#ef4444;">Error: ' + err.message + '</span>';
      }
    }

    async function stageRollback() {
      document.getElementById('costOutput').innerHTML = '<span style="color:#f59e0b;">Staging production rollback action...</span>';
      try {
        const res = await fetch('/mcp/tools/stage_rollback', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            action_id: 'rb_' + Date.now(),
            target_service: 'backend-payments',
            target_commit_sha: 'a8f3b9c2e',
            reason: 'High change failure rate and latency spike'
          })
        });
        const data = await res.json();
        document.getElementById('costOutput').innerHTML = 
          '<strong>Rollback Staged:</strong> ' + data.action_id + '<br>' +
          '<strong>Target:</strong> ' + data.target_service + ' @ ' + data.target_commit_sha + '<br>' +
          '<strong>State:</strong> ' + data.state + '<br>' +
          '<strong>Spoken Prompt:</strong> ' + data.spoken_prompt;
      } catch (err) {
        document.getElementById('costOutput').innerHTML = '<span style="color:#ef4444;">Error: ' + err.message + '</span>';
      }
    }
  </script>
</body>
</html>
"""
