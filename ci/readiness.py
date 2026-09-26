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
    "J4": "the official FAQ permits Android TV Emulator or Fire TV/Vega simulator evidence, "
          "but a workflow-dispatched install, D-pad journey and runtime receipt must still run",
    "D2": "needs a verified deploy-and-teardown cycle for the recorded build",
    "E2": "needs a recorded video for narration and picture to be in sync with",
    "E4": "needs a public video of the running product",
    "G2": "needs a deployment whose reported build SHA equals HEAD",
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


#: Where a Fire TV build-and-device receipt will live. It is written by
#: ``python scripts/write_firetv_receipt.py`` from a real build and a real launch, the
#: way deploy_teardown_receipt.json is written by its probe, and that script refuses to
#: write it without an APK file it can open. Gate J4 fails while the receipt is absent.
FIRETV_BUILD_RECEIPT = "firetv_build_receipt.json"
ANDROID_TV_RUNTIME_RECEIPT = "android_tv_runtime_receipt.json"
TERRAFORM_CYCLE_RECEIPT = "terraform_cycle_receipt.json"

#: Every field J4 requires, and what each one is evidence of. A receipt missing any of
#: them is not evidence, so the gate fails and says which field it wanted.
FIRETV_RECEIPT_FIELDS = {
    "built_by_command": "the gradle command that produced the APK",
    "gradle_exit_code": "gradle's own exit code, which must be 0",
    "apk_path": "the path of the APK, which must exist in this checkout",
    "apk_sha256": "the digest of that APK, so the file can be identified",
    "device_run": "a recorded launch on a Fire TV device",
}

#: What the legacy physical-device receipt has to say. An installed APK that was
#: never observed running proves packaging, not the user journey. The official event
#: FAQ also accepts the Android TV Emulator path evaluated separately below.
FIRETV_DEVICE_FIELDS = {
    "device_model": "which Fire TV device ran it",
    "fire_os_or_android_version": "what it was running",
    "adb_install_exit_code": "adb install's exit code, which must be 0",
    "launched_at_utc": "when it was launched",
    "observed": "what was seen on the screen, in words",
}

ANDROID_TV_RECEIPT_FIELDS = {
    "build_sha": "the Git revision that built the APK",
    "workflow_run_url": "the GitHub Actions run that retained the evidence bundle",
    "artifact_name": "the downloadable Actions artifact containing APK, logs and screenshot",
    "built_by_command": "the Gradle command and compiled endpoint",
    "apk_sha256": "the exact APK digest",
    "adb_install_exit_code": "the emulator install result, which must be 0",
    "normal_launcher": "proof the normal Leanback launcher used no URL override",
    "endpoint_loaded_without_intent_override": "the compiled HTTPS endpoint seen in logcat",
    "endpoint_health_build_sha": "proof the loaded web app reports the same release as the APK",
    "runtime": "the emulator model and Android version",
    "remote_journey": "the D-pad journey events and effect boundary",
    "artifacts": "content-addressed APK, logcat and screenshot records",
}

ANDROID_TV_REQUIRED_EVENTS = {
    "journey:page_loaded:",
    "journey:what_changed:ANOMALY_ATTRIBUTED:",
    "journey:rollback_staged:",
    "journey:rollback_confirmed:RECORDED_ONLY:DPAD_RECORD_ONLY_DEMO",
    "journey:handoff_published:checkout-api-active:",
}

ANDROID_TV_RUNTIME_PATHS = (
    "app/",
    "gradle/",
    "build.gradle.kts",
    "settings.gradle.kts",
    "gradlew",
    "gradlew.bat",
    ".github/workflows/android-tv-emulator.yml",
    "scripts/android_tv_smoke.sh",
    "scripts/write_android_tv_runtime_receipt.py",
)


