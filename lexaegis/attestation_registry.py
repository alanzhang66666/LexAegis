"""Production trust-anchor registry for V3 scoped attestation reuse.

This module persists and resolves externally signed scope attestations against
an out-of-repository trust anchor, and exposes a read-only verdict that the
four-gate orchestrator may add as an extra fail-closed member.

What it proves: a holder of a configured Ed25519 key signed a statement whose
scope equals the scope derived from the current frozen request, and the
attestation is absent from a fresh, non-truncating revocation snapshot.

What it does NOT prove: that the signer is a real lawyer or DPO, that the
organisation is authorised, that PIA/CTIA were performed, that evidence bytes
were read, or that the claim is legally correct. ``grants_reuse`` is always
False: an attestation never replaces a per-request gate, never authorises
dispatch, and never widens an existing check. Replacing the per-request
G3/G5/isolation receipts with a standing attestation is a legal-semantics
decision that this module deliberately does not implement.
"""
from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path

from .scoped_attestation_shadow import (
    AttestationStatement,
    AuthenticatedAttestation,
    AuthenticatedRevocations,
    DeploymentScope,
    PolicyScope,
    RecipientScope,
    RevocationStatement,
    TrustedKey,
    inspect_attestation,
)
from .util import digest

ATTESTATION_KIND = "v3_attestation"
REVOCATION_KIND = "v3_revocation"
GUARD_ENV = "LEX_V3_ATTESTATION_GUARD"
ANCHOR_ENV = "LEX_V3_TRUST_ANCHOR"
ANCHOR_SCHEMA = 1
PASS, FAIL, UNKNOWN = "pass", "fail", "unknown"
NOTICE = ("仅校验外部签名、范围、有效期与撤销快照；不证明签署人资质、组织授权、"
          "PIA/CTIA 或法律正确性，也不授予复用、批准或发送权限。")


class AttestationRegistryError(ValueError):
    """The attestation registry state cannot be trusted."""


def guard_enabled():
    """Opt-in only: an unset or different value changes no existing behaviour."""
    return os.getenv(GUARD_ENV, "").strip() == "1"


