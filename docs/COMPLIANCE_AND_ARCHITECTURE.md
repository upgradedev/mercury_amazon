# Architecture, AWS Well-Architected review, and regulatory alignment

**Repository:** `mercury_amazon`
**Scope:** the code in this repository as it stands, not a planned system.

A note on what this document is. It is a self-assessment, not an audit. No
external reviewer has looked at this system, no AWS Well-Architected Framework
Review tool has been run against it, and no legal review has been performed. Where
a pillar or an article is only partly addressed, this document says so rather than
awarding itself a pass. The words "compliant" and "conformity" are deliberately
avoided throughout, because neither has been established by anyone qualified to
establish it.

---

## 1. Architecture

Hexagonal, four layers, with the dependency rule enforced by a readiness gate that
reads the imports rather than trusting the diagram.

| Layer | Directory | Rule | Enforced by |
|---|---|---|---|
| Domain | `src/domain` | Pure models. No SDK, no framework, no I/O | Gate A5 greps for `boto3`, `httpx`, `fastapi`, `botocore`, `requests` imports |
| Application | `src/application` | Use cases depending on `Protocol`s | Gate A4 checks the layer imports its contracts from the domain |
| Infrastructure | `src/infrastructure` | Adapters to GitHub, Cost Explorer, CloudWatch, local git | Gate F7 checks nothing here is orphaned |
| Interfaces | `src/interfaces` | The HTTP server and route wiring | Gate G3 checks routes reach use cases |

The Fire TV client (`app/`) is a separate Android module that hosts the same
cockpit page the web serves, so there is one interface implementation rather than
a TV copy that can drift.

### Data provenance as an architectural constraint

Every telemetry report carries a `Provenance` value (`src/domain/provenance.py`)
naming its source, and the interface layer serialises it into every response. This
is not decoration; it is the mechanism that makes a fallback safe to ship. An
adapter that cannot reach its live source returns a fixture **and** a provenance
that says why, and the cockpit renders the difference visibly.

---

## 2. AWS Well-Architected review

Six pillars, assessed against what is implemented. "Partial" and "Not addressed"
are used where they are the truth.

| Pillar | What exists | Assessment |
|---|---|---|
| **Operational excellence** | Terraform in `infra/main.tf`. A public Function URL serves the cockpit and `GET /health` reports status and the build SHA. Structured CloudWatch EMF is emitted per request by `PrivateObservabilityHarness`, with PII masking. CI runs lint, 665 tests, a coverage floor and the readiness auditor. | **Partial.** The software path is deployed, but teardown has not been exercised and the candidate Android TV runtime receipt is pending. |
| **Security** | Operator state changes require a bearer secret compared in constant time. Governance tokens are HMAC-signed, content-bound and single use. The public D-pad demo routes accept only fixed labelled fixture evidence, turn off whenever a dispatcher is selected, and have no external effect. | **Partial.** The operator secret is shared, with no rotation and no per-operator identity. DynamoDB makes nonces global across instances but does not identify the human actor. |
| **Reliability** | Every adapter degrades to a labelled fallback rather than failing the request. Failed AWS calls are deliberately not cached. Rollback leases expire. The Lambda persists deployment markers, handoffs, staged actions and spent nonces in DynamoDB with conditional writes. | **Partial.** The local quickstart deliberately falls back to process memory, and deployed concurrency still needs operational evidence. |
| **Performance efficiency** | Measured, not asserted: `python scripts/benchmark_suite.py` reports 2.88 ms to 65.90 ms mean per endpoint over 60 requests each, written to `benchmarks_summary.json`. Credential resolution and fixture reads are cached after a benchmark showed them costing over a second per request. | **Addressed for the local path.** No measurement exists from a Fire TV on a real network. |
| **Cost optimisation** | Cost Explorer responses cached for 15 minutes because AWS bills per request. Serverless design with no always-on compute. | **Partial.** The idle cost figures in `infra/README.md` are labelled ESTIMATE because no bill has been read for a deployment of this project. |
| **Sustainability** | Scale-to-zero compute; no continuous polling of paid APIs. | **Partial.** Asserted from the architecture, not measured. |

---

## 3. EU AI Act alignment

Mercury performs threshold arithmetic and HMAC verification. It runs no model and
makes no automated decision about a person, so on our reading it is not a
high-risk AI system under the Act. The articles below are addressed anyway,
because the incident-attribution feature makes a claim about causation that a
human will act on.

