# Requirements Document

## Introduction

`formal-outbound-release` defines a fail-closed, one-time formal outbound release capability for LexAegis V1.0. The feature preserves the current blocked state and the current record of ten layer-A evaluations with zero real sends. The feature derives release controls, evidence requirements, and review workflows only from existing legal assets, catalogs, rules, templates, and the labor V2 draft pack. Missing case-specific facts, signatures, runtime receipts, provider evidence, and approvals remain `unknown` or `pending` and block dispatch.

## Glossary

- **System**: The LexAegis workbench, worker, independent gateway, and supporting release-control services acting together.
- **Existing Legal Assets**: The repository's current merged legal-source catalog, rule specification, `outbound_gate` G table, legal-computing handoff templates, signature workbook, approval-page design, labor V2 draft pack, and current templates.
- **Formal Release Policy**: A time-bounded, build-bound, provider-bound policy that can arm at most one dispatch for the exact `LA-001 × R_fact_summary × D_DeepSeek_official_API` tuple.
- **Canonical Request Hash**: The deterministic hash of the complete frozen formal request and its specified dependencies, excluding approval state, grant state, provider response, and runtime attempt records.
- **Runtime Pack**: A content-addressed operational copy derived from the existing labor V2 draft pack without modifying or publishing the repository draft.
- **Gate Decision**: The authoritative result produced from the existing `outbound_gate` G identifiers for a specific formal-release phase.
- **G-product**: The existing product-release latch gate that remains blocked without a valid, exact-scope Formal Release Policy.
- **One-Time Grant**: A random authorization with an exact 30-minute lifetime, bound to one request, evidence manifest, build manifest, release policy, target, and model.
- **Request-Bound Isolation Receipt**: G9 technical evidence tied to the exact request hash, build, deployment, Compose configuration, image digests, probes, host firewall evidence, and supply-chain evidence.
- **Actual Provider Attempt**: A provider network attempt begun only after the independent gateway atomically claims the request ID, One-Time Grant nonce, and product-policy slot.
- **Formal Context**: The complete set of frozen request, tuple, Runtime Pack, provider profile, evidence, build manifest, ledger, attack runs, isolation receipt, approval or grant state, and product policy needed for an applicable gate phase.
- **Conflict Response**: The expected fail-closed response, normally HTTP 409, returned before dispatch when a mandatory condition does not pass.
- **Verified Build Manifest**: A release manifest produced from a clean worktree and verified validation results, with hashes for every required source and deployment artifact.
- **Pending Build Manifest**: A diagnostic manifest that cannot arm G-product or authorize formal release.
- **Legal Confirmation Templates**: The existing 法01, 法02, 法08, 法09, and 法10 templates used for named, hash-bound evidence; a blank template is not evidence of a conclusion.
- **Gateway Record**: The durable independent-gateway record whose state distinguishes `sending`, `complete`, `unknown`, and failed-before-disclosure outcomes.

## Requirements

### Requirement 1: Scope and safety baseline

**User Story:** As a release owner, I want formal outbound capability to remain fail-closed until every existing gate has request-bound evidence, so that adding the feature does not imply that formal dispatch is already enabled.

#### Acceptance Criteria

1.1 WHILE no valid Formal Release Policy is installed, THE System SHALL expose the formal outbound state as `blocked`.

1.2 WHEN the System implements or operates formal outbound release, THE System SHALL preserve `packs/labor_v2_draft.json` at version `2.0.0-draft.3`, `status=draft`, and `dispatch_allowed=false`.

1.3 WHEN the System records the current ten-case result, THE System SHALL classify the result as layer-A evaluation with zero real sends unless the independent gateway has claimed a valid One-Time Grant and started an Actual Provider Attempt.

1.4 WHEN the D-path performs `evaluate`, THE System SHALL classify the operation as evaluation rather than HTTP dispatch.

1.5 IF any mandatory approve, reserve, or send condition is missing, `unknown`, `pending`, expired, failed, stale, or revoked, THEN THE System SHALL return a Conflict Response identifying the blocking existing G identifier and reason code.