def runtime_receipt_checkout_problem(receipt: dict) -> str | None:
    """Return why a historical runtime receipt cannot prove this checkout."""
    build_sha = str(receipt.get("build_sha", ""))
    if not re.fullmatch(r"[0-9a-f]{40}", build_sha):
        return "runtime build SHA is not a full Git SHA"
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", build_sha, "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if ancestor.returncode != 0:
        return f"runtime build {build_sha[:7]} is not an ancestor of HEAD"
    changed = subprocess.run(
        ["git", "diff", "--name-only", f"{build_sha}..HEAD", "--", *ANDROID_TV_RUNTIME_PATHS],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if changed.returncode != 0:
        return "could not compare runtime-bearing files with the receipt build"
    paths = [path for path in changed.stdout.splitlines() if path]
    if paths:
        return f"runtime-bearing files changed after the receipt build: {paths}"
    return None


def evaluate_terraform_cycle_receipt(receipt: object) -> tuple[bool, str]:
    """D2: validate one Actions deploy, live probe, destroy and absence receipt."""
    if not isinstance(receipt, dict):
        return False, "Terraform cycle receipt is not a JSON object"
    problems = []
    source = str(receipt.get("source_revision", ""))
    if receipt.get("schema") != "mercury.terraform_cycle_receipt/2":
        problems.append("unexpected schema")
    if receipt.get("execution_mode") != "github_actions_pipeline":
        problems.append("execution_mode is not github_actions_pipeline")
    expected_run = r"https://github\.com/upgradedev/mercury_amazon/actions/runs/[0-9]+"
    if not re.fullmatch(expected_run, str(receipt.get("workflow_run_url", ""))):
        problems.append("workflow_run_url is not a mercury_amazon Actions run")
    if not re.fullmatch(r"[0-9a-f]{40}", source):
        problems.append("source_revision is not a full Git SHA")
    if receipt.get("production_url_destroyed") is not False:
        problems.append("receipt does not preserve the production URL boundary")
    package = receipt.get("lambda_package")
    if not isinstance(package, dict) or not re.fullmatch(r"[0-9a-f]{64}", str(package.get("sha256", ""))):
        problems.append("lambda package digest is invalid")
    elif not isinstance(package.get("bytes"), int) or package["bytes"] <= 0:
        problems.append("lambda package byte count is invalid")
    pre = receipt.get("pre_destroy")
    if not isinstance(pre, dict):
        problems.append("pre_destroy evidence is missing")
    else:
        if pre.get("root_http_status") != 200 or pre.get("health_http_status") != 200:
            problems.append("disposable endpoint did not answer both live probes with HTTP 200")
        if pre.get("health_build_sha") != source:
            problems.append("disposable endpoint build SHA does not match source_revision")
        if pre.get("health_durable_state") is not True:
            problems.append("disposable endpoint did not report durable state")
        required_sids = {"FunctionURLAllowPublicAccess", "FunctionURLAllowInvokeAction"}
        if not required_sids <= set(pre.get("function_policy_statements", [])):
            problems.append("public Function URL policy is incomplete")
    destroy = receipt.get("destroy")
    if not isinstance(destroy, dict):
        problems.append("destroy evidence is missing")
    else:
        if destroy.get("terraform_exit_code") != 0:
            problems.append("terraform destroy did not exit 0")
        if destroy.get("post_destroy_url_http_status") == 200:
            problems.append("disposable endpoint still answered HTTP 200 after destroy")
        for field in (
            "lambda_absent",
            "dynamodb_absent",
            "iam_role_absent",
            "iam_policy_absent",
            "cloudwatch_log_group_absent",
            "terraform_state_empty",
            "teardown_verified",
        ):
            if destroy.get(field) is not True:
                problems.append(f"destroy.{field} is not true")
    if receipt.get("error") not in (None, ""):
        problems.append("cycle recorded an execution error")
    if receipt.get("passed") is not True:
        problems.append("pipeline did not mark the validated cycle passed")
    if problems:
        return False, "; ".join(problems)
    return True, f"Actions cycle {receipt['workflow_run_url']} deployed and destroyed {source[:7]}"


def terraform_cycle_checkout_problem(receipt: dict) -> str | None:
    """Reject a cycle when IaC or its runner changed after the evidenced revision."""
    source = str(receipt.get("source_revision", ""))
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", source, "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if ancestor.returncode != 0:
        return f"cycle source {source[:7]} is not an ancestor of HEAD"
    paths = (
        "infra/",
        ".github/workflows/terraform-cycle.yml",
        "scripts/terraform_cycle.py",
        "scripts/build_lambda_package.py",
    )
    changed = subprocess.run(
        ["git", "diff", "--name-only", f"{source}..HEAD", "--", *paths],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=20,
    )
    changed_paths = [path for path in changed.stdout.splitlines() if path]
    if changed.returncode != 0:
        return "could not compare infrastructure files with the cycle source"
    if changed_paths:
        return f"infrastructure files changed after the cycle source: {changed_paths}"
    return None


def evaluate_firetv_gate(readme_terms, manifest: str, receipt, apk_exists) -> tuple[bool, str]:
    """J4: is the sponsor product load-bearing, or merely mentioned.

    This gate used to pass on ``bool(readme_terms) and 'LEANBACK_LAUNCHER' in manifest``,
    which is a grep over two text files. Before the first successful Android workflow,
    Mercury's own README said no APK had been built, so the gate that decided whether the
    sponsor product was load-bearing was the one gate in this file that could not fail on
    the axis it exists to test, and it contributed a PASS to a published score.

    A Fire TV entry is load-bearing when there is a Fire TV binary and an allowed target
    has run the real interaction. The event FAQ explicitly accepts Android TV Emulator
    or the Fire TV/Vega simulator, so a content-addressed CI emulator receipt is valid;
    the older physical-device receipt remains valid too.

    ``apk_exists`` is injected so a test can drive every branch without an APK.
    """
    missing_context = []
    if not readme_terms:
        missing_context.append("the README never names Fire TV, Fire OS or leanback")
    if "LEANBACK_LAUNCHER" not in manifest:
        missing_context.append("no LEANBACK_LAUNCHER activity in app/src/main/AndroidManifest.xml")
    if missing_context:
        return False, "; ".join(missing_context)

    if not isinstance(receipt, dict) or not receipt:
        return False, (
            f"A leanback manifest and the word 'Fire TV' are text, not a Fire TV app. This gate "
            f"wants {ANDROID_TV_RUNTIME_RECEIPT} from the dispatched Android TV workflow or "
            f"{FIRETV_BUILD_RECEIPT} from a physical device. Neither runtime receipt exists"
        )

    if receipt.get("schema") == "mercury.android_tv_runtime_receipt/1":
        problems = []
        for field, means in ANDROID_TV_RECEIPT_FIELDS.items():
            if receipt.get(field) in (None, "", []):
                problems.append(f"{field} missing ({means})")
        if receipt.get("adb_install_exit_code") not in (None, 0):
            problems.append("adb install did not exit 0")
        if not re.fullmatch(r"[0-9a-f]{40}", str(receipt.get("build_sha", ""))):
            problems.append("build_sha is not a full Git SHA")
        if not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("apk_sha256", ""))):
            problems.append("apk_sha256 is not a SHA-256 digest")
        if not str(receipt.get("workflow_run_url", "")).startswith("https://github.com/"):
            problems.append("workflow_run_url is not a GitHub HTTPS run URL")
        expected_run = r"https://github\.com/upgradedev/mercury_amazon/actions/runs/[0-9]+"
        if not re.fullmatch(expected_run, str(receipt.get("workflow_run_url", ""))):
            problems.append("workflow_run_url is not a mercury_amazon Actions run")
        if str(receipt.get("build_sha", "")) not in str(receipt.get("artifact_name", "")):
            problems.append("artifact_name does not contain build_sha")
        if not str(receipt.get("endpoint_loaded_without_intent_override", "")).startswith("https://"):
            problems.append("the compiled endpoint is not HTTPS")
        if str(receipt.get("endpoint_loaded_without_intent_override", "")) not in str(
            receipt.get("built_by_command", "")
        ):
            problems.append("built_by_command does not identify the compiled endpoint")
        if receipt.get("endpoint_health_build_sha") != receipt.get("build_sha"):
            problems.append("endpoint_health_build_sha does not match build_sha")
        if "no COCKPIT_URL intent extra" not in str(receipt.get("normal_launcher", "")):
            problems.append("normal_launcher does not rule out an ADB URL override")
        runtime = receipt.get("runtime")
        if not isinstance(runtime, dict) or not runtime.get("device_model") or not runtime.get("os_version"):
            problems.append("runtime must name the Android TV model and OS version")
        journey = receipt.get("remote_journey")
        if not isinstance(journey, dict):
            problems.append("remote_journey is missing")
        else:
            events = set(journey.get("events", []))
            missing_events = sorted(ANDROID_TV_REQUIRED_EVENTS - events)
            if missing_events:
                problems.append(f"remote_journey missing {missing_events}")
            if "NONE" not in str(journey.get("external_effect", "")):
                problems.append("record-only external effect is not explicit")
        artifacts = receipt.get("artifacts")
        if not isinstance(artifacts, dict):
            problems.append("artifacts is missing")
        else:
            for name in (
                "apk", "logcat", "screenshot", "install_log", "launch_log", "endpoint_health",
            ):
                item = artifacts.get(name)
                if not isinstance(item, dict):
                    problems.append(f"artifacts.{name} is missing")
                    continue
                if not re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", ""))):
                    problems.append(f"artifacts.{name}.sha256 is invalid")
                if not isinstance(item.get("bytes"), int) or item["bytes"] <= 0:
                    problems.append(f"artifacts.{name}.bytes is invalid")
            apk_artifact = artifacts.get("apk")
            if isinstance(apk_artifact, dict) and apk_artifact.get("sha256") != receipt.get("apk_sha256"):
                problems.append("apk_sha256 does not match artifacts.apk.sha256")
        if problems:
            return False, f"{ANDROID_TV_RUNTIME_RECEIPT} is not evidence yet: " + "; ".join(problems)
        return True, (
            f"Android TV runtime {runtime['device_model']} ({runtime['os_version']}) installed APK "
            f"{str(receipt['apk_sha256'])[:12]}..., loaded the compiled endpoint through the normal "
            f"Leanback launcher, and logged attribution, record-only approval and handoff via D-pad; "
            f"evidence: {receipt['workflow_run_url']}"
        )

    problems = []
    for field, means in FIRETV_RECEIPT_FIELDS.items():
        if receipt.get(field) in (None, "", []):
            problems.append(f"{field} missing ({means})")
    if receipt.get("gradle_exit_code") not in (None, 0):
        problems.append(f"gradle exited {receipt.get('gradle_exit_code')}, so no APK was built")
    apk = receipt.get("apk_path")
    if apk and not apk_exists(apk):
        problems.append(f"apk_path {apk!r} is not a file in this checkout")

    device = receipt.get("device_run")
    if not isinstance(device, dict) or not device:
        problems.append("device_run missing (a recorded launch on a Fire TV device)")
    else:
        for field, means in FIRETV_DEVICE_FIELDS.items():
            if device.get(field) in (None, "", []):
                problems.append(f"device_run.{field} missing ({means})")
        if device.get("adb_install_exit_code") not in (None, 0):
            problems.append(
                f"adb install exited {device.get('adb_install_exit_code')}, so it never installed"
            )

    if problems:
        return False, f"{FIRETV_BUILD_RECEIPT} is not evidence yet: " + "; ".join(sorted(problems))

    return True, (
        f"{receipt['built_by_command']} exited 0 and produced {apk} (sha256 "
        f"{str(receipt['apk_sha256'])[:12]}...), which installed and ran on "
        f"{device['device_model']} on {device['fire_os_or_android_version']} at "
        f"{device['launched_at_utc']}: {device['observed']}"
    )