| Article | Requirement | What this repository does | Gap |
|---|---|---|---|
| **Article 10** (Data governance) | Data sets are relevant, representative and documented | Every input carries a `Provenance` recording source, detail and observation time. The GitHub fixture is a recording of a real read with the command that produced it. The AWS fixture states in its own text that it is synthetic. | The synthetic cost fixture is not representative of any real account, which is why it says so rather than being presented as typical. |
| **Article 13** (Transparency) | Users can interpret the output and use it appropriately | The cockpit prints the provenance beside every number, with a visually distinct `OFFLINE FIXTURE` badge. The correlator returns its reasoning as text, including the reasoning for a refusal. DORA proxy definitions are stated in `docs/EVIDENCE.md` rather than implied. | None identified. |
| **Article 14** (Human oversight) | A human can intervene, and automation does not act alone | Mercury never executes a rollback on its own. It stages a recommendation; a person must authorise with a secret, then confirm with a single-use token inside a 300 second lease. Every refusal names its reason. | Oversight is authenticated by a shared secret, not by an identified individual, so the record shows that an authorised party acted, not which one. |
| **Article 15** (Accuracy and robustness) | Accuracy is stated, and the system resists failure | The anomaly rule is published: a step up against the mean of the readings before the step, with a fixed factor, and the attribution refuses to name a change when more than one landed in the window. A zero baseline is explicitly not treated as an infinite spike. Only a commit that changed a file the server is built from (`src/domain/change_scope.py`) counts as a deploy candidate. Naming precision is measured at 0.500 over 58 namings (95% interval 0.375 to 0.625) on the held-out half of a synthetic, self-authored labelled corpus of 1160 cases per side, with the window and gate tuned on the train half and the runtime filter imposed as a constraint, and ships in every answer as attribution.measured_accuracy. Before the filter the same split read 0.625 over 40; the generator's labels let a documentation-only commit cause a regression, and the drop is counted in `docs/EVIDENCE.md`. Both halves share the generator's assumption that a regression shows within 75 minutes, which the shipped window equals, so the figure is conditional on it (41.5% at a 90 minute ceiling, 27.3% at 180) and the note in the answer says so. The in-sample 0.5221 over 113 namings it replaced on 2026-09-27 is kept in `docs/EVIDENCE.md` as history. A refusal to attribute ships as a refusal (`attribution.refusal_statement` names the reason and says the reason is not a finding about the deploys; `attribution.nothing_to_revert` is true only when the reading is under the 3.0x anomaly threshold) and is never rendered as proof that a deploy did not cause the anomaly. 665 tests are collected and the recorded coverage run reports 92 percent over 2089 statements, including a failing-input test for each of ten rollback denial reasons. | The rule has no seasonality and no trend model, so a regular nightly batch will look like an anomaly. This is a known false-positive mode and is stated in `docs/EVIDENCE.md`. |
| **Article 50** (Disclosure) | People are told when they interact with a machine | The cockpit is labelled as a tool throughout. Its spoken output is the browser's `speechSynthesis`, disclosed as such in `docs/EVIDENCE.md`. There is no conversational agent and no synthetic persona. | None identified. |

---

## 4. GDPR data map

| Category | Collected | Stored | Transmitted |
|---|---|---|---|
| Customer or end-user personal data | None | None | None |
| Commit author names and pull request author logins | Yes, from GitHub or local `git log` | In process memory only, for the life of a request | Rendered on the cockpit screen |
| AWS account spend per service | Yes, when credentials resolve | 15 minute in-process cache | Rendered on the cockpit screen |
| Request metadata (client IP, path, status) | Yes | Emitted to logs as CloudWatch EMF | Masked before emission |

Mercury reads no customer database and holds no end-user records. The only
personal data it touches is the developer identity attached to a commit, which is
already published in the repository it is read from.

`PrivateObservabilityHarness` masks email addresses, GitHub tokens matching
`ghp_[A-Za-z0-9]{36}`, and `AWS_SECRET_ACCESS_KEY=` values before any log record
leaves the process. That masking is unit tested in
`tests/unit/test_observability_harness.py`.

**Known gap.** The masking is regular-expression based. It catches the patterns it
knows and will not catch a credential in an unrecognised format. It reduces
accidental disclosure; it is not a guarantee.

**Retention.** Nothing is persisted by Mercury itself. Log retention is whatever
the CloudWatch log group is configured with, which this repository does not set.

---

## 5. Threat notes

| Threat | Mitigation | Residual risk |
|---|---|---|
| Anyone on the network stages or confirms a rollback | Bearer secret required on both endpoints, constant-time comparison | A leaked secret grants full rollback authority. There is no rotation and no second factor. |
| A staged rollback is edited before confirmation | The token is bound to a hash of the payload; any edit invalidates it | None identified for this path. |
| A captured token is replayed | Nonce consumed on first use | The nonce set is in memory, so a second server instance would accept a token the first has already spent. |
| A hostile deep link redirects the Fire TV WebView | `CockpitUrlResolver` accepts only absolute `http` and `https` URLs, rejecting `javascript:`, `file:` and embedded whitespace | An attacker who can set the intent extra can still point the app at another `http` host. |
| A malicious API response injects markup into the cockpit | Every interpolated value passes through `escapeHtml`, checked by a test that parses each `innerHTML` statement | None identified for this path. |
| The asset route is walked out of `docs/` | Extension allowlist plus a resolved-parent check | None identified for this path. |