1.6 WHEN the System returns a pre-dispatch Conflict Response, THE System SHALL leave approval receipts, grants, dispatch intents, outbox events, grant reservations, product-policy consumption, Gateway Records, and provider network-attempt counts unchanged.

### Requirement 2: Existing-asset-only legal integration

**User Story:** As a legal reviewer, I want the implementation to reuse current legal assets without requiring new legal source material, so that the release process is grounded in the repository's existing evidence base.

#### Acceptance Criteria

2.1 WHEN the System imports legal release material, THE System SHALL support the existing merged legal-source catalog, rule specification, `outbound_gate` G table, legal-computing handoff templates, signature workbook, approval-page design, labor V2 draft pack, and current templates.

2.2 WHEN an Existing Legal Asset supplies required normative content or template structure, THE System SHALL use that asset without requiring an additional legal source document for the same content or structure.

2.3 WHEN a gate depends on case-specific facts, a completed signature, actual provider evidence, or a runtime receipt, THE System SHALL require genuinely completed evidence using the Existing Legal Assets rather than treating the template or legal source itself as proof of the case-specific condition.

2.4 IF an Existing Legal Asset does not prove a contract term, provider fact, approver identity, signature result, legal conclusion, organization authorization, attack result, or isolation result, THEN THE System SHALL record the unsupported condition as `unknown` or `pending` and block dispatch.

2.5 IF input consists only of a filename, blank form, oral statement, engineering probe, AI-authored opinion, or public marketing text, THEN THE System SHALL preserve the corresponding conclusion as `unknown` or `pending` rather than synthesize `reviewed`, `pass`, `resisted`, signed, authorized, or approved status.

### Requirement 3: Legal-source normalization and citation mapping

**User Story:** As a legal asset maintainer, I want deduplication and historical article mapping to preserve every source variant, so that normalization cannot silently rewrite legal evidence.

#### Acceptance Criteria

3.1 WHEN the System imports a legal-source row, THE System SHALL retain at least one source asset identifier and the content hash of the source bytes for that row.

3.2 WHEN the System imports exact duplicate legal-source rows in any input order, THE System SHALL produce the same duplicate grouping while retaining every source link and source hash.

3.3 WHEN legal-source rows share a normalized title and article scope but differ in text or version metadata, THE System SHALL preserve every variant and mark the canonical conclusion `pending` until the existing review process resolves the conflict.

3.4 WHEN the System represents the Lawyer Law article transition effective 2026-09-01, THE System SHALL retain former article 38 as a historical record and link article 38 to article 41 through an explicit time-bounded citation mapping.

3.5 IF the article 38-to-41 relationship is supported only by amendment sequence rather than verified republished full text, THEN THE System SHALL label the mapping basis as amendment sequence and classify verbatim verification of current article 41 text as `pending`.

3.6 IF a post-2026-09-01 runtime rule cites article 38 as current without a temporal mapping or relies on an unresolved article 38/41 conflict, THEN THE System SHALL return a non-pass G5 result.

3.7 IF an article-level statutory basis is required, THEN THE System SHALL classify an instrument-scope reference or recommendation standard alone as insufficient for that basis.

3.8 IF any legal-source row in an import transaction lacks a source asset identifier or source content hash, THEN THE System SHALL reject the complete import transaction without persisting a partial registry update.

### Requirement 4: Runtime pack lifecycle

**User Story:** As a pack administrator, I want a reviewed runtime copy to be publishable without publishing the repository draft, so that operational release evidence and source-control assets remain distinct.

#### Acceptance Criteria

4.1 WHEN the System creates a Runtime Pack draft, THE System SHALL derive an independent content-addressed operational copy from the existing labor V2 draft.

4.2 WHILE any existing Runtime Pack publication condition lacks a pass result, THE System SHALL keep the Runtime Pack non-dispatchable; the required conditions SHALL include reviewed legal state, explicit dispatch scope, five frozen risk weights, review evidence, references, and a valid content hash.

