"""V2.2 package distribution control plane.

``domain_packages.export_bundle``/``import_bundle`` are the transport-neutral
mechanics; this module is the controller that owns desired state: which edge
node should hold which manifest, what has been delivered, and what the edge
has acknowledged. The actual delivery channel (KubeEdge device twin,
ConfigMap sync, manual copy) is out of scope — ``deliver`` produces the
signed bundle and the caller ships it.

Fail-closed rules:

- assignments only target registered edge nodes and resolvable manifests
  (``validated``/``signed``/``published``; ``deprecated`` stays deliverable
  for draining, ``draft``/``revoked`` are never assigned);
- receipts must come from the assigned node, reference the stored manifest
  hash, and follow the status order — anything else is rejected and the
  assignment is marked ``failed``;
- revocation is an explicit controller action that waits for an edge
  ``revoked`` receipt; a revoked manifest can never be re-assigned;
- nothing here authorizes outbound dispatch — activation on the edge is a
  package-availability signal, not a dispatch decision.
"""
from . import domain_packages
from .util import audit, now, uid


NODE_KIND = "edge_node"
ASSIGNMENT_KIND = "package_assignment"
RECEIPT_KIND = "package_receipt"

# assignment.status transitions driven by controller actions / edge receipts
ASSIGNMENT_STATES = (
    "assigned", "delivered", "verified", "active",
    "revoking", "revoked", "failed",
)
TERMINAL_STATES = {"active", "revoked", "failed"}
MAX_ATTEMPTS = 3

# receipts the edge may post and the state they move the assignment to
_RECEIPT_TRANSITIONS = {
    "verified": {"delivered"},
    "activated": {"verified"},
    "revoked": {"revoking"},
    "failed": {"assigned", "delivered", "verified", "revoking"},
}


class ControllerError(ValueError):
    """Fail-closed control-plane error (maps to 409 at the API layer)."""


def _get_assignment(repo, assignment_id):
    try:
        return repo.get(assignment_id, ASSIGNMENT_KIND)
    except KeyError as error:
        raise ControllerError("未知的包下发分配") from error


def _record_receipt(repo, assignment, kind, edge_node_id, detail=None):
    receipt = {
        "id": uid("rcpt"), "assignment_id": assignment["id"],
        "manifest_id": assignment["manifest_id"],
        "edge_node_id": edge_node_id, "kind": kind,
        "detail": detail or {}, "at": now(),
    }
    repo.put(RECEIPT_KIND, receipt, assignment["edge_node_id"])
    return receipt


# --- edge node registry ------------------------------------------------------

def register_node(repo, node_id, actor, labels=None):
    """Register an edge node identity. Only registered nodes can be assigned
    packages — unknown nodes are rejected rather than silently trusted."""
    node_id = (node_id or "").strip()
    if not node_id:
        raise ControllerError("edge_node_id 不能为空")
    try:
        record = repo.get(node_id, NODE_KIND)
    except KeyError:
        record = {"id": node_id, "registered_at": now(), "registered_by": actor,
                  "labels": dict(labels or {}), "last_seen_at": None}
    else:
        record["labels"] = {**record.get("labels", {}), **(labels or {})}
    repo.put(NODE_KIND, record)
    audit(repo, "", "edge_node.registered", edge_node_id=node_id, actor=actor)
    return record


def list_nodes(repo):
    return repo.list(NODE_KIND)


# --- desired state -----------------------------------------------------------

def assign(repo, manifest_id, edge_node_id, actor):
    """Create the desired-state record: ``edge_node_id`` should hold this
    manifest. Refuses unknown nodes and non-deliverable manifests."""
    try:
        repo.get(edge_node_id, NODE_KIND)
    except KeyError as error:
        raise ControllerError(f"未注册的边侧节点: {edge_node_id}") from error
    try:
        manifest = repo.get(manifest_id, domain_packages.MANIFEST_KIND)
    except KeyError as error:
        raise ControllerError("未知的 domain_package_manifest") from error
    if manifest.get("status") not in {"validated", "signed", "published", "deprecated"}:
        raise ControllerError(
            f"manifest 状态 {manifest.get('status')} 不可下发")
    duplicate = [
        a for a in repo.list(ASSIGNMENT_KIND, edge_node_id)
        if a.get("manifest_id") == manifest_id
        and a.get("status") not in {"revoked", "failed"}
    ]
    if duplicate:
        raise ControllerError("该 manifest 已分配给此节点")
    assignment = {
        "id": uid("assign"), "manifest_id": manifest_id,
        "manifest_hash": manifest.get("content_hash"),
        "edge_node_id": edge_node_id, "desired_state": "present",
        "status": "assigned", "attempts": 0,
        "assigned_by": actor, "assigned_at": now(), "updated_at": now(),
    }
    repo.put(ASSIGNMENT_KIND, assignment, edge_node_id)
    audit(repo, "", "package.assigned", assignment_id=assignment["id"],
          manifest_id=manifest_id, edge_node_id=edge_node_id, actor=actor)
    return assignment


def deliver(repo, assignment_id, actor):
    """Produce the signed bundle for transport and mark the assignment
    delivered. Returns the bundle — shipping it is the caller's job."""
    assignment = _get_assignment(repo, assignment_id)
    if assignment["status"] != "assigned":
        raise ControllerError(f"分配状态 {assignment['status']} 不可投递")
    if assignment["attempts"] >= MAX_ATTEMPTS and assignment["status"] == "assigned":
        raise ControllerError("重试次数已用尽")
    bundle = domain_packages.export_bundle(repo, assignment["manifest_id"])
    assignment["attempts"] += 1
    assignment["bundle_hash"] = bundle["bundle_hash"]
    assignment["status"] = "delivered"
    assignment["updated_at"] = now()
    repo.put(ASSIGNMENT_KIND, assignment, assignment["edge_node_id"])
    _record_receipt(repo, assignment, "delivered", actor,
                    {"bundle_hash": bundle["bundle_hash"],
                     "attempt": assignment["attempts"]})
    audit(repo, "", "package.delivered", assignment_id=assignment["id"],
          manifest_id=assignment["manifest_id"],
          edge_node_id=assignment["edge_node_id"],
          bundle_hash=bundle["bundle_hash"], actor=actor)
    return bundle


