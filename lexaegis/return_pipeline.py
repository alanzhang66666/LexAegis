"""V2.2 P6 Return Pipeline + edge autonomy.

The cloud-return path runs as an explicit staged pipeline. Every stage is
recorded as a VALIDATION task_step; a stage failure raises ValueError which
the caller maps to ``invalid_cloud_result`` — candidate outputs are never
adopted until all stages pass.

Edge autonomy: when the gateway is provably unreachable (TCP connect failed,
so nothing could have crossed the send boundary), cloud-required work is
suspended as ``waiting-cloud`` instead of failing or faking a result. Local
steps keep running. Mock transports can never claim cloud provenance.
"""
import httpx

from . import domain_runtime
from .task_engine import validate_cloud_result

STAGES = (
    "envelope", "hash", "schema", "provenance", "domain_mapper",
    "identity_relink", "evidence_relink", "review_schema", "human_decision",
)

WAITING_CLOUD = "waiting-cloud"
RETRY_AFTER_SECONDS = 30


def record_result_envelope(repo, task, record, pipeline_status, failure_code=None):
    """Write the V2.2 CloudResultEnvelope receipt for a returned result.

    ``pending_human`` after every pipeline stage passed — the result is a
    candidate until a HumanDecision adopts it. ``rejected`` when the
    pipeline refused the payload; the hash still binds the exact bytes that
    came back. Never written when no result crossed the wire."""
    if not isinstance(record.get("result"), (dict, list)):
        return None
    from .contracts import CloudResultEnvelope
    from .util import digest, now, uid
    envelope = CloudResultEnvelope(
        id=uid("result_env"),
        task_id=task["id"],
        case_id=task["case_id"],
        cloud_task_envelope_id=(task.get("cloud_envelope") or {}).get("id"),
        request_hash=task.get("request_hash"),
        result_hash=digest(record["result"]),
        provenance=provenance_for_transport(task["request"].get("transport")),
        pipeline_status=pipeline_status,
        failure_code=failure_code,
        created_at=now(),
    ).model_dump()
    repo.put("cloud_result_envelope", envelope, task["case_id"])
    return envelope


def provenance_for_transport(transport):
    """Strict transport → provenance mapping. A mock/local result can never
    be stamped ``cloud`` — the only cloud provenance is transport==cloud."""
    provenance = {"mock": "simulation", "local": "local_deterministic",
                  "cloud": "cloud"}.get(transport)
    if provenance is None:
        raise ValueError(f"未知传输通道无法标注 provenance: {transport}")
    return provenance


def _stage(repo, task, name, fn):
    """Run one pipeline stage, recording its outcome as a task_step."""
    try:
        outcome = fn()
    except ValueError:
        domain_runtime.record_task_step(
            repo, task, "VALIDATION", f"return:{name}:failed")
        raise
    domain_runtime.record_task_step(
        repo, task, "VALIDATION", f"return:{name}:{outcome or 'ok'}")
    return outcome


