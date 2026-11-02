"""Authenticated production-only intake; supplied evidence never auto-passes."""
from pathlib import Path
from fastapi import File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from .contracts import FormalReleasePolicy, GateReceiptInput, IsolationReceipt
from .release_build import readiness_for_context
from .evidence import EvidenceStore, EvidenceIntakeService, EvidenceStoreError
from . import formal_release, release_service, service
from .util import audit, digest, now, uid


class IsolationConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    receipt_id: str = Field(min_length=1)


class ReceiptRevocation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=1000)


class TaskPolicyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_hash: str = Field(min_length=64, max_length=71)
    scope_kind: str = Field(default="request", pattern="^(request|first_acceptance)$")


def _current_request_scope(repo, request_hash, context):
    matches = [item for item in repo.list("task")
               if item.get("request_hash") == request_hash and item.get("request")]
    if len(matches) != 1:
        raise ValueError("请求哈希未绑定唯一当前任务")
    task = matches[0]
    case = service.assert_current(repo, task)
    if digest(task["request"]) != request_hash:
        raise ValueError("当前请求哈希与正文不一致")
    manifest = context.get("build_manifest")
    frozen = formal_release.freeze_request(
        repo, task=task, case=case, build_manifest=manifest,
        runtime_identities=context.get("runtime_identities", []),
    )
    if frozen.request_hash != request_hash:
        raise ValueError("冻结请求哈希已变化")
    policies = [FormalReleasePolicy.model_validate(item)
                for item in repo.list("formal_release_policy")]
    request_policies = [item for item in policies
                        if item.scope_kind == "request" and item.bound_request_hash == request_hash]
    if len(request_policies) > 1:
        raise ValueError("请求范围策略重复")
    if request_policies:
        policy = request_policies[0]
        derived = formal_release._tuple_for_request(case, task, task["request"], include_pilot=False)
        if (policy.tuple != derived or policy.build_manifest_hash != frozen.build_manifest_hash
                or policy.allowed_target != frozen.target or policy.allowed_model != frozen.model
                or policy.allowed_provider_profile_hash != frozen.provider_profile_hash):
            raise ValueError("请求策略与当前冻结请求不一致")
        scope = policy.tuple
    else:
        first_policies = [item for item in policies
                          if item.scope_kind == "first_acceptance" and item.tuple == frozen.tuple]
        if len(first_policies) > 1:
            raise ValueError("首案范围策略重复")
        if first_policies:
            policy = first_policies[0]
            if (policy.build_manifest_hash != frozen.build_manifest_hash
                    or policy.allowed_target != frozen.target or policy.allowed_model != frozen.model
                    or policy.allowed_provider_profile_hash != frozen.provider_profile_hash):
                raise ValueError("首案策略与当前冻结请求不一致")
            scope = policy.tuple
        else:
            activations = [row for row in repo.list("runtime_pack_activation")
                           if row.get("pack_id") == task.get("pack_id")]
            if len(activations) > 1:
                raise ValueError("规则运行库激活来源不唯一")
            request_scoped = False
            if activations:
                try:
                    runtime_pack = repo.get(activations[0].get("runtime_pack_id", ""), "runtime_pack")
                except KeyError as exc:
                    raise ValueError("规则运行库激活来源缺失") from exc
                request_scoped = runtime_pack.get("scope_kind") == "request"
            if request_scoped:
                if (not manifest or len(activations) != 1
                        or activations[0].get("artifact_sha256") != manifest.runtime_pack_hash):
                    raise ValueError("请求级规则运行库与当前已验证构建不匹配")
                scope = formal_release._tuple_for_request(case, task, task["request"], include_pilot=False)
            else:
                scope = frozen.tuple
    return task, case, frozen, manifest, scope


class IntakeContextOutput(BaseModel):
    task_id: str
    request_hash: str
    tuple: dict[str, str]
    bound_versions: dict[str, str]
    build_manifest_hash: str
    actor: dict[str, str]
    facts: list[dict]
    gates: list[dict]
    g2_authorization_statement: str
    isolation: dict[str, str]
    readiness: dict


