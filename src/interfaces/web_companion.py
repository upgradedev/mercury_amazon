"""Web Companion HTML and Static Assets for Mercury Voice CTO Cockpit."""

COMPANION_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Mercury: Voice CTO Cockpit & DORA Radar</title>
  <style>
    :root {
      --bg: #090d16;
      --card-bg: #111827;
      --accent: #a855f7;
      --accent-hover: #9333ea;
      --text: #f9fafb;
      --text-muted: #9ca3af;
      --border: #374151;
      --success: #10b981;
      --danger: #ef4444;
      --warning: #f59e0b;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    body { background: var(--bg); color: var(--text); padding: 20px; line-height: 1.5; }
    .container { max-width: 1100px; margin: 0 auto; }
    header { border-bottom: 1px solid var(--border); padding-bottom: 15px; margin-bottom: 25px; display: flex; justify-content: space-between; align-items: center; }
    h1 { font-size: 1.8rem; color: var(--accent); }
    .badge { background: #374151; padding: 4px 10px; border-radius: 999px; font-size: 0.8rem; color: #c084fc; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
    @media (max-width: 768px) { .grid { grid-template-columns: 1fr; } }
    .card { background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; padding: 20px; }
    .card h2 { font-size: 1.2rem; margin-bottom: 15px; color: var(--accent); }
    button { background: var(--accent); color: white; border: none; padding: 10px 18px; border-radius: 6px; cursor: pointer; font-weight: 600; margin-top: 10px; transition: background 0.2s; }
    button:hover { background: var(--accent-hover); }
    .btn-secondary { background: #4b5563; margin-left: 8px; }
    .btn-secondary:hover { background: #6b7280; }
    .output-box { background: #090d16; border: 1px solid var(--border); border-radius: 6px; padding: 15px; margin-top: 15px; min-height: 120px; font-size: 0.95rem; }
    .tag { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: bold; }
    .tag-elite { background: #065f46; color: #a7f3d0; }
    .tag-anomaly { background: #991b1b; color: #fecaca; }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div>
        <h1>Mercury: Voice CTO Cockpit</h1>
        <p style="color: var(--text-muted); font-size: 0.9rem;">Amazon Alexa+ & Fire TV War Room | DORA Velocity & AWS Cost Radar</p>
      </div>
      <span class="badge">Streamable HTTP MCP Active</span>
    </header>

    <div class="grid">
      <!-- Panel 1: DORA & PR Radar -->
      <div class="card">
        <h2>1. DORA Metrics & PR Bottlenecks</h2>
        <p style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 10px;">
          Query real-time engineering velocity and review SLAs via conversational voice intelligence.
        </p>
        <div>
          <button onclick="fetchDORA()">Query DORA Velocity</button>
          <button class="btn-secondary" onclick="fetchPRBottlenecks()">Inspect Stalled PRs</button>
        </div>
        <div class="output-box" id="doraOutput">
          <span style="color: var(--text-muted);">Awaiting CTO query dispatch...</span>
        </div>
      </div>

      <!-- Panel 2: AWS Cost Radar & Rollback -->
      <div class="card">
        <h2>2. AWS Cost Radar & Governed Rollback</h2>
        <p style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 10px;">
          Detect cloud spend anomalies and safely rollback flaky services with voice tokens.
        </p>
        <div>
          <button onclick="fetchCostRadar()">Inspect Cloud Burn Rate</button>
          <button class="btn-secondary" style="background:#dc2626;" onclick="stageRollback()">Stage Rollback</button>
        </div>
        <div class="output-box" id="costOutput">
          <span style="color: var(--text-muted);">Awaiting telemetry fetch...</span>
        </div>
      </div>
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