4.3 WHEN the System publishes a Runtime Pack for formal release, THE System SHALL bind the publication to exactly `LA-001 × R_fact_summary × D_DeepSeek_official_API` without wildcard case, purpose, recipient, model, or time scope.

4.4 WHEN the System publishes, retires, or revokes a Runtime Pack, THE System SHALL leave the repository pack file unchanged.

4.5 WHEN a bound Runtime Pack hash changes or the Runtime Pack is retired or revoked, THE System SHALL invalidate every unclaimed frozen request, downstream receipt, pending intent, and One-Time Grant bound to the former hash.

### Requirement 5: Canonical gate evaluation

**User Story:** As a security engineer, I want one authoritative formal gate evaluator, so that no send path can rely on a weaker subset under a misleading name.

#### Acceptance Criteria

5.1 WHEN the System performs authoritative formal gate evaluation, THE System SHALL execute only the existing `outbound_gate` G identifiers without introducing a second gate numbering scheme.

5.2 WHEN the System evaluates a formal-release phase, THE System SHALL evaluate G0, G1, G2, G3, G5, G6, G7, G8, G9, G10 when required by the phase, and G-product.

5.3 WHEN the System evaluates approval eligibility before G10 exists, THE System SHALL compute `approval_eligible` from G0 through G9 plus G-product without treating absent G10 as a blocker.

5.4 WHEN the System evaluates enqueue, worker-send, or gateway dispatch, THE System SHALL set `dispatch_allowed=true` only when G10 and every other applicable gate pass.

5.5 IF any mandatory Gate Decision result is `unknown`, `pending`, `fail`, expired, stale, or revoked, THEN THE System SHALL treat that result as a dispatch blocker.

5.6 WHEN the System classifies a gate by engineering `kind` or legal `disposition`, THE System SHALL preserve engineering failures as dispatch blockers even when the failures do not change legal disposition.

5.7 WHEN a caller invokes the public `validate_formal_gate` API, THE System SHALL require complete Formal Context and return the complete Gate Decision for the requested phase.

5.8 IF a migration-only subset validator is invoked by an approval, enqueue, worker, or gateway authorization path, THEN THE System SHALL fail the authorization path closed and identify the subset validator as non-authoritative.

5.9 IF a caller invokes the legacy four-argument gate API without complete Formal Context, THEN THE System SHALL return a blocking context-missing result or domain error and SHALL not return an empty blocker list.

5.10 WHEN the System evaluates formal release, THE System SHALL preserve every blocker produced by the existing `validate_formal_gate`, `collect_outbound_blockers`, `policy.assess`, and `authorize_dispatch` behavior while adding any stricter formal-release blockers.

### Requirement 6: Mandatory legal review evidence

**User Story:** As an approver, I want source review and request-specific legal confirmations to be mandatory but distinct from send approval, so that a review record cannot silently authorize a network call.

#### Acceptance Criteria

6.1 WHEN the System evaluates G1, THE System SHALL require a named 法01 source-human-review receipt containing the adopted fact set, reviewer identity, reviewer role, confirmation time, and evidence artifact hash.

6.2 WHEN the System evaluates G2 for LA-001, THE System SHALL require the exact “本次可用” authorization statement, matching organization authorization, exact release tuple, validity period, named signer evidence, and artifact hash from the existing 法02 template.

6.3 WHEN the System evaluates G2 for any of the remaining nine cases, THE System SHALL return a blocking non-pass result regardless of other evidence.

6.4 WHEN the System evaluates G7, G8, or G9 legal confirmation, THE System SHALL require the corresponding named, artifact-hash-bound 法08, 法09, or 法10 receipt to reference the same Canonical Request Hash as G6 and the hash of the corresponding technical evidence.

6.5 WHEN the System creates or updates a `ManualApprovalRecord` or approval-workspace legal conclusion, THE System SHALL leave G10, `dispatch_allowed`, One-Time Grant count, product capacity, and Actual Provider Attempt count unchanged.

6.6 WHEN the System records legal review and G10 approval, THE System SHALL audit legal-review identity, role, and time separately from G10 approver identity, role, and time.

