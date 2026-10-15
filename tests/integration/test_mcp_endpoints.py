"""Integration tests for the Mercury HTTP tool server.

Every telemetry endpoint must return provenance, because the cockpit renders it
and a judge reads it. These tests assert that contract as hard as they assert the
numbers.
"""
import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_health_reports_the_build_sha_field():
    from fastapi.testclient import TestClient

    from src.interfaces.mcp_server import app

    res = TestClient(app).get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["service"] == "mercury-firetv-cockpit"
    # build_sha may be empty outside a git checkout, but the field must exist so
    # scripts/probe_deployment.py can compare a deployment against a commit.
    assert "build_sha" in body
    assert "github_live" in body


def test_root_serves_the_cockpit_page(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "Mercury" in res.text
    assert "<title>Mercury Fire TV incident board</title>" in res.text


def test_cockpit_scripts_are_served_next_to_the_page(client):
    res = client.get("/firetv_nav.js")
    assert res.status_code == 200
    assert "mercuryNav" in res.text


def test_cockpit_script_route_refuses_path_traversal(client):
    res = client.get("/..%2f..%2fREADME.js")
    assert res.status_code in (404, 400)


def _committed_fonts():
    from src.interfaces.mcp_server import WEB_DIR

    return sorted(WEB_DIR.glob("*.woff2"))


def test_the_board_fonts_are_served_from_this_origin_as_woff2(client):
    """The page names its fonts relatively, so this server has to hand them out."""
    fonts = _committed_fonts()
    assert len(fonts) == 6
    for font in fonts:
        res = client.get(f"/{font.name}")
        assert res.status_code == 200, font.name
        assert res.headers["content-type"] == "font/woff2"
        assert res.content == font.read_bytes()
        assert res.content[:4] == b"wOF2"
        # No explicit max-age: a TV revalidates against the validator instead.
        assert res.headers.get("etag") and res.headers.get("last-modified")


def test_the_font_route_refuses_anything_that_is_not_a_committed_font(client):
    for probe in [
        "/..%2f..%2fREADME.woff2",
        "/%2e%2e%2fdocs%2fbarlow-latin-400.woff2",
        "/..%5cREADME.woff2",
        "/fonts/barlow-latin-400.woff2",
        "/not-a-font.woff2",
        "/OFL-Barlow.txt",
        "/FIRE_TV_BUILD.md",
    ]:
        assert client.get(probe).status_code == 404, probe


def test_dora_endpoint_returns_metrics_and_provenance(client):
    res = client.post("/mcp/tools/get_dora_velocity_report")
    assert res.status_code == 200
    data = res.json()
    assert data["tier"] in ["ELITE", "HIGH", "MEDIUM", "LOW"]
    assert set(data["metrics"]) == {
        "deployment_frequency_per_day", "lead_time_hours",
        "change_failure_rate_pct", "mttr_hours",
    }
    prov = data["provenance"]
    assert prov["data_source"] in ("github-api", "offline-fixture")
    assert prov["detail"]
    assert isinstance(prov["is_live"], bool)


def test_dora_endpoint_is_honest_about_fixture_mode(client):
    """With no GITHUB_TOKEN in the environment the response must say fixture."""
    data = client.post("/mcp/tools/get_dora_velocity_report").json()
    assert data["provenance"]["data_source"] == "offline-fixture"
    assert data["provenance"]["display_label"] == "OFFLINE FIXTURE"
    assert data["provenance"]["is_live"] is False


def test_pr_bottlenecks_endpoint_returns_counts_and_provenance(client):
    data = client.post("/mcp/tools/get_pr_bottlenecks").json()
    assert data["total_open"] >= 0
    assert data["stale_count"] >= len(data["stale_prs"])
    assert "provenance" in data


def test_cost_endpoint_returns_spend_and_provenance(client):
    data = client.post("/mcp/tools/get_aws_cost_anomalies").json()
    assert data["month_to_date_usd"] >= 0
    assert data["provenance"]["data_source"] in ("aws-cost-explorer", "offline-fixture")


def test_what_changed_returns_a_verdict_and_both_provenances(client):
    res = client.post("/mcp/tools/what_changed", json={"service_name": "checkout-api"})
    assert res.status_code == 200
    data = res.json()
    assert data["verdict"] in (
        "NO_ANOMALY", "ANOMALY_ATTRIBUTED", "ANOMALY_WITHOUT_ATTRIBUTION", "INSUFFICIENT_DATA",
    )
    assert data["explanation"]
    assert "metric_provenance" in data
    assert "commit_provenance" in data


def test_what_changed_falls_back_to_real_local_commits_not_invented_ones(client):
    """Without a GitHub token the commits come from git log, and say so."""
    data = client.post("/mcp/tools/what_changed", json={"service_name": "checkout-api"}).json()

    assert data["commit_provenance"]["data_source"] in ("local-git", "offline-fixture")
    if data["commit_provenance"]["data_source"] == "local-git":
        assert "git log" in data["commit_provenance"]["detail"]
        assert "not the service being monitored" in data["commit_provenance"]["detail"]
        assert data["offending_commit"]["sha"]
    else:
        # No checkout available: nothing may be blamed.
        assert data["offending_commit"] is None
        assert data["recommended_action"] is None


def test_the_metric_behind_a_correlation_is_never_claimed_to_be_live_offline(client):
    """The commits may be real while the metric is simulated. The split must show."""
    data = client.post("/mcp/tools/what_changed", json={"service_name": "checkout-api"}).json()
    assert data["metric_provenance"]["is_live"] is False
    assert data["metric_provenance"]["display_label"] == "OFFLINE FIXTURE"
    assert "never read from" in data["metric_provenance"]["detail"]


def test_an_anchored_simulation_says_it_was_anchored(client):
    """Moving a simulated point to fit a commit must be disclosed, not hidden."""
    data = client.post("/mcp/tools/what_changed", json={"service_name": "checkout-api"}).json()
    assert data["offending_commit"] is not None
    detail = data["metric_provenance"]["detail"]
    # Which commit the reading is placed after is itself a choice, so the sentence
    # has to name the rule that chose it, not merely admit that something moved.
    assert "placed" in detail
    # The window is the correlator's own, 75 minutes since 2026-09-27.
    assert "alone in its 75 minute attribution window" in detail
    assert "the commit stamp beside this answer says they are, and this metric is generated" in detail
    # docs/EVIDENCE.md quotes this sentence as what the evidence panel shows, so the
    # quote has to be the sentence the server sends, not an older wording of it.
    sent = re.search(r"The final reading is placed .*?this metric is generated\.", detail).group(0)
    evidence = (REPO_ROOT / "docs" / "EVIDENCE.md").read_text(encoding="utf-8")
    quoted = " ".join(line[2:] for line in evidence.splitlines() if line.startswith("> "))
    assert sent in " ".join(quoted.split()), "docs/EVIDENCE.md quotes a provenance sentence the server no longer sends"


def test_the_five_demo_services_reach_the_five_verdicts_the_readme_promises(client):
    """The README's demo table, driven against this repository's recorded git log window.

    This used to be conditional: the anchored-simulation test above only asserted
    anything ``if data["offending_commit"] is not None``, so the day checkout-api
    stopped attributing, the table in the README would have gone stale with the suite
    still green. It could stop attributing: which commit the fixture anchors to was
    chosen from git log at HEAD, which grows every time somebody commits. The window is
    now recorded at one merge (tests/unit/test_local_git_window.py shows new commits
    cannot move it).

    So the verdicts are asserted, not conditioned on. If a re-recorded window ever makes
    a demo row unreachable, this fails and the README is corrected rather than quietly
    wrong.
    """
    expected = {
        "checkout-api": ("ANOMALY_ATTRIBUTED", None),
        "release-train": ("ANOMALY_WITHOUT_ATTRIBUTION", "WINDOW_TOO_CROWDED"),
        "search-indexer": ("ANOMALY_WITHOUT_ATTRIBUTION", "NO_CANDIDATE_IN_WINDOW"),
        "payments-worker": ("NO_ANOMALY", None),
        "quiet-service": ("INSUFFICIENT_DATA", None),
    }
    for service, (verdict, refusal) in expected.items():
        data = client.post("/mcp/tools/what_changed", json={"service_name": service}).json()
        assert data["verdict"] == verdict, (
            f"{service} returned {data['verdict']}, not the {verdict} the README's demo "
            f"table promises. The fixture anchors to the recorded git log window, so a "
            f"re-recorded window (scripts/record_local_git_window.py) can move this: fix the "
            f"anchoring, the recording or the table, not this test."
        )
        assert data["attribution"]["refusal_reason"] == refusal, service
        # Correlation alone never creates a rollback target. Even an attributed
        # row needs authenticated deployment evidence and a matching health readback.
        assert data["recommended_action"] is None, service
        if verdict == "ANOMALY_ATTRIBUTED":
            assert data["deployment_evidence"]["blocked_reason"]


def test_recorded_demo_markers_create_an_honest_record_only_dpad_path(client):
    from src.infrastructure.demo_evidence import seed_recorded_demo_evidence
    from src.interfaces import mcp_server

    seed_recorded_demo_evidence(mcp_server.incident_use_case, mcp_server.deployment_evidence)
    changed = client.post("/mcp/tools/what_changed", json={"service_name": "checkout-api"}).json()
    assert changed["recommended_action"] is not None
    assert changed["deployment_evidence"]["mode"] == "OFFLINE_RECORDED_DEMO"
    assert changed["commit_provenance"]["data_source"] in {"local-git", "offline-fixture"}
    assert "not deployments of checkout-api" in changed["recommended_action"]["note"]

    rec = changed["recommended_action"]
    staged = client.post("/mcp/tools/demo_stage_rollback", json={
        "action_id": "tv-demo-integration",
        "target_service": rec["target_service"],
        "target_commit_sha": rec["target_commit_sha"],
        "environment": rec["environment"],
        "target_artifact_sha256": rec["target_artifact_sha256"],
        "target_deployment_marker_id": rec["target_deployment_marker_id"],
        "offending_deployment_marker_id": rec["offending_deployment_marker_id"],
        "reason": "Recorded fixture journey; no deployment system is contacted.",
        "lease_sec": 300,
    })
    assert staged.status_code == 200
    assert staged.json()["authorization_mode"] == "DPAD_RECORD_ONLY_DEMO"
    confirmed = client.post("/mcp/tools/demo_confirm_rollback", json={
        "action_id": staged.json()["action_id"],
        "governance_token": staged.json()["governance_token"],
    })
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "RECORDED_ONLY"
    assert confirmed.json()["external_effect"] == "NONE"

    handoff = client.post("/mcp/tools/demo_update_handoff", json={"expected_revision": 0})
    assert handoff.status_code == 200
    assert handoff.json()["incident_id"] == "checkout-api-active"
    assert handoff.json()["authorization_mode"] == "DPAD_RECORD_ONLY_DEMO"
    assert handoff.json()["external_effect"] == "NONE"
    assert "record-only" in handoff.json()["next_step"]
    refreshed = client.get("/mcp/demo-handoff")
    assert refreshed.status_code == 200
    assert refreshed.json()["revision"] == handoff.json()["revision"]


def test_demo_handoff_confirmed_facts_use_candidate_language(client):
    """Confirmed facts must not state a cause the product cannot prove.

    The second fact used to read "ANOMALY_ATTRIBUTED: ...", the raw verdict
    enum, while the hero, tile, rows and announcement all say "Temporal
    candidate". The fact now carries the same qualifier in the
    explanation's own "closest change" words. Commit, author and window
    come from the live diagnosis in this test, so fixture rotation cannot
    break the pin; the wording around them is exact.
    """
    from src.infrastructure.demo_evidence import seed_recorded_demo_evidence
    from src.interfaces import mcp_server

    seed_recorded_demo_evidence(mcp_server.incident_use_case, mcp_server.deployment_evidence)
    correlation = mcp_server.incident_use_case.execute("checkout-api", 60)
    revision = client.get("/mcp/demo-handoff/revision").json()["revision"]
    handoff = client.post(
        "/mcp/tools/demo_update_handoff", json={"expected_revision": revision}
    )
    assert handoff.status_code == 200
    facts = handoff.json()["confirmed_facts"]
    assert len(facts) == 3
    assert not any("ANOMALY_ATTRIBUTED" in fact for fact in facts)
    offending = correlation.offending_commit
    assert facts[1] == (
        f"Temporal candidate, not proof of cause: commit {offending.sha} by "
        f"{offending.author} is the closest change inside "
        f"{correlation.attribution_window_minutes} minute attribution window."
    )


def test_demo_handoff_is_fixed_and_disabled_when_effectful_dispatch_is_selected(client, monkeypatch):
    from src.interfaces import mcp_server

    class ArmedDispatcher:
        armed = True
        repository = "example/repo"
        workflow = "rollback.yml"
        ref = "main"
        disarm_reason = ""

    monkeypatch.setattr(mcp_server, "rollback_dispatcher", ArmedDispatcher())
    refused = client.post("/mcp/tools/demo_update_handoff", json={"expected_revision": 0})
    assert refused.status_code == 403


def test_a_second_screen_can_read_the_demo_handoff_revision_before_it_writes(client):
    """The shared handoff refuses a stale revision, so a writer has to be able to read it.

    Before this route existed the page sent revision 0 on every load, so once anyone had
    published, every later screen that pressed Publish was refused with a 409. Nothing
    having been published is revision 0 and answers 200, not 404, so the read is not an
    error in the browser console.
    """
    from src.infrastructure.demo_evidence import seed_recorded_demo_evidence
    from src.interfaces import mcp_server

    seed_recorded_demo_evidence(mcp_server.incident_use_case, mcp_server.deployment_evidence)
    before = client.get("/mcp/demo-handoff/revision")
    assert before.json()["revision"] == 0, "nothing published yet reads as revision 0"
    assert before.status_code == 200
    revision = before.json()["revision"]
    assert revision >= 0

    first = client.post("/mcp/tools/demo_update_handoff", json={"expected_revision": revision})
    assert first.status_code == 200
    after = client.get("/mcp/demo-handoff/revision").json()["revision"]
    assert after == revision + 1

    stale = client.post("/mcp/tools/demo_update_handoff", json={"expected_revision": revision})
    assert stale.status_code == 409, "a stale revision is still refused; the read does not weaken it"
    second = client.post("/mcp/tools/demo_update_handoff", json={"expected_revision": after})
    assert second.status_code == 200
    assert second.json()["revision"] == after + 1


def test_the_operator_handoff_revision_read_needs_the_secret_and_starts_at_zero(client, auth_headers):
    refused = client.get("/mcp/handoffs/never-published-incident/revision")
    assert refused.status_code in (401, 403)
    empty = client.get("/mcp/handoffs/never-published-incident/revision", headers=auth_headers)
    assert empty.status_code == 200
    assert empty.json()["revision"] == 0


def test_the_crowded_refusal_says_which_commit_it_was_anchored_to_and_why(client):
    """The demo that shows the refusal has to disclose its own staging too."""
    data = client.post("/mcp/tools/what_changed", json={"service_name": "release-train"}).json()
    assert data["verdict"] == "ANOMALY_WITHOUT_ATTRIBUTION"
    assert data["attribution"]["refusal_reason"] == "WINDOW_TOO_CROWDED"
    assert data["attribution"]["commits_in_window"] > 1
    assert data["offending_commit"] is None
    assert data["recommended_action"] is None
    detail = data["metric_provenance"]["detail"]
    assert "the commit with the most company" in detail
    assert "the commit stamp beside this answer says they are, and this metric is generated" in detail
    assert "cannot attribute it to any one of them" in data["voice_summary"]
    assert "rolling back on this answer would be a guess" in data["voice_summary"]


def test_every_answer_carries_the_measured_worth_of_naming_a_commit(client):
    """An attribution ships the precision it was measured at, next to the name.

    The figure comes from attribution_holdout_summary.json, which
    ``python scripts/attribution_split.py`` writes: the shipped engine's precision on
    the held-out split, so the number on the wire is the number in the README rather
    than one recomputed per request, and not the in-sample figure it replaced.
    """
    data = client.post("/mcp/tools/what_changed", json={"service_name": "checkout-api"}).json()
    accuracy = data["attribution"]["measured_accuracy"]
    assert accuracy["measured_by_command"] == "python scripts/attribution_split.py"
    if accuracy["measured"]:
        summary = json.loads((REPO_ROOT / "attribution_holdout_summary.json").read_text(encoding="utf-8"))
        held = next(r for r in summary["engines"] if r["engine"] == summary["shipped_engine"])["held_out"]
        assert accuracy["split"] == "held-out"
        assert accuracy["precision_when_it_names_a_commit"] == held["naming_precision"]
        assert accuracy["namings_measured"] == held["times_a_commit_was_named"]
        assert accuracy["corpus_cases"] == held["cases"]
    else:
        assert accuracy["precision_when_it_names_a_commit"] is None
        assert "no measured accuracy" in accuracy["note"]


def test_what_changed_reports_how_many_changes_were_candidates(client):
    """The count the correlation trial argued for has to reach the wire.

    Against the labelled corpus in ``scripts/correlation_trial.py`` every wrong attribution
    whose real cause was inside the attribution window was a window holding more than one
    change, so the number of candidates is part of the answer rather than a log line.
    """
    data = client.post("/mcp/tools/what_changed", json={"service_name": "checkout-api"}).json()
    attribution = data["attribution"]
    assert isinstance(attribution["commits_in_window"], int)
    assert attribution["commits_in_window"] >= 0

    if data["verdict"] == "ANOMALY_ATTRIBUTED":
        assert attribution["commits_in_window"] >= 1
        assert attribution["is_ambiguous"] == (attribution["commits_in_window"] > 1)
        if attribution["is_ambiguous"]:
            assert "It is not the only candidate" in data["explanation"]
    else:
        # Nothing was named, so there is nothing to be ambiguous about.
        assert attribution["is_ambiguous"] is False


def test_a_verdict_that_names_nobody_claims_no_candidates(client):
    """The two refusals must not report a candidate they did not act on."""
    for service in ("payments-worker", "search-indexer", "quiet-service"):
        data = _what_changed(client, service)
        assert data["offending_commit"] is None
        assert data["attribution"]["commits_in_window"] == 0
        assert data["attribution"]["is_ambiguous"] is False


def _certainty_violations(text: str) -> list[str]:
    from src.domain.incident_correlation import REFUSAL_MUST_NOT_CLAIM

    flat = " ".join((text or "").split())
    return [pattern for pattern in REFUSAL_MUST_NOT_CLAIM if re.search(pattern, flat, re.IGNORECASE)]


def test_a_refusal_on_the_wire_is_a_refusal_and_not_an_acquittal(client):
    """The three refusing demo services, as the cockpit receives them.

    Each has to say Mercury cannot attribute, and why, and none of them may carry the
    certainty phrasing the domain forbids or claim that nothing needs reverting. That
    last flag is the one a downstream consumer would key on, so it is asserted by name.
    """
    for service in ("release-train", "search-indexer", "quiet-service"):
        data = _what_changed(client, service)
        attribution = data["attribution"]
        assert attribution["can_attribute"] is False, service
        assert attribution["nothing_to_revert"] is False, (
            f"{service} returned {data['verdict']} with nothing_to_revert true; only "
            "NO_ANOMALY may say that"
        )
        assert attribution["refusal_statement"], f"{service} ships no refusal statement"
        assert "cannot attribute" in attribution["refusal_statement"], service
        for field in ("refusal_statement", "voice_summary", "explanation"):
            text = attribution[field] if field == "refusal_statement" else data[field]
            assert not _certainty_violations(text), f"{service}.{field} states a certainty: {text!r}"
        assert data["recommended_action"] is None, service


def test_only_the_steady_service_says_nothing_needs_reverting(client):
    steady = _what_changed(client, "payments-worker")
    assert steady["verdict"] == "NO_ANOMALY"
    assert steady["attribution"]["nothing_to_revert"] is True
    assert steady["attribution"]["can_attribute"] is False
    assert steady["attribution"]["refusal_statement"] is None

    named = _what_changed(client, "checkout-api")
    assert named["verdict"] == "ANOMALY_ATTRIBUTED"
    assert named["attribution"]["can_attribute"] is True
    assert named["attribution"]["nothing_to_revert"] is False
    assert named["attribution"]["refusal_statement"] is None


def test_what_changed_rejects_an_out_of_range_window(client):
    assert client.post("/mcp/tools/what_changed", json={"time_window_minutes": 99999}).status_code == 422
    assert client.post("/mcp/tools/what_changed", json={"time_window_minutes": 1}).status_code == 422


def test_observability_audit_reports_missing_signals(client):
    res = client.post("/mcp/tools/audit_observability", json={
        "service_name": "checkout-api",
        "received_signals": ["error_rate", "emf_logs"],
    })
    assert res.status_code == 200
    data = res.json()
    assert data["is_fully_observable"] is False
    assert "p95_latency" in data["missing_signals"]
    assert 0 < data["observability_gap_score"] <= 1


def test_every_response_carries_a_request_id_header(client):
    res = client.get("/health")
    assert res.headers.get("X-Mercury-Request-Id")


def test_devops_event_feed_starts_empty_and_accepts_authorized_events(client, auth_headers):
    res = client.post("/webhooks/github/workflow_run", headers=auth_headers, json={
        "repository": "acme/widgets", "workflow_name": "ci.yml", "conclusion": "failure",
    })
    assert res.status_code == 200
    assert res.json()["status"] == "FAILURE"

    feed = client.get("/mcp/events/devops").json()
    assert feed["total"] >= 1
    assert feed["events"][0]["source"] == "GitHub_Actions"


def test_webhook_ingest_requires_authorization(client):
    res = client.post("/webhooks/github/workflow_run", json={
        "repository": "acme/widgets", "workflow_name": "ci.yml", "conclusion": "success",
    })
    assert res.status_code == 401


# -------------------------------------- Every verdict is reachable from the API
#
# The defect these close: the simulated metric series came from two module
# constants, so every service name returned the same 34x factor. The correlator's
# NO_ANOMALY and ANOMALY_WITHOUT_ATTRIBUTION verdicts had unit tests but no input
# a reviewer could supply ever reached them over HTTP. These drive the four
# verdicts through the endpoint the cockpit calls.

DEMO_SERVICES = ["checkout-api", "payments-worker", "search-indexer"]


def _what_changed(client, service_name):
    res = client.post("/mcp/tools/what_changed", json={"service_name": service_name})
    assert res.status_code == 200
    return res.json()


def test_the_metric_series_is_not_the_same_for_every_service(client):
    readings = {
        name: (_what_changed(client, name)["metric"]["baseline"],
               _what_changed(client, name)["metric"]["current"])
        for name in DEMO_SERVICES
    }
    assert len(set(readings.values())) == len(DEMO_SERVICES), (
        f"the simulated series does not depend on the service: {readings}"
    )


def test_the_demo_services_reach_three_different_verdicts(client):
    verdicts = {name: _what_changed(client, name)["verdict"] for name in DEMO_SERVICES}
    commits_available = (
        _what_changed(client, "checkout-api")["commit_provenance"]["data_source"]
        in ("local-git", "github-api")
    )

    assert verdicts["payments-worker"] == "NO_ANOMALY"
    assert verdicts["search-indexer"] == "ANOMALY_WITHOUT_ATTRIBUTION"
    if commits_available:
        assert verdicts["checkout-api"] == "ANOMALY_ATTRIBUTED"
        assert len(set(verdicts.values())) == 3
    else:
        # No checkout and no token: nothing can be attributed, and the correlator
        # must say so rather than blaming something.
        assert verdicts["checkout-api"] == "ANOMALY_WITHOUT_ATTRIBUTION"


def test_the_steady_service_is_refused_on_the_factor_not_on_missing_data(client):
    """A zero baseline would also produce NO_ANOMALY. Prove it is the threshold."""
    data = _what_changed(client, "payments-worker")
    metric = data["metric"]
    assert metric["baseline"] > 0
    assert metric["sample_size"] >= 2
    assert 1.0 < metric["anomaly_factor"] < 3.0
    assert "below the 3.0x threshold" in data["explanation"]
    assert data["recommended_action"] is None
    assert data["offending_commit"] is None


def test_the_unattributed_service_had_commits_available_and_still_blamed_nothing(client):
    """The refusal must come from the attribution window, not from an empty history."""
    data = _what_changed(client, "search-indexer")
    if data["commit_provenance"]["data_source"] not in ("local-git", "github-api"):
        pytest.skip("no commit history is reachable here, so the window cannot be the reason")

    assert data["verdict"] == "ANOMALY_WITHOUT_ATTRIBUTION"
    assert data["metric"]["anomaly_factor"] >= 3.0
    assert data["offending_commit"] is None
    assert data["recommended_action"] is None
    assert "no commit landed in the" in data["explanation"]
    assert "deliberately outside" in data["metric_provenance"]["detail"]


def test_an_unknown_service_is_refused_rather_than_given_an_invented_incident(client):
    data = _what_changed(client, "quiet-service")
    assert data["verdict"] == "INSUFFICIENT_DATA"
    assert data["incident_detected"] is False
    assert data["metric"]["sample_size"] == 0
    assert data["metric"]["current"] == 0.0
    assert data["recommended_action"] is None
    assert "does not invent a reading" in data["metric_provenance"]["detail"]


def test_the_cockpit_offers_exactly_the_services_the_fixture_knows(client):
    """The demo buttons on the page and the fixture must not drift apart."""
    from pathlib import Path

    from src.infrastructure.cloudwatch_adapter import SIMULATED_SERVICES
    from src.infrastructure.demo_evidence import seed_recorded_demo_evidence
    from src.interfaces.mcp_server import deployment_evidence, incident_use_case

    page = (Path(__file__).resolve().parent.parent.parent / "docs" / "index.html").read_text(
        encoding="utf-8"
    )
    offered = set(re.findall(r'data-service="([^"]+)"', page))
    assert set(SIMULATED_SERVICES) < offered, (
        f"the cockpit does not offer every known service: {set(SIMULATED_SERVICES) - offered}"
    )
    unknown = offered - set(SIMULATED_SERVICES)
    assert len(unknown) == 1, (
        f"the cockpit must offer exactly one name the fixture refuses, found {sorted(unknown)}"
    )
    seed_recorded_demo_evidence(incident_use_case, deployment_evidence)
    for service in ("checkout-api", "payments-worker", "search-indexer", "release-train", "quiet-service"):
        rev = client.get("/mcp/demo-handoff/revision").json()["revision"]
        res = client.post(
            "/mcp/tools/demo_update_handoff",
            json={"expected_revision": rev, "service_name": service},
        )
        assert res.status_code == 200, f"{service}: {res.text}"
        body = res.json()
        assert body["authorization_mode"] == "DPAD_RECORD_ONLY_DEMO"
        assert body["revision"] == rev + 1
        if service != "checkout-api":
            assert service in body["current_action"]
            assert any(service in fact for fact in body["confirmed_facts"])