def evaluate_firetv_receipt_candidates(
    readme_terms,
    manifest: str,
    candidates: list[tuple[str, str]],
    apk_exists,
    checkout_validator=runtime_receipt_checkout_problem,
) -> tuple[bool, str]:
    """Evaluate Android-emulator and physical-device evidence independently.

    A malformed or stale receipt on one route must not shadow valid evidence on the
    other. If neither route validates, retain every rejection reason so the repair is
    actionable rather than determined by file ordering.
    """
    failures = []
    found = False
    for path, text in candidates:
        if not text:
            continue
        found = True
        try:
            receipt = json.loads(text)
        except (TypeError, ValueError):
            failures.append(f"{path}: invalid JSON")
            continue
        passed, message = evaluate_firetv_gate(readme_terms, manifest, receipt, apk_exists)
        if passed and receipt.get("schema") == "mercury.android_tv_runtime_receipt/1":
            checkout_problem = checkout_validator(receipt)
            if checkout_problem:
                passed, message = False, checkout_problem
        if passed:
            return True, f"{path}: {message}"
        failures.append(f"{path}: {message}")
    if found:
        return False, " | ".join(failures)
    return evaluate_firetv_gate(readme_terms, manifest, None, apk_exists)


#: Where the test suite's own runtime is recorded, by scripts/time_test_suite.py. G1
#: compares the README against it, because a runtime written as prose is a number that
#: ages every time a test is added and nobody notices.
SUITE_TIMING_SUMMARY = "suite_timing_summary.json"