6.7 WHEN one natural person performs legal review and G10 approval under different roles, THE System SHALL represent one natural person with two role-specific actions rather than two independent reviewers.

### Requirement 7: Frozen request and hash binding

**User Story:** As a reviewer, I want all downstream evidence bound to one canonical request hash, so that approval cannot drift to changed content or infrastructure.

#### Acceptance Criteria

7.1 WHEN the System freezes G6, THE System SHALL include the wire payload, prompt, exact primary endpoint, model, provider-profile hash, Runtime Pack hash, material versions, rule versions, task version, mapping version, ledger version, combination-input hash, attack-protocol hashes, and Verified Build Manifest hash in the canonical frozen input.

7.2 WHEN the System computes the Canonical Request Hash, THE System SHALL exclude approval state, grant state, provider response, and runtime attempt records from the canonical frozen input.

7.3 WHEN two canonical frozen inputs are byte-equivalent after canonicalization, THE System SHALL produce equal Canonical Request Hash values.

7.4 WHEN any frozen dependency changes, THE System SHALL produce a different Canonical Request Hash and invalidate G7 through G10 evidence, gate snapshots, pending intents, and unclaimed One-Time Grants bound to the former hash.

7.5 WHEN the System constructs the formal wire payload, THE System SHALL exclude mappings, original identity values, local text, anchors, raw source text, and other local-only identity material.

7.6 WHEN the System freezes a formal release recipient, THE System SHALL include exactly one reviewed D primary recipient and SHALL reject inferred, auto-added, fallback, or standby recipients.

7.7 IF any mandatory frozen dependency is absent or cannot be canonicalized, THEN THE System SHALL reject the freeze operation without persisting a Frozen Formal Request or Canonical Request Hash.

### Requirement 8: Request-bound isolation receipt

**User Story:** As an approver, I want G9 to prove the environment for this exact request, so that a historical global probe cannot authorize a different request or deployment.

#### Acceptance Criteria

8.1 WHEN the System evaluates G9, THE System SHALL treat the global `isolation_verified` boolean as migration information that cannot independently satisfy G9.

8.2 WHEN the System issues a Request-Bound Isolation Receipt, THE System SHALL bind the receipt to the Canonical Request Hash, Verified Build Manifest hash, deployment identity, Compose hash, image digests, probe-output hash, host-firewall evidence hash, and supply-chain evidence hash.

8.3 WHEN the System records G9 probes, THE System SHALL use the five existing names `api_no_egress`, `worker_no_egress`, `gateway_no_case_volume`, `redteam_no_secrets`, and `benchmark_no_secrets` without renaming.

8.4 WHEN the System evaluates a Request-Bound Isolation Receipt, THE System SHALL require all five named probe values to equal `true`.

8.5 IF the deployment mode is `native`, THEN THE System SHALL reject Request-Bound Isolation Receipt issuance and return a non-pass G9 result.

8.6 WHEN the System issues a technical Request-Bound Isolation Receipt, THE System SHALL set the receipt to `pending_legal_confirmation` with an expiry exactly 30 minutes after issuance and SHALL change the receipt to `valid` only after a named 法10 confirmation referencing the same Canonical Request Hash and technical-receipt hash is recorded before expiry.

8.7 IF a Request-Bound Isolation Receipt is mismatched, expired, revoked, historical, incomplete, still pending, or lacks a matching 法10 confirmation, THEN THE System SHALL block approval and dispatch.

### Requirement 9: Enforced product release latch

**User Story:** As a product owner, I want the product latch enforced in every network-capable layer, so that it cannot remain a display-only status.

#### Acceptance Criteria

9.1 WHEN the System handles API approval, API enqueue, worker send, or gateway dispatch, THE System SHALL enforce G-product through the authoritative evaluator or a phase-current verified snapshot.

9.2 WHILE no valid Formal Release Policy exists for the exact Formal Context, THE System SHALL return G-product state `blocked`.