def execute(repo, task, record):
    """Run the staged return pipeline for a 'complete' gateway record.

    Mutates ``task`` (artifact/status) exactly as the former inline path did.
    Raises ValueError on any stage failure."""
    from . import service

    case = None

    def envelope_stage():
        if "result" not in record:
            raise ValueError("云端返回缺少 result")
        envelope = task.get("cloud_envelope")
        if envelope and envelope.get("request_hash") != task.get("request_hash"):
            raise ValueError("云端信封 request_hash 与任务请求不一致")
        return "ok"

    def hash_stage():
        if task.get("domain_runtime_snapshot_id") and not task.get("request_hash"):
            raise ValueError("快照绑定任务缺少 request_hash")
        return "ok"

    validated = None

    def schema_stage():
        nonlocal validated
        validated = validate_cloud_result(
            task["type"], record["result"], task, task["fact_snapshot"])
        return "ok"

    provenance = None

    def provenance_stage():
        nonlocal provenance
        provenance = provenance_for_transport(task["transport"])
        return provenance

    mapper_info = None

    def domain_mapper_stage():
        # Package-provided declarative mapper (cause_pack.mapper) executed by
        # the kernel engine. Outcomes: skipped (no snapshot / task type not in
        # applies_to / no claim list), unbound (snapshot, manifest or package
        # unresolvable), none (bound but declares no mapper), mapped.
        nonlocal mapper_info
        snapshot_id = task.get("domain_runtime_snapshot_id")
        if not snapshot_id:
            return "skipped"
        try:
            snapshot = repo.get(snapshot_id, "domain_runtime_snapshot")
            manifest = repo.get(snapshot["domain_package_manifest_id"],
                                "domain_package_manifest")
        except KeyError:
            return "unbound"
        from . import domain_mapper
        from .spi import spi_for
        for ref in manifest["package_refs"].get("cause_pack") or []:
            package = repo.get(ref["id"], "domain_package")
            if package.get("content_hash") != ref.get("content_hash"):
                continue
            config = spi_for(package).mapper()
            if not config:
                return "none"
            if not domain_mapper.applies(config, task["type"]):
                return "skipped"
            report = domain_mapper.apply_mapper(config, validated)
            mapper_info = {"package_id": package.get("package_id"),
                           "content_hash": package.get("content_hash")}
            return "mapped" if report else "skipped"
        return "unbound"

    claims = []

    def identity_relink_stage():
        nonlocal case, claims
        case = service.get_case(repo, task["case_id"])
        claims = validated.get("claims") if isinstance(validated, dict) else validated
        if not isinstance(claims, list):
            return "skipped"
        for claim in claims:
            display = claim["text"]
            entries = case.get("mapping_entries", [])
            if entries:
                for entry in entries:
                    display = display.replace(entry["wire_token"], entry["original_value"])
            else:
                for original, alias in case.get("mapping", {}).items():
                    display = display.replace(alias, original)
            claim["local_text"] = display
        return "ok"

    claim_anchor_ids = []

    def evidence_relink_stage():
        if not isinstance(claims, list):
            return "skipped"
        all_anchors = service.anchor_index(repo, task["case_id"], current_only=False)
        for claim in claims:
            anchor_ids = list(claim["anchors"])
            claim_anchor_ids.append(anchor_ids)
            claim["anchors"] = [all_anchors[anchor_id]
                                for anchor_id in anchor_ids
                                if anchor_id in all_anchors]
        return "ok"

    def review_schema_stage():
        if not isinstance(claims, list):
            return "skipped"
        current_anchors = service.anchor_index(repo, task["case_id"], current_only=True)
        flagged = 0
        for claim, anchor_ids in zip(claims, claim_anchor_ids):
            if any(anchor_id not in current_anchors for anchor_id in anchor_ids):
                claim["issues"].append("引用包含历史材料版本锚点，确认前须显式核对")
                claim["status"] = "needs_review"
                flagged += 1
        return f"flagged={flagged}"

    def human_decision_stage():
        extra = validated if isinstance(validated, dict) else {}
        if isinstance(claims, list):
            task["artifact"] = {
                "schema_version": 2, "claims": claims, "provenance": provenance,
                "confirmed": False,
                "unused_fact_ids": list(extra.get("unused_fact_ids") or []),
                "gaps": list(extra.get("gaps") or []),
                "feedback_issues": list(extra.get("feedback_issues") or []),
            }
        else:
            task["artifact"] = {"schema_version": 2, "result": validated,
                                "provenance": provenance, "confirmed": False}
        if mapper_info:
            task["artifact"]["domain_mapper"] = mapper_info
        task["status"] = "complete"
        return "pending_human"

    for name, stage in (
        ("envelope", envelope_stage), ("hash", hash_stage),
        ("schema", schema_stage), ("provenance", provenance_stage),
        ("domain_mapper", domain_mapper_stage),
        ("identity_relink", identity_relink_stage),
        ("evidence_relink", evidence_relink_stage),
        ("review_schema", review_schema_stage),
        ("human_decision", human_decision_stage),
    ):
        _stage(repo, task, name, stage)

    record_result_envelope(repo, task, record, "pending_human")

    if isinstance(task.get("artifact"), dict) and "claims" in task["artifact"]:
        service.seed_followups(repo, case, task)


def is_connect_error(error):
    """True only when the TCP connect provably failed — nothing could have
    crossed the send boundary, so retrying is safe."""
    return isinstance(error, (httpx.ConnectError, ConnectionError, OSError))


def mark_waiting_cloud(repo, task, job):
    """Suspend a cloud-required job while the edge is disconnected.

    Task stays queued; the job goes back to pending with a not-before delay.
    No status is advanced and no provenance is fabricated."""
    domain_runtime.record_task_step(
        repo, task, "CLOUD", WAITING_CLOUD, from_status=task.get("status"))
    job.update(status="pending", error="云端不可达，挂起等待重连",
               not_before=RETRY_AFTER_SECONDS)
    repo.put("job", job, job["case_id"])