def _sha256(value):
    """Normalise a bare hex digest or an already-prefixed value; None if unusable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.startswith("sha256:"):
        text = text[len("sha256:"):]
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        return None
    return "sha256:" + text


def _utc(value):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise AttestationRegistryError("invalid timestamp") from exc
    else:
        raise AttestationRegistryError("timestamp must be an ISO string or datetime")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AttestationRegistryError("timezone-aware timestamp required")
    return parsed.astimezone(timezone.utc)


def _unconfigured(reason):
    return {"state": "unconfigured", "loaded": False, "reasons": [reason],
            "authoritative": False}


def _anchor_permissions_ok(info, *, posix=None):
    """Judge POSIX group/other write bits; report honestly where they do not exist.

    On Windows ``os.stat`` synthesises writable bits for every user-writable
    file, so the POSIX test would reject every real anchor. There is no
    equivalent stdlib ACL check, so the verdict is reported as unverified
    rather than faked as passed: an administrator must still keep the anchor
    file writable only by the service account.
    """
    posix = (os.name == "posix") if posix is None else posix
    if not posix:
        return True, "unsupported_platform"
    return not (info.st_mode & 0o022), "posix_mode"


def load_anchor(path=None):
    """Read the external trust anchor. Never falls back to a repository default.

    The anchor must be an absolute path to a regular file that group and other
    users cannot write; otherwise a local attacker could substitute keys.
    """
    target = os.getenv(ANCHOR_ENV, "").strip() if path is None else str(path)
    if not target:
        return _unconfigured("trust_anchor_unconfigured")
    anchor_path = Path(target)
    if not anchor_path.is_absolute():
        return _unconfigured("trust_anchor_must_be_absolute")
    try:
        info = anchor_path.stat()
    except OSError:
        return _unconfigured("trust_anchor_missing")
    if not stat.S_ISREG(info.st_mode):
        return _unconfigured("trust_anchor_not_a_regular_file")
    permissions_ok, permission_check = _anchor_permissions_ok(info)
    if not permissions_ok:
        return _unconfigured("trust_anchor_writable_by_others")
    try:
        document = json.loads(anchor_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _unconfigured("trust_anchor_unreadable")
    if not isinstance(document, dict) or document.get("schema_version") != ANCHOR_SCHEMA:
        return _unconfigured("trust_anchor_schema_invalid")
    try:
        keys = {}
        for item in document.get("trusted_keys") or []:
            key = TrustedKey(
                key_id=item["key_id"], owner_id=item["owner_id"], role=item["role"],
                purpose=item["purpose"],
                allowed_scopes=frozenset(item.get("allowed_scopes") or ()),
                public_key=bytes.fromhex(item["public_key_hex"]),
                active=bool(item.get("active", True)),
            )
            keys[key.key_id] = key
        revocation = document.get("revocation") or {}
        providers = {str(pid): {"jurisdiction": str(item["jurisdiction"]),
                                "processing_region": str(item["processing_region"])}
                     for pid, item in (document.get("providers") or {}).items()}
        policies = {str(domain): str(juris)
                    for domain, juris in (document.get("policy_jurisdictions") or {}).items()}
    except (KeyError, TypeError, ValueError):
        return _unconfigured("trust_anchor_invalid")
    if not keys:
        return _unconfigured("trust_anchor_has_no_keys")
    return {
        "state": "loaded", "loaded": True, "reasons": [], "authoritative": False,
        "permission_check": permission_check,
        "trusted_keys": keys,
        "authority_id": str(revocation.get("authority_id") or ""),
        "ledger_id": str(revocation.get("ledger_id") or ""),
        "minimum_sequence": revocation.get("minimum_sequence"),
        "known_revoked_ids": frozenset(revocation.get("known_revoked_ids") or ()),
        "network_policy_hash": _sha256(document.get("network_policy_hash")),
        "providers": providers,
        "policy_jurisdictions": policies,
    }


def _plain(value):
    """Accept a contract model or a plain mapping for the same field access."""
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


def expected_scopes(frozen, task, case, anchor):
    """Derive the exact scopes a standing attestation would have to cover.

    Every field comes from the frozen request, the persisted case/task, or the
    external anchor. Anything that cannot be derived is reported as a reason
    instead of being guessed, so a missing fact can never read as a pass.
    """
    reasons = []
    frozen = _plain(frozen) or {}
    task = task or {}
    case = case or {}
    anchor = anchor or {}
    environment = case.get("runtime_profile")
    build_hash = _sha256(frozen.get("build_manifest_hash"))
    network_hash = anchor.get("network_policy_hash")
    deployment = None
    if environment not in {"production", "integration"}:
        reasons.append("deployment_environment_unknown")
    elif not build_hash:
        reasons.append("deployment_build_hash_missing")
    elif not network_hash:
        reasons.append("deployment_network_policy_hash_missing")
    else:
        deployment = DeploymentScope(kind="deployment", environment=environment,
                                     build_manifest_hash=build_hash,
                                     network_policy_hash=network_hash)
    tuple_ = frozen.get("tuple") or {}
    purpose = tuple_.get("purpose")
    recipient_scope = _recipient_scope(frozen, tuple_, anchor, reasons, suffix="")
    standby_scope = None
    if frozen.get("standby_provider_id"):
        standby_scope = _recipient_scope(frozen, tuple_, anchor, reasons, suffix="standby_",
                                         provider_id=frozen.get("standby_provider_id"),
                                         target=frozen.get("standby_target"),
                                         model=frozen.get("standby_model"),
                                         profile_hash=frozen.get("standby_provider_profile_hash"))
    domain = case.get("domain")
    pack_id = task.get("pack_id")
    pack_hash = _sha256(frozen.get("runtime_pack_hash"))
    policy = None
    if not purpose:
        reasons.append("policy_purpose_missing")
    if not domain or not pack_id:
        reasons.append("policy_scope_incomplete")
    elif not pack_hash:
        reasons.append("policy_pack_hash_missing")
    else:
        jurisdiction = (anchor.get("policy_jurisdictions") or {}).get(str(domain))
        if not jurisdiction:
            reasons.append("policy_jurisdiction_unconfigured")
        else:
            try:
                policy = PolicyScope(kind="policy", domain=str(domain), pack_id=str(pack_id),
                                     pack_content_hash=pack_hash, jurisdiction=jurisdiction)
            except ValueError:
                reasons.append("policy_scope_invalid")
    return {"deployment": deployment, "recipient": recipient_scope, "standby": standby_scope,
            "policy": policy, "reasons": reasons}


def _recipient_scope(frozen, tuple_, anchor, reasons, *, suffix="", provider_id=None,
                     target=None, model=None, profile_hash=None):
    """Build one slot's recipient scope; primary and standby use the same rules."""
    provider_id = tuple_.get("recipient") if provider_id is None else provider_id
    target = frozen.get("target") if target is None else target
    model = frozen.get("model") if model is None else model
    profile_hash = frozen.get("provider_profile_hash") if profile_hash is None else profile_hash
    purpose = tuple_.get("purpose")
    profile_hash = _sha256(profile_hash)
    if not provider_id or not purpose:
        reasons.append(suffix + "recipient_scope_incomplete")
        return None
    if not target or not model or not profile_hash:
        reasons.append(suffix + "recipient_identity_missing")
        return None
    provider = (anchor.get("providers") or {}).get(str(provider_id))
    if not provider:
        reasons.append(suffix + "recipient_region_unconfigured")
        return None
    try:
        return RecipientScope(kind="recipient", provider_id=str(provider_id),
                              provider_profile_hash=profile_hash, endpoint=str(target),
                              model=str(model), purpose=str(purpose),
                              jurisdiction=provider["jurisdiction"],
                              processing_region=provider["processing_region"])
    except (KeyError, ValueError):
        reasons.append(suffix + "recipient_scope_invalid")
        return None