9.3 WHEN the System installs a Formal Release Policy, THE System SHALL limit the policy to exactly `LA-001 × R_fact_summary × D_DeepSeek_official_API`, one Verified Build Manifest, one provider-profile hash, one target/model pair, a validity duration from 1 second through 24 hours inclusive, and `maximum_dispatches=1`.

9.4 IF a first-release policy contains a wildcard, multiple cases, multiple purposes, multiple recipients, multiple targets, multiple models, a validity duration outside 1 second through 24 hours, or a dispatch maximum other than one, THEN THE System SHALL reject the policy without arming G-product.

9.5 WHEN the System installs a valid Formal Release Policy, THE System SHALL leave G1 through G10 evidence, approval state, One-Time Grant count, and Actual Provider Attempt count unchanged.

9.6 WHEN the independent gateway successfully claims the request ID, One-Time Grant nonce, and product-policy slot, THE System SHALL atomically mark the sole policy slot `consumed` before provider network I/O and reject every later grant or attempt under that policy.

9.7 WHEN a caller queries product dispatch capability without complete Formal Context, THE System SHALL return `blocked` without advertising a global `enabled` state.

### Requirement 10: Build and deployment provenance

**User Story:** As a release engineer, I want source, documentation, frontend, wheel, pack, and images tied to one manifest, so that formal behavior cannot differ from the reviewed build.

#### Acceptance Criteria

10.1 WHEN the System creates a Verified Build Manifest, THE System SHALL include a clean source commit, source-tree hash, documentation hash, frontend-build hash, wheel hash, lockfile hashes, Runtime Pack hash, image digests, migration revision, and validation-results hash.

10.2 IF the worktree is dirty, THEN THE System SHALL produce at most a Pending Build Manifest and keep G-product unarmed.

10.3 WHEN the System evaluates API approval, API enqueue, worker send, or gateway dispatch, THE System SHALL require the API, worker, and gateway runtime build identities to equal the Verified Build Manifest identity frozen into the request.

10.4 WHEN a document, source tree, frontend bundle, wheel, Runtime Pack, container image, lockfile, migration revision, or validation result drifts from the Verified Build Manifest, THE System SHALL invalidate the manifest for formal release and require a new verified manifest and request freeze.

10.5 WHEN the System rolls back to an older application build, THE System SHALL revoke the active Formal Release Policy and every unclaimed dependent One-Time Grant before the older API, worker, or gateway process starts.

### Requirement 11: One-time G10 approval

**User Story:** As an approver, I want to authorize exactly one attempt for one reviewed request, so that approval cannot be reused or broadened.

#### Acceptance Criteria

11.1 WHEN a caller invokes `approve_once`, THE System SHALL require an authenticated actor with a nonempty stable identity and role `approver`.

11.2 WHEN the System processes `approve_once`, THE System SHALL require the submitted Canonical Request Hash and approval-eligible gate-snapshot hash to equal the current stored values.

11.3 WHEN `approve_once` succeeds, THE System SHALL atomically create one G10 receipt and one random One-Time Grant expiring exactly 30 minutes after issuance and bound to the exact tuple, Canonical Request Hash, evidence-manifest hash, Verified Build Manifest hash, and Formal Release Policy ID.

11.4 WHEN `approve_once` succeeds, THE System SHALL leave provider network-attempt count and Gateway Record count unchanged.

11.5 WHEN concurrent `approve_once` calls target the same Canonical Request Hash, THE System SHALL create at most one active or consumed One-Time Grant.

11.6 IF a One-Time Grant is expired, revoked, claimed, consumed, bound to stale evidence, or presented for a different request, tuple, build, target, model, or policy, THEN THE System SHALL reject the grant before provider network I/O.

11.7 WHEN a One-Time Grant has been claimed or an attempt has failed before disclosure, THE System SHALL keep the grant non-reusable and require a fresh gate evaluation and named approval for any later attempt.

### Requirement 12: Atomic reservation, claim, and idempotency

**User Story:** As an operator, I want crashes and retries to preserve at-most-once external attempts, so that recovery cannot duplicate disclosure.