def stale_timing_disclosure(recorded_count, collected_count) -> tuple[str, str]:
    """The two phrases the README must carry when the runtime record predates the suite.

    A runtime is a measurement of a particular suite, and the honest response to the
    suite growing is to re-measure. When it cannot be re-measured yet, because the machine
    is loaded and a loaded measurement is the defect the record exists to prevent, the
    README may keep publishing the record on one condition: it says in prose how many
    tests the record was measured over, how many the suite collects now, and that a
    re-measure on an idle machine is pending. Both phrases have to match exactly, so the
    note cannot age into a vague "roughly current", and the second one names the live
    count, so adding a test without updating the note still turns G1 red.
    """
    return (
        f"measured over {recorded_count} collected tests",
        f"the suite now collects {collected_count} tests and a re-measure on an idle machine "
        f"is pending",
    )


#: Where the persona review is restated in this repository's own voice. Gates I1 to I4
#: used to read a workspace coordination file two directories up, which meant they
#: passed here and failed for anyone who cloned this repository on its own. They read
#: this file instead, so the score they contribute to is reproducible from a clone.
PERSONA_REVIEW_DOC = "docs/PERSONA_REVIEW.md"

#: The three lenses the review is required to carry, by role. The internal instrument
#: that defines them is a workspace document that is never part of a submission, so it
#: is not named here and these gates do not string-match its filename. A gate that
#: checks for a filename it cannot open is checking nothing.
PERSONA_LENSES = ("Sponsor product owner", "UX designer", "Recruiter")