def _revocation_snapshot(repo):
    record = None
    for item in repo.list(REVOCATION_KIND):
        if isinstance(item, dict) and item.get("record_type") == REVOCATION_KIND:
            record = item
    if record is None:
        return None
    try:
        return AuthenticatedRevocations.model_validate(record["snapshot"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AttestationRegistryError("revocation_record_invalid") from exc


def ingest_attestation(repo, proof, anchor, at):
    """Persist one signed attestation after verifying it against the anchor."""
    if not isinstance(proof, AuthenticatedAttestation):
        raise AttestationRegistryError("attestation_payload_invalid")
    if not anchor or anchor.get("loaded") is not True:
        raise AttestationRegistryError("trust_anchor_unconfigured")
    statement = proof.statement
    verdict = inspect_attestation(
        proof, statement.scope, None, trusted_keys=anchor["trusted_keys"],
        expected_revocation_authority=anchor["authority_id"], expected_ledger_id=anchor["ledger_id"],
        minimum_revocation_sequence=anchor["minimum_sequence"] or 1,
        minimum_revoked_ids=anchor["known_revoked_ids"], at=_utc(at))
    # A revocation snapshot is required before an attestation may be stored.
    blocking = [reason for reason in verdict["reasons"] if reason != "revocation_snapshot_missing"]
    if blocking:
        raise AttestationRegistryError(";".join(blocking))
    content = digest(statement.model_dump(mode="json"))
    record_id = "v3-attestation-" + statement.attestation_id
    previous = None
    try:
        previous = repo.get(record_id, ATTESTATION_KIND)
    except KeyError:
        previous = None
    if previous is not None and previous.get("content_hash") != content:
        raise AttestationRegistryError("attestation_id_conflict")
    stored = {"id": record_id, "record_type": ATTESTATION_KIND, "attestation_id": statement.attestation_id,
              "content_hash": content, "attestation": proof.model_dump(mode="json"),
              "ingested_at": _utc(at).isoformat()}
    repo.put(ATTESTATION_KIND, stored)
    return {"state": "stored", "attestation_id": statement.attestation_id,
            "scope_kind": statement.scope.kind, "content_hash": content, "authoritative": False}


def ingest_revocations(repo, snapshot, anchor, at):
    """Store a signed revocation snapshot only if it is fresh and never shrinks."""
    if not isinstance(snapshot, AuthenticatedRevocations):
        raise AttestationRegistryError("revocation_snapshot_invalid")
    if not anchor or anchor.get("loaded") is not True:
        raise AttestationRegistryError("trust_anchor_unconfigured")
    statement = snapshot.statement
    if statement.authority_id != anchor["authority_id"] or statement.ledger_id != anchor["ledger_id"]:
        raise AttestationRegistryError("revocation_scope_mismatch")
    floor = anchor["minimum_sequence"] or 1
    if not isinstance(floor, int) or isinstance(floor, bool) or floor < 1:
        raise AttestationRegistryError("revocation_sequence_floor_invalid")
    if statement.sequence < floor:
        raise AttestationRegistryError("revocation_sequence_rollback")
    if not anchor["known_revoked_ids"].issubset(statement.revoked_attestation_ids):
        raise AttestationRegistryError("revocation_history_truncated")
    at = _utc(at)
    if not statement.issued_at <= at < statement.valid_until:
        raise AttestationRegistryError("revocation_snapshot_stale")
    previous = _revocation_snapshot(repo)
    if previous is not None:
        if statement.sequence <= previous.statement.sequence:
            raise AttestationRegistryError("revocation_sequence_not_newer")
        if not set(previous.statement.revoked_attestation_ids).issubset(statement.revoked_attestation_ids):
            raise AttestationRegistryError("revocation_history_truncated")
    record_id = "v3-revocation-" + digest({"ledger": statement.ledger_id})[:32]
    repo.put(REVOCATION_KIND, {"id": record_id, "record_type": REVOCATION_KIND,
                               "ledger_id": statement.ledger_id,
                               "sequence": statement.sequence,
                               "snapshot": snapshot.model_dump(mode="json"),
                               "ingested_at": at.isoformat()})
    return {"state": "stored", "sequence": statement.sequence, "authoritative": False}


def _resolve_kind(repo, scope, anchor, revocations, at):
    """Return (state, matched ids, reasons) for one required scope."""
    if scope is None:
        return UNKNOWN, [], ["scope_not_derivable"]
    expected = scope.model_dump(mode="json")
    candidates = [item for item in repo.list(ATTESTATION_KIND)
                  if isinstance(item, dict) and isinstance(item.get("attestation"), dict)
                  and (item["attestation"].get("statement") or {}).get("scope") == expected]
    if not candidates:
        return FAIL, [], ["no_attestation_for_scope"]
    reasons = []
    matched = []
    for item in candidates:
        try:
            proof = AuthenticatedAttestation.model_validate(item["attestation"])
        except (TypeError, ValueError):
            reasons.append("stored_attestation_invalid")
            continue
        verdict = inspect_attestation(
            proof, scope, revocations, trusted_keys=anchor["trusted_keys"],
            expected_revocation_authority=anchor["authority_id"],
            expected_ledger_id=anchor["ledger_id"],
            minimum_revocation_sequence=anchor["minimum_sequence"] or 1,
            minimum_revoked_ids=anchor["known_revoked_ids"], at=at)
        if verdict["state"] == "diagnostic_match":
            matched.append(proof.statement.attestation_id)
        else:
            reasons.extend(verdict["reasons"] or ["attestation_not_accepted"])
    if matched:
        return PASS, sorted(matched), []
    return FAIL, [], sorted(set(reasons))


def resolve(repo, frozen, task, case, anchor, at):
    """Verdict for the current request; never authoritative, never grants reuse."""
    if not anchor or anchor.get("loaded") is not True:
        return {"schema_version": 1, "state": anchor.get("state", "unconfigured") if anchor else "unconfigured",
                "authoritative": False, "grants_reuse": False,
                "legal_state": UNKNOWN, "deployment_state": UNKNOWN,
                "matched": {}, "reasons": list((anchor or {}).get("reasons") or []),
                "notice": NOTICE}
    at = _utc(at)
    scopes = expected_scopes(frozen, task, case, anchor)
    try:
        revocations = _revocation_snapshot(repo)
    except AttestationRegistryError as exc:
        revocations = None
        scopes["reasons"].append(str(exc))
    results = {}
    for key in ("recipient", "standby", "policy", "deployment"):
        results[key] = _resolve_kind(repo, scopes.get(key), anchor, revocations, at)
    legal_parts = [results["recipient"], results["policy"]]
    if scopes.get("standby") is not None or scopes.get("reasons"):
        if scopes.get("standby") is not None:
            legal_parts.append(results["standby"])
    legal_state, legal_matched, legal_reasons = _combine(legal_parts)
    deployment_state, deployment_matched, deployment_reasons = _combine([results["deployment"]])
    reasons = sorted(set(scopes.get("reasons") or []) | set(legal_reasons) | set(deployment_reasons))
    satisfied = legal_state == PASS and deployment_state == PASS
    summary = {"legal": legal_state, "deployment": deployment_state,
               "matched": {"legal": legal_matched, "deployment": deployment_matched},
               "revocation_sequence": getattr(getattr(revocations, "statement", None), "sequence", None)}
    return {"schema_version": 1, "state": "satisfied" if satisfied else "blocked",
            "authoritative": False, "grants_reuse": False,
            "legal_state": legal_state, "deployment_state": deployment_state,
            "matched": summary["matched"], "reasons": reasons,
            "revocation_sequence": summary["revocation_sequence"],
            "summary_hash": "sha256:" + digest({"domain": "lexaegis.v3.AttestationResolution",
                                                "value": summary}),
            "notice": NOTICE}


def _combine(parts):
    """Combine member states; any non-pass entry blocks the group."""
    states = [state for state, _matched, _reasons in parts]
    matched = sorted({item for _state, ids, _reasons in parts for item in ids})
    reasons = sorted({reason for _state, _ids, failures in parts for reason in failures})
    if all(state == PASS for state in states):
        return PASS, matched, reasons
    for state in (FAIL, UNKNOWN):
        if state in states:
            return state, matched, reasons
    return UNKNOWN, matched, reasons


def status(repo, frozen, task, case, at):
    """Read-only view for the API; unconfigured by default, never blocking."""
    if not guard_enabled():
        return {"schema_version": 1, "state": "not_enabled", "authoritative": False,
                "grants_reuse": False, "legal_state": UNKNOWN, "deployment_state": UNKNOWN,
                "matched": {}, "reasons": [], "notice": NOTICE}
    return resolve(repo, frozen, task, case, load_anchor(), at)


def gate_members(repo, frozen, task, case, at):
    """Attestation input for the four-gate bundle, or None when the guard is off."""
    if not guard_enabled():
        return None
    return resolve(repo, frozen, task, case, load_anchor(), at)