#### Acceptance Criteria

12.1 WHEN the System reserves an approved formal dispatch, THE System SHALL atomically persist the dispatch intent, outbox event, ledger version, and One-Time Grant reservation state in one transaction.

12.2 WHEN a worker processes a formal dispatch intent, THE System SHALL re-run `authorize_dispatch` and complete formal gate validation before contacting the independent gateway.

12.3 WHEN the independent gateway receives a formal envelope, THE System SHALL independently verify the envelope signature, Canonical Request Hash, One-Time Grant, evidence manifest, Verified Build Manifest, exact target and model, primary-only topology, wire contract, and G-product state.

12.4 WHEN the independent gateway accepts a new formal envelope, THE System SHALL atomically claim the request ID, One-Time Grant nonce, and Formal Release Policy slot and persist a `sending` Gateway Record before provider network I/O.

12.5 WHEN the independent gateway receives a repeated request ID or One-Time Grant nonce, THE System SHALL return the existing Gateway Record for an identical envelope or a fail-closed idempotency conflict for a non-identical envelope, with zero new provider network attempts in either case.

12.6 WHEN the independent gateway contacts the provider, THE System SHALL disable redirects and restrict the exact endpoint to the existing allowlist entry frozen into the request.

12.7 IF a complete valid provider response is not durably recorded within 90 seconds after provider network I/O begins, THEN THE System SHALL record the outcome as `unknown` or possible disclosure and keep the One-Time Grant and Formal Release Policy slot consumed.

12.8 WHEN an attempt is `unknown`, possible disclosure, or otherwise claimed, THE System SHALL reject automatic retry and recipient switching.

12.9 WHEN the System reconciles a formal dispatch, THE System SHALL read existing Gateway Record state without contacting the provider or creating a new provider network attempt.

### Requirement 13: Revalidation and revocation

**User Story:** As a governance operator, I want every dependency rechecked and revocable before claim, so that stale evidence cannot remain silently usable.

#### Acceptance Criteria

13.1 WHEN the System processes approval, enqueue, worker-send, or gateway dispatch, THE System SHALL revalidate the Runtime Pack, provider profile, evidence, Verified Build Manifest, material versions, ledger version, Request-Bound Isolation Receipt, approval expiry, One-Time Grant state, and Formal Release Policy state applicable to that phase.

13.2 WHEN referenced evidence, a Runtime Pack, provider profile, Verified Build Manifest, or Formal Release Policy is revoked, THE System SHALL invalidate every dependent unclaimed One-Time Grant and pending dispatch intent.

13.3 WHEN a provider profile changes or expires, THE System SHALL block dispatch even when the former provider-profile hash was approved.

13.4 WHEN the ledger version changes, THE System SHALL invalidate the request's cumulative-disclosure assumptions and require a new request freeze.

13.5 WHEN revocation occurs after gateway claim, THE System SHALL preserve the historical Gateway Record and audit chain and SHALL describe the outcome according to recorded transmission evidence rather than as `prevented`.

13.6 IF a claimed request cannot be proven undisclosed, THEN THE System SHALL retain the request as consumed and `unknown` or possible disclosure and keep the request non-retryable.

### Requirement 14: Audit and evidence manifest

**User Story:** As an auditor, I want a tamper-evident, hash-centered record of every decision without case plaintext, so that the single dispatch can be reconstructed safely.

#### Acceptance Criteria

14.1 WHEN the System completes an import, review, evidence registration, gate evaluation, freeze, invalidation, approval, reservation, claim, provider outcome, revocation, reconciliation, or policy-consumption action, THE System SHALL append an immutable audit record for the action.

14.2 WHEN the System appends an audit record, THE System SHALL include stable actor ID, role, timestamp, Canonical Request Hash when applicable, relevant artifact hashes, previous-record hash, action, status, and reason code.

14.3 WHEN the System writes or exports audit data, THE System SHALL exclude API keys, mappings, original identity values, raw case text, complete request bodies, protected evidence content, and provider error bodies.