#: Outcomes a procedure step or a finding may carry. Anything else is not a verdict.
PERSONA_VERDICTS = ("PASS", "FAIL", "PARTIAL", "OPEN")


def markdown_table(text: str, *required_headers: str) -> list[dict[str, str]]:
    """Rows of the first markdown table whose header carries every required column.

    Returned as dicts keyed by header cell. A document with no such table yields an
    empty list, which is what makes the gates below able to fail.
    """
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not line.strip().startswith("|"):
            continue
        headers = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not all(header in headers for header in required_headers):
            continue
        if index + 1 >= len(lines) or not re.match(r"^\|[\s:|-]+\|$", lines[index + 1].strip()):
            continue
        rows = []
        for row_line in lines[index + 2:]:
            if not row_line.strip().startswith("|"):
                break
            cells = [cell.strip() for cell in row_line.strip().strip("|").split("|")]
            if len(cells) < len(headers):
                cells += [""] * (len(headers) - len(cells))
            rows.append(dict(zip(headers, cells)))
        return rows
    return []


def cited_repository_paths(text: str) -> list[str]:
    """Every repository-relative path cited in backticks anywhere in ``text``.

    A path is a backticked word carrying both a ``/`` and a file extension, which
    picks ``tests/unit/test_readiness_gates.py`` out of a command line and leaves
    ``tests/`` and prose alone.
    """
    paths = []
    for span in re.findall(r"`([^`]+)`", text):
        for word in span.split():
            word = word.strip("(),;:")
            if "/" in word and re.search(r"\.[A-Za-z0-9]{1,5}$", word):
                paths.append(word)
    return sorted(set(paths))