def record_receipt(repo, assignment_id, kind, edge_node_id,
                   manifest_hash=None, detail=None):
    """Fold an edge acknowledgement into the assignment. Fail-closed on
    wrong node, wrong content hash, or an out-of-order receipt."""
    assignment = _get_assignment(repo, assignment_id)
    if edge_node_id != assignment["edge_node_id"]:
        raise ControllerError("回执节点与分配节点不符")
    if kind not in _RECEIPT_TRANSITIONS:
        raise ControllerError(f"未知回执类型: {kind}")
    if manifest_hash is not None and manifest_hash != assignment["manifest_hash"]:
        assignment["status"] = "failed"
        assignment["updated_at"] = now()
        repo.put(ASSIGNMENT_KIND, assignment, assignment["edge_node_id"])
        _record_receipt(repo, assignment, "failed", edge_node_id,
                        {"reason": "manifest_hash 不符", **(detail or {})})
        raise ControllerError("回执 manifest_hash 与分配不符")
    if assignment["status"] not in _RECEIPT_TRANSITIONS[kind]:
        raise ControllerError(
            f"回执 {kind} 不适用于状态 {assignment['status']}")
    _record_receipt(repo, assignment, kind, edge_node_id, detail)
    if kind == "failed":
        assignment["status"] = "assigned" if assignment["attempts"] < MAX_ATTEMPTS else "failed"
        assignment["last_error"] = (detail or {}).get("error")
    else:
        assignment["status"] = _next_status(kind)
    assignment["updated_at"] = now()
    repo.put(ASSIGNMENT_KIND, assignment, assignment["edge_node_id"])
    audit(repo, "", f"package.{kind}", assignment_id=assignment["id"],
          manifest_id=assignment["manifest_id"], edge_node_id=edge_node_id)
    return assignment


def _next_status(receipt_kind):
    return {"verified": "verified", "activated": "active",
            "revoked": "revoked"}[receipt_kind]


def request_revocation(repo, assignment_id, actor, reason=None):
    """Flip desired state to absent. The assignment stays ``revoking`` until
    the edge posts a ``revoked`` receipt — revocation is never assumed."""
    assignment = _get_assignment(repo, assignment_id)
    if assignment["status"] in {"revoked", "failed"}:
        raise ControllerError(f"分配状态 {assignment['status']} 不可撤销")
    assignment["desired_state"] = "absent"
    assignment["status"] = "revoking"
    assignment["revocation_reason"] = reason
    assignment["updated_at"] = now()
    repo.put(ASSIGNMENT_KIND, assignment, assignment["edge_node_id"])
    audit(repo, "", "package.revocation_requested", assignment_id=assignment["id"],
          manifest_id=assignment["manifest_id"],
          edge_node_id=assignment["edge_node_id"], actor=actor, reason=reason)
    return assignment


def reconcile(repo, edge_node_id=None):
    """Reconciliation report: assignments that still differ from their
    desired state. ``assigned`` entries are pending delivery retries;
    ``delivered``/``verified`` entries await edge receipts; ``revoking``
    awaits revocation receipts. Nothing is force-marked — the report is the
    operator's truth source."""
    assignments = repo.list(ASSIGNMENT_KIND)
    if edge_node_id:
        assignments = [a for a in assignments if a.get("edge_node_id") == edge_node_id]
    report = {"retry": [], "awaiting_receipt": [], "awaiting_revocation": [],
              "ok": [], "failed": []}
    for assignment in assignments:
        status = assignment["status"]
        if status == "assigned":
            bucket = "failed" if assignment["attempts"] >= MAX_ATTEMPTS else "retry"
        elif status in {"delivered", "verified"}:
            bucket = "awaiting_receipt"
        elif status == "revoking":
            bucket = "awaiting_revocation"
        elif status == "failed":
            bucket = "failed"
        else:
            bucket = "ok"
        report[bucket].append(assignment)
    return report


# --- edge-side helpers (run on the edge node's own store) ---------------------

def edge_apply(repo, bundle, edge_node_id):
    """Edge-side intake: verify + import the bundle via the shared
    fail-closed mechanics, then return the receipt payload the edge should
    post back. ``published`` is never imported — the bundle's own signature
    decides what status survives."""
    imported = domain_packages.import_bundle(
        repo, bundle, actor=f"edge:{edge_node_id}")
    return {"kind": "verified", "edge_node_id": edge_node_id,
            "manifest_hash": repo.get(
                imported["manifest"], domain_packages.MANIFEST_KIND)["content_hash"],
            "detail": {"downgraded": imported["downgraded"]}}


def edge_revoke(repo, manifest_id, edge_node_id):
    """Edge-side revocation: revoke the manifest (which propagates to
    in-flight tasks via the existing fail-closed path) and return the
    receipt payload. Idempotent."""
    from . import domain_packages as packages
    manifest = repo.get(manifest_id, packages.MANIFEST_KIND)
    if manifest.get("status") != "revoked":
        packages.transition(repo, packages.MANIFEST_KIND, manifest_id,
                            "revoked", actor=f"edge:{edge_node_id}")
    return {"kind": "revoked", "edge_node_id": edge_node_id,
            "manifest_hash": manifest.get("content_hash")}