_INTAKE_GATES = [
    {"gate_id": "G1", "required_template_kinds": ["法01"], "templates": [
        {"template_kind": "法01", "required_role": "legal_reviewer", "required_for_gate": True}]},
    {"gate_id": "G2", "required_template_kinds": ["法02"], "templates": [
        {"template_kind": "法02", "required_role": "legal_reviewer", "required_for_gate": True}]},
    {"gate_id": "G3", "required_template_kinds": ["法03", "法04"], "templates": [
        {"template_kind": "法03", "required_role": "legal_reviewer", "required_for_gate": True},
        {"template_kind": "法04", "required_role": "legal_reviewer", "required_for_gate": True},
        {"template_kind": "技01", "required_role": "technical_reviewer", "required_for_gate": False,
         "purpose": "辅助工程记录，不替代法03或法04"}]},
    {"gate_id": "G5", "required_template_kinds": ["法05"], "templates": [
        {"template_kind": "法05", "required_role": "legal_reviewer", "required_for_gate": True},
        {"template_kind": "技02", "required_role": "technical_reviewer", "required_for_gate": False}]},
    {"gate_id": "G6", "required_template_kinds": ["技03"], "templates": [
        {"template_kind": "技03", "required_role": "technical_reviewer", "required_for_gate": True}]},
    {"gate_id": "G7", "required_template_kinds": ["法08"], "templates": [
        {"template_kind": "法08", "required_role": "legal_reviewer", "required_for_gate": True,
         "technical_template": "技04"}]},
    {"gate_id": "G8", "required_template_kinds": ["法09"], "templates": [
        {"template_kind": "法09", "required_role": "legal_reviewer", "required_for_gate": True,
         "technical_template": "技05"}]},
    {"gate_id": "G9", "required_template_kinds": ["法10"], "templates": [
        {"template_kind": "法10", "required_role": "legal_reviewer", "required_for_gate": True,
         "technical_template": "技06"}]},
    {"gate_id": "G10", "required_template_kinds": ["技08"], "templates": [
        {"template_kind": "技08", "required_role": "approver", "required_for_gate": True}]},
]


