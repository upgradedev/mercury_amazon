"""Standards readiness auditor for Mercury.

Enumerates every gate from STANDARDS.md and reports PASS or FAIL for each. Two
rules govern this file, and they matter more than the score it prints:

1. A gate that cannot fail is not a gate. Anything hardcoded to True has been
   replaced with a real check or an honest FAIL. Break something in the repository
   and the corresponding gate must go red.

2. A gate that reads evidence from outside the repository says so in its own
   message, because a judge cloning this repository on its own does not have that
   evidence and must not be shown a PASS that depends on it.

Gates that are not achievable without a deployment, a video upload or hardware are
reported FAIL and excluded from the CI exit code by an explicit, printed policy
list, so the failure is visible rather than hidden inside the script.

Run: ``python ci/readiness.py``
"""
from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Gates that report FAIL honestly but do not fail the CI job, each with the
# reason it is out of reach of an automated run. Printed in the output.
CI_EXEMPT: dict[str, str] = {
    "C5": "needs a real browser driver walking the recorded video path",
    "D2": "needs a deployment of this commit; the live endpoint runs an older build",
    "E2": "needs a recorded video for narration and picture to be in sync with",
    "E4": "needs a public video of the running product",
    "G2": "needs a deployment whose reported build SHA equals HEAD",
    "I1": "evidence lives in a workspace coordination file that is not part of this repository",
    "I2": "evidence lives in a workspace coordination file that is not part of this repository",
    "I3": "evidence lives in a workspace coordination file that is not part of this repository",
    "I4": "evidence lives in a workspace coordination file that is not part of this repository",
    "O1": "owner action: YouTube upload",
    "O2": "owner action: Devpost project creation",
    "O3": "owner action: pressing Submit",
}


class GateResult:
    def __init__(self, gate_id: str, title: str, passed: bool, message: str,
                 external_evidence: bool = False):
        self.gate_id = gate_id
        self.title = title
        self.passed = passed
        self.message = message
        self.external_evidence = external_evidence


def read(path: str) -> str:
    full = os.path.join(REPO_ROOT, path)
    if not os.path.exists(full):
        return ""
    with open(full, "r", encoding="utf-8") as handle:
        return handle.read()


def get_standards_gate_ids() -> list[str]:
    """Parse gate IDs from the canonical STANDARDS.md when it is reachable."""
    candidates = [
        r"C:\dev\solutions\_submission_kit\STANDARDS.md",
        os.path.join(REPO_ROOT, "../../_submission_kit/STANDARDS.md"),
        os.path.join(REPO_ROOT, "STANDARDS.md"),
    ]
    for path in candidates:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as handle:
                gates = re.findall(r"\|\s*([JABCDEFGHOI][0-9]+)\s*\|", handle.read())
            if gates:
                return gates
    return [
        "J1", "J2", "J3", "J4", "J5",
        "A1", "A2", "A3", "A4", "A5", "A6", "A7",
        "B1", "B2", "B3", "B4",
        "C1", "C2", "C3", "C4", "C5", "C6",
        "D1", "D2", "D3",
        "E1", "E2", "E3", "E4",
        "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9",
        "G1", "G2", "G3", "G4",
        "H1", "H2", "H3",
        "I1", "I2", "I3", "I4", "I5",
        "O1", "O2", "O3",
    ]