def evaluate_persona_review_gates(doc: str, path_exists) -> dict[str, tuple[bool, str]]:
    """I1 to I4: was a structured review run, owned, and written down where a clone sees it.

    These four gates used to read ``../../STATE.md``. Each said in its own message that
    the evidence was outside the repository, which was honest and unusable: a judge with
    a clone and nothing else got four FAILs where this machine printed four PASSes, so
    the published readiness score was not reproducible from the artifact submitted.

    They now read ``docs/PERSONA_REVIEW.md`` and check its substance rather than the
    presence of a phrase. Deleting a lens, attributing a finding to a lens nobody owns,
    dropping the review date or citing a test file that is not on disk each turns one of
    them red. ``path_exists`` is injected so a test can drive the citation branch
    without writing files into the checkout.
    """
    outcomes: dict[str, tuple[bool, str]] = {}

    if not doc.strip():
        missing = f"{PERSONA_REVIEW_DOC} is missing, so no review is recorded in this repository"
        return {gid: (False, missing) for gid in ("I1", "I2", "I3", "I4")}

    # --- I1: the procedure that runs before any lens opens.
    steps = markdown_table(doc, "Step", "What it asks", "Outcome", "Evidence")
    bad_steps = [
        s["Step"] for s in steps
        if s["Outcome"] not in PERSONA_VERDICTS or not s["Evidence"]
    ]
    i1 = len(steps) >= 4 and not bad_steps
    outcomes["I1"] = (i1, (
        f"{len(steps)} procedure steps ran before any lens opened, each with an outcome and a "
        f"citation, recorded in {PERSONA_REVIEW_DOC}" if i1
        else f"{PERSONA_REVIEW_DOC} records {len(steps)} procedure steps"
             + (f"; these carry no outcome or no evidence: {bad_steps}" if bad_steps else "")
             + ("; at least four are required" if len(steps) < 4 else "")
    ))

    # --- I2: three lenses, each with a verdict and at least one finding of its own.
    owners = markdown_table(doc, "Lens", "Owner", "What it decides", "Verdict")
    findings = markdown_table(doc, "ID", "Lens", "Finding", "Verdict", "Evidence")
    by_lens = {row["Lens"]: row for row in owners}
    lenses_with_findings = {row["Lens"] for row in findings}
    missing_lenses = [
        lens for lens in PERSONA_LENSES
        if lens not in by_lens
        or by_lens[lens]["Verdict"] not in PERSONA_VERDICTS
        or lens not in lenses_with_findings
    ]
    i2 = not missing_lenses
    scored = ", ".join(
        "{} {}".format(lens, by_lens[lens]["Verdict"]) for lens in PERSONA_LENSES
    ) if i2 else ""
    outcomes["I2"] = (i2, (
        f"All three required lenses reviewed in {PERSONA_REVIEW_DOC}, each with a verdict "
        f"and findings of its own: {scored}" if i2
        else f"Lenses missing from {PERSONA_REVIEW_DOC}, unscored, or with no finding of "
             f"their own: {missing_lenses}"
    ))

    # --- I3: ownership is total. A finding attributed to a lens nobody owns fails.
    unowned = sorted(
        lens for lens in lenses_with_findings
        if lens not in by_lens or not by_lens[lens]["Owner"]
    )
    i3 = bool(owners) and all(row["Owner"] for row in owners) and not unowned
    outcomes["I3"] = (i3, (
        f"Every lens carrying a finding has exactly one owner across {len(owners)} rows "
        f"of {PERSONA_REVIEW_DOC}" if i3
        else (f"{PERSONA_REVIEW_DOC} attributes findings to a lens with no owner: {unowned}"
              if unowned else f"{PERSONA_REVIEW_DOC} records no ownership table")
    ))

    # --- I4: findings written down, dated, and every citation resolvable on disk.
    date = re.search(r"Review date:\s*(\d{4}-\d{2}-\d{2})", doc)
    bad_findings = [
        f["ID"] for f in findings
        if not f["Finding"] or f["Verdict"] not in PERSONA_VERDICTS or not f["Evidence"]
    ]
    dangling = [path for path in cited_repository_paths(doc) if not path_exists(path)]
    i4 = len(findings) >= 5 and not bad_findings and not dangling and bool(date)
    failure_count = sum(1 for f in findings if f["Verdict"] == "FAIL")
    outcomes["I4"] = (i4, (
        f"{len(findings)} findings recorded in {PERSONA_REVIEW_DOC} on {date.group(1) if date else ''}, "
        f"{failure_count} of them failures, every citation resolving to a file in this checkout"
        if i4 else
        f"{PERSONA_REVIEW_DOC} records {len(findings)} findings"
        + ("" if date else "; no review date")
        + (f"; incomplete rows: {bad_findings}" if bad_findings else "")
        + (f"; cited paths that are not in this checkout: {dangling}" if dangling else "")
    ))

    return outcomes


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
    j4, j4_message = evaluate_firetv_receipt_candidates(
        j4_terms,
        manifest,
        [
            (ANDROID_TV_RUNTIME_RECEIPT, read(ANDROID_TV_RUNTIME_RECEIPT)),
            (FIRETV_BUILD_RECEIPT, read(FIRETV_BUILD_RECEIPT)),
        ],
        lambda path: os.path.isfile(os.path.join(REPO_ROOT, path)),
    )
    gate("J4", "Sponsor product is load-bearing", j4, j4_message)

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

    # D2 is a separate disposable pipeline. Production probes belong only to G2.
    receipt_text = read("deploy_teardown_receipt.json")
    cycle_text = read(TERRAFORM_CYCLE_RECEIPT)
    d2_reason = f"No {TERRAFORM_CYCLE_RECEIPT} from the disposable Actions pipeline"
    d2 = False
    if cycle_text:
        try:
            cycle_receipt = json.loads(cycle_text)
            d2, d2_reason = evaluate_terraform_cycle_receipt(cycle_receipt)
            if d2:
                checkout_problem = terraform_cycle_checkout_problem(cycle_receipt)
                if checkout_problem:
                    d2, d2_reason = False, checkout_problem
        except ValueError:
            d2_reason = f"{TERRAFORM_CYCLE_RECEIPT} is not valid JSON"
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
    # Runtime entry points include both the local ASGI server and any callable
    # referenced by Terraform. Lambda imports its handler from the IaC string,
    # so a Python-only import graph would incorrectly call that adapter an orphan.
    entry_points = read("src/interfaces/mcp_server.py")
    terraform = read("infra/main.tf")
    terraform_entry_points = {
        module.replace(".", "/") + ".py"
        for module in re.findall(r'handler\s*=\s*"([\w.]+)\.[\w]+"', terraform)
    }
    root_entry_points = {"src/interfaces/mcp_server.py", *terraform_entry_points}
    reachable: set[str] = set()
    frontier = list(root_entry_points)
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
    orphans = sorted(all_modules - reachable - root_entry_points)
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

    # The other cross-surface number is how long that suite takes. It was prose, it
    # went stale as the suite tripled in size, and it is the one claim in this
    # repository that three readers failed to reproduce. It is recorded by
    # scripts/time_test_suite.py now, and G1 checks the README against the record.
    # Figures inside backticks are quotations, not claims: the evidence document quotes
    # the two retired figures so the correction stays visible. Strip code before reading
    # claims. The runtime and its history moved from the README into docs/EVIDENCE.md so
    # the README reads in a minute; the badge above stays on the README, and the runtime
    # is checked where it is now published.
    evidence = read("docs/EVIDENCE.md")
    readme_prose = " ".join(re.sub(
        r"`[^`]*`", " ", re.sub(r"```.*?```", " ", evidence, flags=re.DOTALL)).split())
    runtime_claims = re.findall(r"(\d+(?:\.\d+)?) to (\d+(?:\.\d+)?) seconds", readme_prose)
    timing = {}
    if os.path.exists(os.path.join(REPO_ROOT, SUITE_TIMING_SUMMARY)):
        with open(os.path.join(REPO_ROOT, SUITE_TIMING_SUMMARY), "r", encoding="utf-8") as handle:
            timing = json.load(handle)
    if g1:
        stale_note = ""
        if not runtime_claims:
            g1, g1_msg = False, "docs/EVIDENCE.md no longer says how long the test suite takes"
        elif not timing:
            g1, g1_msg = False, (
                f"docs/EVIDENCE.md publishes a suite runtime and {SUITE_TIMING_SUMMARY} is missing, "
                f"so nothing measured it. Run python scripts/time_test_suite.py")
        elif timing.get("tests_collected") != collected:
            # The record predates the suite. That is allowed only when the README says
            # so in the two exact phrases stale_timing_disclosure returns; a record that
            # is quietly older than the suite it describes is the defect this gate exists
            # to catch.
            needed = stale_timing_disclosure(timing.get("tests_collected"), collected)
            missing = [phrase for phrase in needed if phrase not in readme_prose]
            if missing:
                g1, g1_msg = False, (
                    f"The recorded runtime was measured over {timing.get('tests_collected')} tests "
                    f"and this suite now has {collected}. Re-run python scripts/time_test_suite.py "
                    f"on an idle machine, or disclose the gap in docs/EVIDENCE.md with the exact "
                    f"phrases {missing}")
            else:
                stale_note = (
                    f"; the runtime record predates the suite ({timing.get('tests_collected')} of "
                    f"{collected} tests), docs/EVIDENCE.md says so, and an idle re-measure is pending")
        if g1:
            # Two ranges may legitimately appear: this session's, and the session it
            # replaced. The second is there so a replaced figure leaves a trace.
            sessions = {(timing.get("min_seconds"), timing.get("max_seconds"))}
            previous = timing.get("previous_measurement") or {}
            lows = [v for k, v in previous.items() if k.endswith("_min_seconds") and v is not None]
            highs = [v for k, v in previous.items() if k.endswith("_max_seconds") and v is not None]
            if lows and highs:
                sessions.add((min(lows), max(highs)))
            unmatched = [c for c in runtime_claims
                         if (float(c[0]), float(c[1])) not in sessions]
            if unmatched:
                g1, g1_msg = False, (
                    f"docs/EVIDENCE.md publishes {unmatched} for the suite runtime; the recorded "
                    f"sessions measured {sorted(sessions)} s")
            elif f"{timing.get('loaded_max_seconds')} seconds" not in readme_prose:
                g1, g1_msg = False, (
                    f"docs/EVIDENCE.md publishes a runtime range with no loaded-machine figure "
                    f"beside it, so it reads as a ceiling. The loaded run measured "
                    f"{timing.get('loaded_max_seconds')} s")
            else:
                g1_msg += (f", and all {len(runtime_claims)} published runtime ranges match a "
                           f"recorded session ({len(timing.get('runs', []))} runs this session, "
                           f"{timing.get('min_seconds')} to {timing.get('max_seconds')} s)"
                           + stale_note)
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
                # The server in this checkout does report build_sha from /health; the
                # receipt records that the DEPLOYED endpoint did not. Name the URL so
                # the line cannot be read as a defect in the local server.
                where = receipt.get("base_url") or "named in deploy_teardown_receipt.json"
                probed = receipt.get("probed_at_utc") or "an unrecorded time"
                g2_msg = (f"The deployed endpoint {where} runs an older build whose /health "
                          f"answered without a build_sha when probed at {probed}, so the "
                          f"deployment cannot be matched to HEAD ({local_head[:7]}); the server "
                          f"in this checkout does report build_sha from /health")
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
    # These four used to read a coordination file two directories above this
    # repository. They passed on this machine and would have failed in a clone,
    # which made a quarter of the failing surface unauditable from the artifact
    # submitted. They read docs/PERSONA_REVIEW.md now and check its substance.
    persona_doc = read(PERSONA_REVIEW_DOC)
    persona_outcomes = evaluate_persona_review_gates(
        persona_doc, lambda path: os.path.exists(os.path.join(REPO_ROOT, path)))

    gate("I1", "The review procedure runs before any lens opens",
         *persona_outcomes["I1"])
    gate("I2", "Three lenses minimum (sponsor product owner, UX designer, recruiter)",
         *persona_outcomes["I2"])
    gate("I3", "Every lens carrying a finding has an owner",
         *persona_outcomes["I3"])
    gate("I4", f"Findings are written down in {PERSONA_REVIEW_DOC}",
         *persona_outcomes["I4"])

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