def register_release_routes(app, store, root, require_role, require_exact_role, build_manifest=None):
    evidence = EvidenceStore(store, Path(root) / "release-evidence")
    intake = EvidenceIntakeService(evidence)

    @app.exception_handler(EvidenceStoreError)
    async def invalid_evidence(request, error):
        return JSONResponse({"detail": str(error)}, status_code=409)

    @app.get("/api/v1/formal-release")
    def release_status(request: Request):
        require_role(request, "technical_reviewer", "legal_reviewer", "approver")
        context = release_service.collect_context(store, root, build_manifest=build_manifest)
        with store.read() as repo:
            return {"policies": repo.list("formal_release_policy"),
                    "receipts": repo.list("gate_evidence_receipt"),
                    "isolation_receipts": repo.list("isolation_receipt"),
                    "artifacts": repo.list("evidence_artifact"),
                    "grants": repo.list("one_time_dispatch_grant"),
                    "readiness": readiness_for_context(context).model_dump(mode="json")}

    @app.get("/api/v1/tasks/{task_id}/formal-release/intake-context", response_model=IntakeContextOutput)
    def task_intake_context(task_id: str, request: Request):
        actor = require_role(request, "technical_reviewer", "legal_reviewer", "approver", "admin",
                             "case_operator")
        context = release_service.collect_context(store, root, build_manifest=build_manifest)
        with store.read() as repo:
            try:
                task, case, frozen, _manifest, release_tuple = _current_request_scope(
                    repo, repo.get(task_id, "task").get("request_hash"), context)
                if task.get("id") != task_id:
                    raise ValueError("请求哈希绑定的任务与路径任务不一致")
                task_facts = {str(item.get("id")): item for item in task.get("fact_snapshot") or []
                              if isinstance(item, dict) and item.get("id")}
                wire_facts = (task["request"].get("wire_payload") or {}).get("facts") or []
                facts = []
                for item in wire_facts:
                    if not isinstance(item, dict) or not item.get("id"):
                        continue
                    source = task_facts.get(str(item["id"]), {})
                    facts.append({"id": str(item["id"]), "field": item.get("field") or source.get("field"),
                                  "text": item.get("text", ""),
                                  "source_ids": list(source.get("source_ids") or [])})
                if not facts:
                    raise ValueError("当前请求没有可用于法01采纳的披露事实")
                bound_versions = {
                    "materials": digest(frozen.material_versions),
                    "rules": digest(frozen.rule_versions),
                    "task": str(frozen.task_version),
                    "mapping": str(frozen.mapping_version),
                    "ledger": str(frozen.ledger_version),
                    "combination": frozen.combination_input_hash,
                }
                from .evidence import _g2_authorization_statement
                return IntakeContextOutput(
                    task_id=task_id, request_hash=frozen.request_hash, tuple=release_tuple,
                    bound_versions=bound_versions, build_manifest_hash=frozen.build_manifest_hash,
                    actor={key: str(actor.get(key) or "") for key in ("user_id", "username", "actor", "role")},
                    facts=facts, gates=_INTAKE_GATES,
                    g2_authorization_statement=_g2_authorization_statement(release_tuple),
                    isolation={"attester_role": "technical_reviewer", "legal_confirmation_role": "legal_reviewer",
                               "confirmation_gate_id": "G8"},
                    readiness=readiness_for_context(
                        context, request_hash=frozen.request_hash
                    ).model_dump(mode="json"),
                )
            except KeyError as exc:
                raise HTTPException(404, "任务或案件不存在") from exc
            except (ValueError, TypeError, KeyError) as exc:
                raise HTTPException(409, f"当前请求无法生成正式证据登记上下文：{exc}") from exc

    @app.post("/api/v1/formal-release/policy")
    def install_policy(body: FormalReleasePolicy, request: Request):
        actor = require_exact_role(request, "admin")
        with store.transaction() as repo:
            result = formal_release.install_policy(repo, body, actor=actor["user_id"], actor_role="admin")
            return result.model_dump(mode="json")

    @app.post("/api/v1/tasks/{task_id}/formal-release/policy")
    def install_task_policy(task_id: str, body: TaskPolicyInput, request: Request):
        actor = require_exact_role(request, "admin")
        context = release_service.collect_context(store, root, build_manifest=build_manifest)
        with store.transaction() as repo:
            task = repo.get(task_id, "task")
            case = service.assert_current(repo, task)
            if task.get("request_hash") != body.request_hash or not task.get("request"):
                raise HTTPException(409, "请求已变化；请刷新后重新生成策略")
            try:
                frozen = formal_release.freeze_request(
                    repo, task=task, case=case,
                    build_manifest=context.get("build_manifest"),
                    runtime_identities=context.get("runtime_identities", []),
                )
            except (ValueError, TypeError, KeyError) as exc:
                raise HTTPException(409, f"当前请求无法生成正式策略：{exc}") from exc
            if body.scope_kind == "first_acceptance":
                if frozen.tuple != formal_release.FIRST_RELEASE_TUPLE:
                    raise HTTPException(409, "首个验收策略仅适用于 LA-001 × R × D 范围")
                bound_hash = None
            else:
                bound_hash = frozen.request_hash
                activations = [row for row in repo.list("runtime_pack_activation")
                               if row.get("pack_id") == task.get("pack_id")]
                manifest = context.get("build_manifest")
                if (len(activations) != 1 or manifest is None
                        or activations[0].get("artifact_sha256") != manifest.runtime_pack_hash):
                    raise HTTPException(409, "请求策略需要与已验证构建完全匹配的已激活规则运行库")
                frozen = frozen.model_copy(update={
                    "tuple": formal_release._tuple_for_request(case, task, task["request"], include_pilot=False)
                })
            candidate = FormalReleasePolicy(
                id=uid("release_policy"), scope_kind=body.scope_kind,
                bound_request_hash=bound_hash, tuple=frozen.tuple,
                build_manifest_hash=frozen.build_manifest_hash,
                allowed_target=frozen.target, allowed_model=frozen.model,
                allowed_provider_profile_hash=frozen.provider_profile_hash,
                maximum_dispatches=1, consumed_dispatches=0, status="blocked",
            )
            result = formal_release.install_policy(repo, candidate, actor=actor["user_id"], actor_role="admin")
            return result.model_dump(mode="json")

    @app.post("/api/v1/formal-release/evidence")
    async def register_evidence(request: Request, template_kind: str,
                                file: UploadFile = File(...)):
        actor = require_role(request, "technical_reviewer", "legal_reviewer", "approver")
        content = await file.read(20 * 1024 * 1024 + 1)
        if not content or len(content) > 20 * 1024 * 1024:
            raise HTTPException(413, "证据为空或超过 20MB")
        engineering = template_kind in {
            "readiness_compose_isolation", "readiness_k8s_conformance",
            "readiness_host_firewall", "readiness_supply_chain",
        }
        metadata = {}
        if engineering:
            try:
                import json
                import re
                lowered = content.decode("utf-8").lower()
                if re.search(r"password\s*[:=]|token\s*[:=]|request[_ -]?body\s*[:=]|/(?:users|home|private|tmp|var)/", lowered):
                    raise HTTPException(409, "readiness 工程证据未通过脱敏检查")
                candidate = json.loads(content.decode("utf-8"))
                if isinstance(candidate, dict):
                    metadata = {
                        "source_command": candidate.get("source_command", "") if isinstance(candidate.get("source_command", ""), str) else "",
                        "valid_until": candidate.get("valid_until") if isinstance(candidate.get("valid_until"), str) else None,
                    }
            except (UnicodeDecodeError, ValueError):
                raise HTTPException(409, "readiness 工程证据必须是可解析的脱敏 JSON")
        return evidence.register_artifact(content=content, media_type=file.content_type or "application/octet-stream",
                                          source_path_hint=Path(file.filename or "evidence").name,
                                          template_kind=template_kind, actor=actor["user_id"],
                                          source_kind="command_generated" if engineering else "manual_upload",
                                          source_command=metadata.get("source_command", ""),
                                          valid_until=metadata.get("valid_until"),
                                          redaction_profile="synthetic-v1" if engineering else "manual").model_dump(mode="json")

    @app.post("/api/v1/formal-release/receipts")
    def register_receipt(body: GateReceiptInput, request: Request):
        # Existing evidence templates define their own signing roles. This
        # route binds that signature to the authenticated account, not a name
        # supplied by an administrator or the browser.
        actor = require_exact_role(request, body.confirmed_role or "legal_reviewer")
        if actor["role"] not in {"legal_reviewer", "approver", "case_operator", "technical_reviewer"}:
            raise HTTPException(403, "此角色不能签署门禁证据")
        if body.confirmed_by != actor["actor"]:
            raise HTTPException(409, "证据签署人必须与当前具名账户一致")
        result = intake.record_gate_receipt(body, actor=actor["user_id"])
        return result.model_dump(mode="json")

    @app.post("/api/v1/formal-release/isolation")
    def register_isolation(body: IsolationReceipt, request: Request):
        actor = require_exact_role(request, "technical_reviewer")
        if body.status != "pending_legal_confirmation" or body.legal_confirmation_receipt_id:
            raise HTTPException(409, "技术人员只能登记待法学确认的隔离证据")
        context = release_service.collect_context(store, root, build_manifest=build_manifest)
        value = body.model_dump(mode="json")
        with store.transaction() as repo:
            if any(row["id"] == body.id for row in repo.list("isolation_receipt")):
                raise HTTPException(409, "隔离证据不可覆盖；请登记新版本")
            try:
                _task, case, frozen, manifest, scope = _current_request_scope(
                    repo, body.request_hash, context)
            except (ValueError, TypeError, KeyError) as exc:
                raise HTTPException(409, f"隔离证据无法绑定当前请求：{exc}") from exc
            if (body.tuple != scope or body.request_hash != frozen.request_hash
                    or body.build_manifest_hash != frozen.build_manifest_hash
                    or body.image_digests != manifest.container_image_digests):
                raise HTTPException(409, "隔离证据范围、请求哈希、构建或镜像与当前任务不一致")
            resolved = {}
            for field in ("deployment_identity_hash", "compose_hash", "probe_output_hash",
                          "host_firewall_evidence_hash", "supply_chain_evidence_hash"):
                raw = (value.get(field) or "").removeprefix("sha256:")
                artifact = evidence.verified_artifact_by_hash(raw)
                if artifact is None:
                    raise HTTPException(409, f"{field} 未在证据库中登记为可核验内容")
                resolved[field] = artifact.id
            value["tuple"] = scope
            value["attested_by"] = actor["user_id"]
            value["evidence_artifact_ids"] = resolved
            repo.put("isolation_receipt", value)
            audit(repo, case["id"], "isolation.submitted", receipt_id=body.id,
                  actor_user_id=actor["user_id"], actor_role=actor["role"])
        return value

    @app.post("/api/v1/formal-release/receipts/{receipt_id}/revoke")
    def revoke_receipt(receipt_id: str, body: ReceiptRevocation, request: Request):
        actor = require_role(request, "legal_reviewer", "approver")
        return intake.revoke_evidence(receipt_id, body.reason, actor=actor["user_id"],
                                      actor_role=actor["role"]).model_dump(mode="json")

    @app.post("/api/v1/formal-release/isolation/{receipt_id}/confirm")
    def confirm_isolation(receipt_id: str, body: IsolationConfirmation, request: Request):
        actor = require_exact_role(request, "legal_reviewer")
        context = release_service.collect_context(store, root, build_manifest=build_manifest)
        with store.transaction() as repo:
            value = repo.get(receipt_id, "isolation_receipt")
            if value["status"] != "pending_legal_confirmation":
                raise HTTPException(409, "隔离收据不在待确认状态")
            try:
                _task, case, frozen, _manifest_value, scope = _current_request_scope(
                    repo, value.get("request_hash", ""), context)
            except (ValueError, TypeError, KeyError) as exc:
                raise HTTPException(409, f"隔离确认无法绑定当前请求：{exc}") from exc
            if (value.get("tuple") != scope or value.get("request_hash") != frozen.request_hash
                    or value.get("build_manifest_hash") != frozen.build_manifest_hash):
                raise HTTPException(409, "隔离收据与当前任务范围或构建不一致")
            legal = repo.get(body.receipt_id, "gate_evidence_receipt")
            if (legal.get("gate_id") != "G8" or legal.get("request_hash") != value["request_hash"]
                    or legal.get("tuple") != scope
                    or legal.get("confirmed_role") != "legal_reviewer" or legal.get("confirmed_by") != actor["actor"]
                    or legal.get("conclusion") != "pass" or legal.get("revoked_at")):
                raise HTTPException(409, "须引用当前具名法学人员签署的同请求有效 G8 收据")
            value.update(status="valid", legal_confirmation_receipt_id=body.receipt_id)
            if not formal_release._isolation_legal_confirmation(
                    repo, value, value["request_hash"], None, scope):
                raise HTTPException(409, "G8 确认收据已失效或证据绑定不完整")
            for artifact_id in legal.get("evidence_artifact_ids", []):
                evidence.read_artifact(artifact_id)
            for artifact_id in value.get("evidence_artifact_ids", {}).values():
                try:
                    evidence.read_artifact(artifact_id)
                except (EvidenceStoreError, KeyError) as exc:
                    raise HTTPException(409, "隔离收据引用的证据内容已失效") from exc
            repo.put("isolation_receipt", value)
            audit(repo, case["id"], "isolation.confirmed", receipt_id=receipt_id,
                  actor_user_id=actor["user_id"], actor_role=actor["role"], at=now())
            return value

    @app.post("/api/v1/tasks/{task_id}/formal-release/check")
    def check_release(task_id: str, request: Request):
        require_role(request, "technical_reviewer", "legal_reviewer", "approver")
        context = release_service.collect_context(store, root, build_manifest=build_manifest)
        with store.transaction() as repo:
            task = repo.get(task_id, "task")
            case = service.assert_current(repo, task)
            task["product_release"] = release_service.status(repo, task, case, context)
            task["product_release"]["readiness"] = readiness_for_context(
                context, request_hash=task.get("request_hash", "")
            ).model_dump(mode="json")
            repo.put("task", task, case["id"])
            return task["product_release"]