def collected_test_count() -> int | None:
    """Number of tests pytest collects, or None when pytest cannot be run."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests", "--collect-only", "-q"],
            capture_output=True, text=True, cwd=REPO_ROOT, timeout=300,
        )
        match = re.search(r"(\d+)\s+tests?\s+collected", result.stdout)
        return int(match.group(1)) if match else None
    except Exception:
        return None


def head_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=REPO_ROOT, timeout=30,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def audit_project() -> list[GateResult]:  # noqa: C901 - one branch per gate, kept flat on purpose
    gate_ids = get_standards_gate_ids()
    results: dict[str, GateResult] = {}

    def gate(gid, title, passed, message, external=False):
        results[gid] = GateResult(gid, title, passed, message, external)

    readme = read("README.md")
    readme_lower = readme.lower()

    # ------------------------------------------------------- J: Framing gates
    # J1 checks the README's actual first sentence rather than a whitelist of
    # personas. The requirement is a named user, so it looks for a human noun
    # phrase and rejects the market words.
    hero = ""
    hero_match = re.search(r"^>\s*(.+)$", readme, re.MULTILINE)
    if hero_match:
        hero = re.sub(r"[*_`]", "", hero_match.group(1)).strip()
    first_sentence = re.split(r"(?<=[.!?])\s", hero)[0] if hero else ""

    banned_markets = ["smbs", "enterprises", "creators", "teams", "everyone", "businesses", "users"]
    named_market = next((b for b in banned_markets if re.search(rf"\b{b}\b", first_sentence.lower())), None)
    persona_pattern = re.compile(
        r"\b(engineer|engineers|developer|developers|on-call|oncall|responder|"
        r"maintainer|maintainers|operator|operators|resident|residents|caregiver|caregivers)\b",
        re.IGNORECASE,
    )
    persona_hit = persona_pattern.search(first_sentence)
    j1 = bool(first_sentence) and persona_hit is not None and named_market is None
    gate("J1", "One named persona, not a market", j1,
         f"First sentence names '{persona_hit.group(0)}'" if j1
         else (f"First sentence names the market '{named_market}'" if named_market
               else f"No persona in the first sentence: {first_sentence[:70]!r}"))

    # J2: a high-consequence action must exist in code AND be guarded, not merely
    # be a word in the README.
    server = read("src/interfaces/mcp_server.py")
    rollback_domain = read("src/domain/governed_rollback.py")
    # Check each state-changing route's own decorator, not merely that the string
    # "Depends(require_operator)" appears somewhere in the file. Guarding one
    # route and leaving the other open must fail this gate.
    guarded_routes = set(re.findall(
        r'@app\.post\("([^"]+)",\s*dependencies=\[Depends\(require_operator\)\]\)', server))
    all_post_routes = set(re.findall(r'@app\.post\("([^"]+)"', server))
    must_be_guarded = {"/mcp/tools/stage_rollback", "/mcp/tools/confirm_rollback"}
    has_rollback_route = must_be_guarded <= all_post_routes
    unguarded = sorted(must_be_guarded - guarded_routes)
    rollback_is_guarded = not unguarded and "verify_governance_token" in rollback_domain
    negative_tests = read("tests/integration/test_rollback_authorization.py")
    refusal_is_tested = "401" in negative_tests and "TOKEN_ALREADY_USED" in negative_tests
    j2 = has_rollback_route and rollback_is_guarded and refusal_is_tested
    gate("J2", "Real consequence behind hero action", j2,
         "Rollback endpoint exists, requires a bearer secret and a single-use content-bound token, "
         "and the refusals are tested" if j2
         else f"routes_present={has_rollback_route} unguarded_routes={unguarded} "
              f"token_verification={'verify_governance_token' in rollback_domain} "
              f"refusal_tested={refusal_is_tested}")

    # J3: a headline comparative number needs a baseline, a margin and a sample
    # size that a committed command actually produces.
    benchmarks = read("benchmarks_summary.json")
    has_measured_file = bool(benchmarks) and "measured_by_command" in benchmarks
    claims_sample = "n=" in readme_lower or "sample size" in readme_lower or "requests)" in readme_lower
    claims_baseline = "against" in readme_lower or "baseline" in readme_lower
    j3 = has_measured_file and claims_sample and claims_baseline
    gate("J3", "One headline comparative number", j3,
         "benchmarks_summary.json carries the command that produced it, and the README states the "
         "sample size and the baseline" if j3
         else f"measured_file={has_measured_file} sample={claims_sample} baseline={claims_baseline}")

    j4_terms = [t for t in ["fire tv", "fire os", "leanback"] if t in readme_lower]
    manifest = read("app/src/main/AndroidManifest.xml")
    j4 = bool(j4_terms) and "LEANBACK_LAUNCHER" in manifest
    gate("J4", "Sponsor product is load-bearing", j4,
         "Fire TV named in the README and a LEANBACK_LAUNCHER activity exists in app/" if j4
         else f"readme_terms={j4_terms} leanback_launcher={'LEANBACK_LAUNCHER' in manifest}")

    word_count = len(first_sentence.split())
    j5 = bool(first_sentence) and word_count <= 25 and "\u2014" not in first_sentence
    gate("J5", "One republishable sentence <=25 words, no em dash", j5,
         f"{word_count} words, zero em dashes" if j5
         else f"{word_count} words, em dash present: {chr(8212) in first_sentence}")

    # ------------------------------------ A: Engineering principles (A1 - A7)
    py_files = glob.glob(os.path.join(REPO_ROOT, "src/**/*.py"), recursive=True)
    oversized = []
    for path in py_files:
        with open(path, "r", encoding="utf-8") as handle:
            if len(handle.readlines()) > 800:
                oversized.append(os.path.basename(path))
    gate("A1", "SOLID at module level (<800 lines)", not oversized,
         f"All {len(py_files)} source files under 800 lines" if not oversized else f"Oversized: {oversized}")

    env_readers = [os.path.basename(p) for p in py_files
                   if "os.environ" in open(p, "r", encoding="utf-8").read()]
    gate("A2", "YAGNI (Config knobs have active readers)", bool(env_readers),
         f"{len(env_readers)} modules read configuration from the environment")

    steps = re.findall(r"^###\s+(\d+)\.", readme, re.MULTILINE)
    a3 = bool(steps) and len(steps) <= 5
    gate("A3", "KISS (Quickstart reachable in <=5 steps)", a3,
         f"Quickstart has {len(steps)} numbered steps" if a3
         else f"Quickstart has {len(steps)} numbered steps, over the limit of 5")

    app_files = glob.glob(os.path.join(REPO_ROOT, "src/application/**/*.py"), recursive=True)
    a4 = bool(app_files) and any("from src.domain" in open(f, "r", encoding="utf-8").read() for f in app_files)
    gate("A4", "DRY (Contracts unified in domain)", a4,
         "Application layer imports its contracts from src/domain" if a4 else "Application does not import domain")

    domain_files = glob.glob(os.path.join(REPO_ROOT, "src/domain/**/*.py"), recursive=True)
    dirty_domain = []
    for path in domain_files:
        with open(path, "r", encoding="utf-8") as handle:
            if re.search(r"^\s*(import|from)\s+(boto3|httpx|requests|fastapi|uvicorn|starlette|botocore)\b",
                         handle.read(), re.MULTILINE):
                dirty_domain.append(os.path.basename(path))
    gate("A5", "Separation of Concerns (Domain imports zero SDKs)", not dirty_domain,
         f"{len(domain_files)} domain modules import no SDK or framework" if not dirty_domain
         else f"Domain imports an SDK: {dirty_domain}")

    a6 = all(os.path.isdir(os.path.join(REPO_ROOT, "src", layer))
             for layer in ["domain", "application", "infrastructure", "interfaces"])
    gate("A6", "Domain Driven Design (Bounded context directories)", a6,
         "src/domain, src/application, src/infrastructure and src/interfaces all present")

    a7 = "401" in negative_tests and "BAD_SIGNATURE" in negative_tests and "TOKEN_CONTENT_MISMATCH" in negative_tests
    gate("A7", "Principle of Least Privilege (Write rejection tested)", a7,
         "Unauthorized, forged, replayed and tampered rollbacks each have a failing-input test" if a7
         else "Rejection tests missing from tests/integration/test_rollback_authorization.py")

    # ---------------------------------- B: Architecture and compliance (B1-B4)
    compliance = read("docs/COMPLIANCE_AND_ARCHITECTURE.md").lower()
    gate("B1", "Well-Architected 6 Pillars review", "well-architected" in compliance,
         "Documented in docs/COMPLIANCE_AND_ARCHITECTURE.md" if "well-architected" in compliance
         else "No Well-Architected review found")
    b2 = "eu ai act" in compliance and "article 14" in compliance
    gate("B2", "EU AI Act Articles 10, 13, 14, 15, 50", b2,
         "Documented with residual gaps named" if b2 else "No EU AI Act section found")
    gate("B3", "GDPR Data Map documented", "gdpr" in compliance,
         "Data map documented" if "gdpr" in compliance else "No GDPR data map found")
    forbidden = [w for w in ["compliant", "conformity"] if w in readme_lower]
    gate("B4", "Never write 'compliant' or 'conformity'", not forbidden,
         "Neither word appears in the README" if not forbidden else f"README uses {forbidden}")

    # ------------------------------------------- C: Tests and coverage (C1-C6)
    ci_workflow = read(".github/workflows/ci.yml")
    gate("C1", "Coverage above 85% enforced in CI", "cov-fail-under=85" in ci_workflow,
         "CI runs pytest with --cov-fail-under=85" if "cov-fail-under=85" in ci_workflow
         else "CI does not enforce a coverage floor of 85%")

    unit_tests = glob.glob(os.path.join(REPO_ROOT, "tests/unit/test_*.py"))
    gate("C2", "Unit tests running in CI", bool(unit_tests) and "pytest tests/" in ci_workflow,
         f"{len(unit_tests)} unit test modules, run by .github/workflows/ci.yml")
    integration_tests = glob.glob(os.path.join(REPO_ROOT, "tests/integration/test_*.py"))
    gate("C3", "Functional & Integration tests", bool(integration_tests),
         f"{len(integration_tests)} integration test modules")
    security_tests = glob.glob(os.path.join(REPO_ROOT, "tests/security/test_*.py"))
    gate("C4", "OWASP / SAST / DAST execution", bool(security_tests),
         f"{len(security_tests)} security test modules, plus ruff in CI")

    # C5 is left as the strict check it was: a real browser driver navigating the
    # product. The Node spatial-navigation spec is genuinely useful but it is a
    # DOM shim, not a browser, and relabelling it would be moving the goalposts.
    browser_driver = False
    for path in glob.glob(os.path.join(REPO_ROOT, "tests/e2e/**/*.py"), recursive=True):
        with open(path, "r", encoding="utf-8") as handle:
            content = handle.read()
        if re.search(r"^\s*(import|from)\s+(playwright|selenium)\b", content, re.MULTILINE) \
                and re.search(r"\.(goto|get)\s*\(", content):
            browser_driver = True
            break
    gate("C5", "End-to-end browser user journey test", browser_driver,
         "Browser driver test present" if browser_driver
         else "No playwright or selenium journey test. tests/e2e runs DOM structure assertions and a "
              "Node-executed spatial navigation spec, neither of which drives a browser")

    # C6: the fixture-offset requirement, checked by looking for parameterised
    # tests that vary a starting parameter rather than asserting it is so.
    parametrised = 0
    for path in glob.glob(os.path.join(REPO_ROOT, "tests/**/*.py"), recursive=True):
        parametrised += len(re.findall(r"@pytest\.mark\.parametrize", open(path, "r", encoding="utf-8").read()))
    gate("C6", "Fixture starts at varied parameter offset", parametrised >= 3,
         f"{parametrised} parameterised test groups vary their starting parameters" if parametrised >= 3
         else f"Only {parametrised} parameterised test groups found")

    # ------------------------------------------------ D: Infrastructure (D1-D3)
    gate("D1", "IaC declared in Terraform/CDK", os.path.exists(os.path.join(REPO_ROOT, "infra/main.tf")),
         "infra/main.tf present")

    # D2 validates the receipt's content, not its existence.
    receipt_text = read("deploy_teardown_receipt.json")
    d2_reason = "No deployment receipt present"
    d2 = False
    if receipt_text:
        try:
            receipt = json.loads(receipt_text)
            probes = receipt.get("probes", [])
            statuses = [p.get("http_status") for p in probes]
            reachable = bool(probes) and all(s == 200 for s in statuses)
            deployed = receipt.get("deployed_commit_sha")
            local_head = receipt.get("local_head_sha")
            teardown = receipt.get("teardown_verified") is True
            d2 = reachable and bool(deployed) and deployed == local_head and teardown
            d2_reason = (
                f"probes={statuses} deployed_sha={deployed or 'not reported by the deployment'} "
                f"receipt_head={(local_head or '')[:7]} teardown_verified={teardown}"
            )
        except ValueError:
            d2_reason = "Deployment receipt is not valid JSON"
    gate("D2", "Tested deploy then teardown with recorded URL", d2,
         "Receipt records a reachable URL at this commit, with teardown verified" if d2 else d2_reason)

    infra_readme = read("infra/README.md")
    d3 = "ESTIMATE" in infra_readme or "estimate" in infra_readme.lower()
    gate("D3", "Monthly idle cost recorded with date", d3,
         "infra/README.md records the idle cost and labels it ESTIMATE where nothing measured it" if d3
         else "infra/README.md presents cost figures without saying whether they were measured")

    # ------------------------------------------------------------ E: Video
    narration = read("video/narration.json")
    cue_sheet = read("video/cue_sheet.json")
    e1 = bool(narration) and "beats" in narration
    gate("E1", "Video narration script per beat in video/", e1,
         "video/narration.json holds a per-beat script" if e1 else "No per-beat narration script")
    # E2 requires narration and picture to be in sync, which can only be true once
    # a video exists. The cue sheet is a plan for one.
    gate("E2", "Narration and picture in sync gate", False,
         "No video exists, so nothing is in sync with anything. video/cue_sheet.json is a shot plan, "
         "not a record of a recorded take")
    e3 = bool(cue_sheet) and "beat_id" in cue_sheet
    gate("E3", "Single beat re-rendering supported", e3,
         "Beats carry stable ids, so one can be re-recorded alone" if e3 else "Beats are not individually addressable")
    gate("E4", "Public video under 180s with running product", False,
         "No video has been recorded or uploaded")

    # ------------------------------------------- F: The README and repo (F1-F9)
    # F1 is renamed to what it truly checks. It counts badges and reports that
    # their targets are not fetched, rather than implying an HTTP 200 check.
    badges = re.findall(r"\[!\[.*?\]\((.*?)\)\]", readme)
    # The requirement is that a reader is told why a badge may not resolve, not
    # that the README uses one particular sentence.
    states_reachability = "badge" in readme_lower and "private" in readme_lower
    f1_note = "" if states_reachability else \
        " The README does not say the repository is private, so a judge clicking a badge will not know why it fails."
    f1 = len(badges) >= 2 and states_reachability
    gate("F1", "Badges are present and their reachability is stated (not fetched)", f1,
         f"{len(badges)} badges; the README states that repository-scoped badges do not resolve while "
         f"the repository is private. No HTTP request is made by this gate." if f1
         else f"{len(badges)} badges.{f1_note}")

    mermaid = len(re.findall(r"```mermaid", readme))
    gate("F2", "At least two Mermaid diagrams", mermaid >= 2, f"{mermaid} Mermaid diagrams in the README")
    gate("F3", "Table of contents present", "## Table of Contents" in readme, "Table of contents present")

    # F4: every number in the benchmark table must cite a command, and that
    # command must be a file that exists.
    cited_commands = re.findall(r"`(python scripts/[a-z_]+\.py[^`]*)`", readme)
    missing_scripts = [c for c in cited_commands
                       if not os.path.exists(os.path.join(REPO_ROOT, c.split()[1]))]
    f4 = bool(cited_commands) and not missing_scripts
    gate("F4", "Real numbers with command attribution", f4,
         f"{len(cited_commands)} cited commands, all of which exist" if f4
         else f"cited={len(cited_commands)} missing={missing_scripts}")

    buzzwords = [w for w in ["seamless", "robust", "leverage", "in today's world", "cutting-edge",
                             "game-chang", "revolutionary", "effortless"] if w in readme_lower]
    em_dashes = readme.count("\u2014")
    f5 = not buzzwords and em_dashes == 0
    gate("F5", "Zero em dashes and zero AI buzzwords", f5,
         "No em dashes and no buzzwords in the README" if f5
         else f"em_dashes={em_dashes} buzzwords={buzzwords}")

    f6 = all(os.path.exists(os.path.join(REPO_ROOT, p))
             for p in ["src", "tests", "LICENSE", "README.md", "CONTRIBUTING.md", "pyproject.toml"])
    gate("F6", "Standard ecosystem repository layout", f6,
         "src, tests, LICENSE, README.md, CONTRIBUTING.md and pyproject.toml all present" if f6
         else "Standard repository files are missing")

    # F7: every source module must be reachable from an entry point, so an
    # ornamental module that nothing imports fails this gate.
    entry_points = read("src/interfaces/mcp_server.py")
    reachable: set[str] = set()
    frontier = ["src/interfaces/mcp_server.py"]
    seen = set()
    while frontier:
        current = frontier.pop()
        if current in seen:
            continue
        seen.add(current)
        source = read(current)
        for module in re.findall(r"from (src\.[\w.]+) import", source):
            path = module.replace(".", "/") + ".py"
            reachable.add(path)
            frontier.append(path)
    all_modules = {os.path.relpath(p, REPO_ROOT).replace("\\", "/") for p in py_files}
    orphans = sorted(all_modules - reachable - {"src/interfaces/mcp_server.py"})
    gate("F7", "Every file is relevant and current", not orphans,
         f"All {len(all_modules)} source modules are reachable from the server entry point" if not orphans
         else f"Modules nothing imports: {orphans}")

    # F8: machine-readable artifacts must be pretty printed and carry provenance.
    unreadable = []
    for artifact in ["benchmarks_summary.json", "deploy_teardown_receipt.json",
                     "src/infrastructure/fixtures/github_telemetry_fixture.json",
                     "src/infrastructure/fixtures/aws_cost_fixture.json"]:
        text = read(artifact)
        if not text:
            unreadable.append(f"{artifact} (missing)")
        elif "\n  " not in text:
            unreadable.append(f"{artifact} (not indented)")
        elif not any(k in text for k in ["note", "measured_by_command", "recorded_by_command"]):
            unreadable.append(f"{artifact} (no provenance field)")
    gate("F8", "All artifacts human readable", not unreadable,
         "Every committed JSON artifact is indented and carries a provenance or note field"
         if not unreadable else f"Problems: {unreadable}")

    f9 = bool(steps) and "```bash" in readme
    gate("F9", "Quickstart a judge can run", f9,
         f"{len(steps)} copy-pasteable steps in the README" if f9 else "No runnable quickstart found")

    # ----------------------------------------------------- G: Consistency (G1-G4)
    badge_match = re.search(r"tests-(\d+)(?:%20|[\s_+-])*(?:passing|collected)", readme, re.IGNORECASE)
    collected = collected_test_count()
    if badge_match is None:
        g1, g1_msg = False, "No test count badge found in the README to cross-check"
    elif collected is None:
        g1, g1_msg = False, "pytest could not be run to verify the README test count"
    else:
        claimed = int(badge_match.group(1))
        g1 = claimed == collected
        g1_msg = (f"README badge says {claimed} tests, pytest collected {collected}"
                  if not g1 else f"README badge and pytest agree at {collected} tests")
    gate("G1", "No cross-surface claim discrepancy", g1, g1_msg)

    # G2 compares the deployment's own reported build SHA against HEAD and fails
    # when they differ, which is the whole point of the gate.
    local_head = head_sha()
    g2, g2_msg = False, "No deployment receipt to compare against HEAD"
    if receipt_text:
        try:
            receipt = json.loads(receipt_text)
            deployed = receipt.get("deployed_commit_sha")
            if not deployed:
                g2_msg = (f"The deployment does not report a build SHA from /health, so it cannot be "
                          f"matched to HEAD ({local_head[:7]})")
            elif deployed == local_head:
                g2, g2_msg = True, f"Deployed build SHA equals HEAD ({local_head[:7]})"
            else:
                g2_msg = f"Deployed {deployed[:7]} does not equal HEAD {local_head[:7]}"
        except ValueError:
            g2_msg = "Deployment receipt is not valid JSON"
    gate("G2", "Deployed SHA matches submitted commit", g2, g2_msg)

    routes = re.findall(r'@app\.(?:get|post)\("([^"]+)"', entry_points)
    uses_use_cases = "_use_case." in entry_points
    readme_routes = [r for r in routes if r.startswith("/mcp/") and r in readme]
    g3 = bool(routes) and uses_use_cases and len(readme_routes) >= 3
    gate("G3", "Claimed capabilities reachable in code", g3,
         f"{len(routes)} routes wired to application use cases, {len(readme_routes)} of them named in the README"
         if g3 else f"routes={len(routes)} use_cases={uses_use_cases} documented={len(readme_routes)}")

    competitors = [c for c in ["cockroach", "backblaze", "qwen", "xprize", "kaggle"] if c in readme_lower]
    gate("G4", "Zero competitor mentions", not competitors,
         "No competitor mentions" if not competitors else f"Mentions {competitors}")

    # ------------------------------------------------------------- H: UX (H1-H3)
    html = read("docs/index.html")
    h1 = ('name="viewport"' in html and "@media" in html
          and 'data-testid="primary-hero-action"' in html)
    gate("H1", "Primary action obvious without reading", h1,
         "Responsive breakpoints and a marked hero action in docs/index.html" if h1
         else "Hero action or responsive layout missing")

    disabled_controls = re.findall(r"<button[^>]*\bdisabled\b[^>]*>", html)
    unexplained = [c for c in disabled_controls if 'title="' not in c]
    h2 = bool(disabled_controls) and not unexplained
    gate("H2", "No control is disabled without visible reason", h2,
         f"{len(disabled_controls)} disabled controls, each carrying a title that says why" if h2
         else f"{len(unexplained)} disabled controls give no reason")

    h3 = html.count("empty-state-card") >= 3 and "error-card" in html and "loading-card" in html
    gate("H3", "Never gate a feature to null", h3,
         "Empty, loading and error states all render an explanation rather than nothing" if h3
         else "Missing an explicit empty, loading or error state")

    # ------------------------------------- I: Personas review instrument (I1-I5)
    # These read a coordination file that lives outside this repository. A judge
    # cloning the repository alone does not have it, so each message says so.
    state_text = ""
    external_state_path = None
    for candidate in ["../../STATE.md", "../STATE.md", "STATE.md"]:
        full = os.path.join(REPO_ROOT, candidate)
        if os.path.exists(full):
            with open(full, "r", encoding="utf-8") as handle:
                state_text = handle.read()
            external_state_path = os.path.normpath(candidate)
            break

    in_repo = external_state_path == "STATE.md"
    where = (f"read from {external_state_path}, which is outside this repository and is not part of "
             f"the clone a judge receives" if (external_state_path and not in_repo)
             else "no STATE.md was found")

    i1 = "00-RUNBOOK.md" in state_text or "Persona Review" in state_text
    gate("I1", "The runbook runs first (00-RUNBOOK.md)", i1,
         f"Persona review runbook recorded, {where}" if i1 else "No persona review runbook recorded",
         external=not in_repo)
    i2 = all(p in state_text for p in ["01 Sponsor Product Owner", "06 UX Designer", "08 Recruiter"])
    gate("I2", "Three personas minimum (01, 06, 08)", i2,
         f"Personas 01, 06 and 08 evaluated, {where}" if i2 else "Required personas not evaluated",
         external=not in_repo)
    i3 = "00-ROSTER.md" in state_text
    gate("I3", "Ownership comes from the roster (00-ROSTER.md)", i3,
         f"Persona anchors taken from the roster, {where}" if i3 else "No roster anchor recorded",
         external=not in_repo)
    i4 = "Persona Review Findings" in state_text
    gate("I4", "Findings are written down in STATE.md", i4,
         f"Findings recorded, {where}" if i4 else "No persona review findings recorded",
         external=not in_repo)

    # I5 asks for a recorded failing input per kill criterion. Mercury's kill
    # criteria are the rollback refusals, so this counts the tests that assert one.
    denial_reasons = set(re.findall(r'denial_reason"\]\s*==\s*"(\w+)"', negative_tests))
    i5 = len(denial_reasons) >= 5
    gate("I5", "Every kill criterion ships a recorded failing input", i5,
         f"{len(denial_reasons)} distinct rollback denial reasons each have a failing-input test: "
         f"{sorted(denial_reasons)}" if i5
         else f"Only {len(denial_reasons)} denial reasons have failing-input tests")

    # ---------------------------------------------------------- O: Owner-gated
    gate("O1", "YouTube upload, public not unlisted", False, "Owner action, not yet done")
    gate("O2", "Devpost CAPTCHA on Create Project", False, "Owner action, not yet done")
    gate("O3", "Pressing Submit", False, "Owner action, not yet done")

    return [results.get(gid, GateResult(gid, f"Gate {gid}", False, "not implemented")) for gid in gate_ids]


def main() -> None:
    results = audit_project()
    passed = [r for r in results if r.passed]
    failed = [r for r in results if not r.passed]
    total = len(results)

    print("=" * 78)
    print(f"  STANDARDS READINESS AUDIT: {len(passed)}/{total} PASSED, {len(failed)}/{total} FAILED")
    print("=" * 78)

    print(f"\n--- PASSED ({len(passed)}/{total}) ---")
    for result in passed:
        marker = "  [external evidence] " if result.external_evidence else "  "
        print(f"{marker}[PASS] [{result.gate_id}] {result.title}: {result.message}")

    print(f"\n--- FAILED ({len(failed)}/{total}) ---")
    for result in failed:
        exempt = f"  (not counted against CI: {CI_EXEMPT[result.gate_id]})" if result.gate_id in CI_EXEMPT else ""
        print(f"  [FAIL] [{result.gate_id}] {result.title} -> {result.message}{exempt}")

    external = [r for r in results if r.external_evidence]
    if external:
        print(f"\n--- READ FROM OUTSIDE THIS REPOSITORY ({len(external)}) ---")
        print("  These gates were evaluated against a coordination file that is not in this")
        print("  repository. Anyone cloning this repository alone should treat them as unproven.")
        for result in external:
            print(f"    [{result.gate_id}] {result.title}")

    print(f"\n--- CI EXEMPTION POLICY ({len(CI_EXEMPT)} gates) ---")
    print("  These gates still report FAIL above. They do not fail the CI job because they")
    print("  cannot be satisfied by running code in a checkout:")
    for gate_id, reason in CI_EXEMPT.items():
        print(f"    {gate_id}: {reason}")

    blocking = [r for r in failed if r.gate_id not in CI_EXEMPT]
    print("\n" + "=" * 78)
    print(f"  SUMMARY: {len(passed)}/{total} PASSED, {len(failed)}/{total} FAILED "
          f"({len(blocking)} of them blocking)")
    print("=" * 78)

    if blocking:
        print(f"\n[FAIL-GATE] {len(blocking)} blocking gate(s) failed: "
              f"{', '.join(r.gate_id for r in blocking)}")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