14.4 WHEN an authorized auditor requests an evidence manifest by Canonical Request Hash, THE System SHALL export the referenced artifact and receipt identifiers, hashes, statuses, and relationships without copying protected evidence content into source control.

14.5 WHEN a user is deactivated or deleted, THE System SHALL retain the user's stable historical audit identity in existing records.

14.6 WHEN the System exports formal-release audit state, THE System SHALL distinguish approved, claimed, complete, `unknown`, failed-before-disclosure, revoked, and expired states.

14.7 IF the required audit append or previous-record hash verification fails, THEN THE System SHALL roll back the associated state transition and leave approval, reservation, claim, policy-consumption, and provider network-attempt counts unchanged.

### Requirement 15: Compatibility and user experience

**User Story:** As a workstation user, I want the stricter release model to coexist with current local and demo workflows, so that safety improvements do not misrepresent or break unrelated capabilities.

#### Acceptance Criteria

15.1 WHEN the System runs demo mock or local deterministic task execution, THE System SHALL operate without requiring a Formal Release Policy or G1 through G10 formal receipts.

15.2 WHEN the System presents a formal-workbench status, THE System SHALL display legal disposition, system readiness, approval eligibility, dispatch allowance, product-latch state, and One-Time Grant state as six separate status classes.

15.3 WHEN the approval workspace displays a legal-review conclusion, THE System SHALL state that the conclusion does not grant G10 approval, create a One-Time Grant, or authorize dispatch.

15.4 WHEN the System returns a Gate Decision, THE System SHALL identify existing G identifiers, reason codes, statuses, and the next evidence action without displaying protected evidence content.

15.5 WHEN the System labels repository packs, the current ten cases, historical Compose probes, or engineering attack baselines, THE System SHALL preserve their actual draft, layer-A, historical, or engineering status rather than label the assets formally approved, published, legally resisted, or dispatch-enabled.

15.6 WHEN the UI or API receives a Conflict Response, THE System SHALL present the response as an expected gate outcome and SHALL suppress automatic retry, bypass guidance, and blind-retry prompts.

### Requirement 16: Rollout, first attempt, and rollback

**User Story:** As a release manager, I want a phased rollout and automatic re-closure, so that capability can be tested without silently becoming a standing outbound channel.

#### Acceptance Criteria

16.1 WHEN the System enters Phase 0, THE System SHALL add schemas and validation while keeping G-product `blocked`.

16.2 WHEN the System enters Phase 1, THE System SHALL import only Existing Legal Assets and run shadow evaluation without changing task approval, One-Time Grant, product-policy consumption, Gateway Record, or dispatch state.

16.3 WHEN the System enters Phase 2, THE System SHALL exercise the complete one-time flow in isolated staging with synthetic material and a local fake provider while recording zero external-provider network attempts and zero real dispatches.

16.4 WHEN the System enters Phase 3, THE System SHALL permit only `LA-001 × R_fact_summary × D_DeepSeek_official_API` to become `armed_once` after a Verified Build Manifest and genuinely completed, valid receipts from Existing Legal Assets are bound to the same Canonical Request Hash.

16.5 WHEN the System enters Phase 4, THE System SHALL permit at most one gateway claim and SHALL atomically consume and re-close the Formal Release Policy for a complete or `unknown` outcome.

16.6 WHEN the System records the first real result using the existing 配05 structure, THE System SHALL derive the result only from Gateway Record evidence and SHALL leave success fields unset before that evidence exists.

16.7 WHEN rollback begins, THE System SHALL revoke the Formal Release Policy and every unclaimed One-Time Grant while preserving claimed, `sending`, complete, and `unknown` Gateway Records and their audit history.

16.8 WHEN an LA-001 attempt succeeds, THE System SHALL leave G2 status, Formal Release Policy scope, and dispatch availability for every other case unchanged and blocked.

16.9 IF Phase 0, Phase 1, Phase 2, or Phase 3 has not completed its required fail-closed checks, THEN THE System SHALL block entry into every later numbered phase.
