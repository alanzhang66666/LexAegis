import asyncio
import hashlib
import io
import json
import os
import secrets
import time
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from zipfile import ZipFile, BadZipFile
import httpx
from fastapi import FastAPI, HTTPException, Request, Response, UploadFile, File, Form
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, ConfigDict, Field, field_validator
from . import __version__, service, release_service
from .auth import create_user_record, current_actor, ensure_initial_admin, public_user, verify_password
from .diagnostics import host_publish_capability, isolation_capability, legal_capability, redteam_capability
from .parsing import UPLOAD_EXTENSIONS, ocr_capability
from .transcribe import whisper_capability
from .providers import EdgeClient
from .contracts import HumanDecision, ProviderProfile, RiskProtocol
from .governance import protocol_content_hash, publish_pack_record
from .outbound_gate import product_dispatch_state
from .registry import TASKS, import_pack, run_pack_regressions, task_definitions, validate_pack
from .runtime_identity import runtime_identity, write_runtime_identity
from .storage import Store
from .runtime_profile import bind_runtime, current_profile, profile_config
from .util import app_dir, audit, digest, now, restrict_mode, sign, uid


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CaseInput(Input):
    reference_code: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    name: str = Field(min_length=1, max_length=120)
    domain: str = "labor"


class DemoInput(Input):
    scenario: Literal["success", "human_veto", "linkage", "stop"] = "success"


class LoginInput(Input):
    username: str = "admin"
    password: str


class UserCreateInput(Input):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[a-z][a-z0-9_.-]{2,31}$")
    display_name: str = Field(min_length=1, max_length=80)
    role: Literal["admin", "case_operator", "technical_reviewer", "legal_reviewer", "approver"]
    password: str = Field(min_length=12, max_length=512)

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value):
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("display_name", mode="before")
    @classmethod
    def normalize_display_name(cls, value):
        return value.strip() if isinstance(value, str) else value


class UserUpdateInput(Input):
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    role: Literal["admin", "case_operator", "technical_reviewer", "legal_reviewer", "approver"] | None = None
    status: Literal["active", "disabled"] | None = None
    password: str | None = Field(default=None, min_length=12, max_length=512)


class FactInput(Input):
    field: str
    value: str = Field(min_length=1, max_length=10000)
    source_ids: list[str] = Field(min_length=1, max_length=100)
    confirmed: bool = False
    claim_stance: Literal["claim", "deny", "hold_evidence", "unknown"] | None = None
    evidence_holder: Literal["worker", "employer", "third_party", "unknown"] | None = None
    day_nature: Literal["weekday", "rest_day", "holiday", "unknown"] | None = None
    hours: float | None = Field(default=None, ge=0, le=10000)
    wage_base: str | None = Field(default=None, max_length=200)
    evidence_attribution: str | None = Field(default=None, max_length=500)
    dispute_status: Literal["claimed", "denied", "disputed", "admitted", "unknown"] | None = None
    statement_status: Literal[
        "claimed", "denied", "admitted", "court_found", "document_recorded", "not_stated", "unknown"
    ] | None = None
    negated: bool | None = None
    subject_role: Literal["worker", "employer", "third_party", "unknown"] | None = None
    subject_category: Literal["natural_person", "legal_person", "unknown"] | None = None
    confidentiality_category: Literal[
        "unknown", "personal_information", "party_privacy", "trade_secret", "state_secret", "other_confidential"
    ] | None = None
    confidentiality_level: Literal["unknown", "ordinary", "elevated", "restricted"] | None = None
    notice_status: Literal["unknown", "not_notified", "notified", "not_applicable"] | None = None
    consent_evidence: str | None = Field(default=None, max_length=500)
    sensitivity_label: Literal[
        "必须保留", "条件保留", "必须保留或条件保留", "假名化保留", "默认删除", "禁止外发", "转人工",
        "must_keep", "conditional_keep", "keep_or_conditional", "pseudonymize_keep",
        "default_delete", "forbid_outbound", "human_review",
    ] | None = None


class Correction(Input):
    block_id: str
    text: str = Field(min_length=1, max_length=100000)


class BlockConfirmation(Input):
    block_id: str


class TaskInput(Input):
    parent_task_id: str | None = None
    transport: Literal["local", "mock", "cloud"] = "cloud"
    task_type: str = "fact_summary"
    pack_id: str | None = None
    sub_purpose: str | None = Field(default=None, max_length=80)


class FollowupTaskInput(Input):
    transport: Literal["local", "mock", "cloud"] = "cloud"
    task_type: str = "fact_summary"


class DecisionInput(Input):
    transform: Literal["keep", "pseudonymize", "generalize", "delete"]
    necessity: Literal["required", "conditional", "unnecessary", "uncertain"]
    output: str | None = Field(default=None, max_length=10000)
    candidate_id: str | None = None


class ApprovalInput(Input):
    request_hash: str
    actor: str = Field(default="local-lawyer", min_length=1, max_length=120)
    actor_role: Literal["approver"] = "approver"


class ReviewIssueInput(Input):
    request_hash: str
    idempotency_key: str = Field(min_length=8, max_length=200)
    reason: str = Field(min_length=1, max_length=4000)
    evidence_ids: list[str] = Field(min_length=1, max_length=100)


class LegalReviewInput(Input):
    evidence_ids: list[str] = Field(min_length=1, max_length=100)
    idempotency_key: str = Field(min_length=8, max_length=200)
    resolved_issue_ids: list[str] = Field(default_factory=list)
    resolution_reason: str = Field(default="", max_length=4000)
    request_hash: str
    material_version: int | None = None
    conclusion: Literal[
        "allow_processing", "allow_after_minimization",
        "needs_further_verification", "prohibit_external_processing", "reject_current_request",
    ]
    reason: str = Field(min_length=1, max_length=4000)
    reviewed_condition_ids: list[str] = Field(min_length=1)
    legal_source_ids: list[str] = Field(min_length=1)
    prohibition_findings: list[dict] = Field(default_factory=list)
    minimization_actions: list[str] = Field(default_factory=list)
    acknowledged_risk_notices: bool
    scope_note: str = Field(min_length=1, max_length=2000)
    fact_premise: str = Field(min_length=1, max_length=2000)
    authority_judgment: str = Field(min_length=1, max_length=2000)
    external_processing_note: str = Field(min_length=1, max_length=2000)
    minimization_note: str = Field(min_length=1, max_length=2000)
    final_basis: str = Field(min_length=1, max_length=2000)


class NamedConfirmation(Input):
    actor: str = Field(min_length=1, max_length=120)
    actor_role: Literal["legal_reviewer", "approver"]


class PackTransitionInput(Input):
    status: Literal["pending_review", "reviewed", "retired"]
    review_record: str | None = Field(default=None, max_length=5000)


class CloudSlotInput(Input):
    url: str = ""
    model: str = Field(default="", max_length=200)
    provider_id: str | None = None


class SettingsInput(Input):
    cloud_url: str
    cloud_model: str = Field(max_length=200)
    edge_url: str
    edge_model: str = Field(max_length=200)
    provider_id: str | None = None
    cloud_primary: CloudSlotInput | None = None
    cloud_standby: CloudSlotInput | None = None
    disclosure_budget_chars: int = Field(default=50000, ge=1, le=2000000)
    disclosure_budget_entries: int = Field(default=20, ge=1, le=1000)
    deployment_mode: Literal["native", "isolated"] = "native"
    isolation_verified: bool = False


def _slot_from(raw, url="", model="", provider_id=None):
    data = raw if isinstance(raw, dict) else (raw.model_dump() if raw is not None else {})
    chosen = data.get("provider_id")
    if chosen in (None, ""):
        chosen = provider_id
    if chosen == "":
        chosen = None
    return {"url": data.get("url") or url or "", "model": data.get("model") or model or "", "provider_id": chosen}


def public_settings(settings):
    record = dict(settings)
    primary = _slot_from(record.get("cloud_primary"), record.get("cloud_url", ""), record.get("cloud_model", ""), record.get("provider_id"))
    record["cloud_primary"] = primary
    record["cloud_standby"] = _slot_from(record.get("cloud_standby"))
    record["cloud_url"] = primary["url"]
    record["cloud_model"] = primary["model"]
    record["provider_id"] = primary["provider_id"]
    return record


def _require_cloud_url(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise service.DomainError("云端 API 需要不带凭据或查询参数的 HTTPS 地址")
    return parsed


class AttackBatchInput(Input):
    auxiliary: dict[str, list[dict]] = Field(default_factory=dict)


class ProviderReviewInput(Input):
    status: Literal["reviewed", "expired"]


LEGAL_FORM_TYPES = ("fa01_source", "fa02_authorization", "fa03_provider", "fa05_rules", "fa06_annotation")


class LegalEvidenceAssessmentInput(Input):
    status: Literal["needs_correction", "evidence_checked"]
    findings: list[str] = Field(default_factory=list, max_length=30)
    basis_references: list[str] = Field(default_factory=list, max_length=30)


def public_legal_evidence(record: dict) -> dict:
    return {key: value for key, value in record.items() if key != "path"}


def assert_docx_payload(data: bytes) -> None:
    try:
        with ZipFile(io.BytesIO(data)) as package:
            members = set(package.namelist())
            if not {"[Content_Types].xml", "word/document.xml"} <= members:
                raise HTTPException(400, "文件不是有效的 Word DOCX")
    except BadZipFile:
        raise HTTPException(400, "文件不是有效的 Word DOCX")


def create_app(data_dir=None, password=None, build_manifest=None):
    explicit_password = password is not None
    root = Path(data_dir or app_dir()).resolve()
    runtime = bind_runtime(root, "app")
    startup_profile = runtime["runtime_profile"]
    root.mkdir(parents=True, exist_ok=True)
    restrict_mode(root, 0o700)
    (root / "files").mkdir(exist_ok=True)
    legal_files = root / "legal-evidence"
    legal_files.mkdir(exist_ok=True)
    restrict_mode(legal_files, 0o700)
    store = Store(root / "app.sqlite")
    from .upgrade import prepare_upgrade
    startup_identity = runtime_identity("api", build_manifest)
    prepare_upgrade(store, startup_identity)
    service.initialize(store)
    password = password or os.getenv("LEX_LOCAL_PASSWORD", "")
    if not password:
        password_file = root / "local-password"
        if not password_file.exists():
            password_file.write_text(secrets.token_urlsafe(18), encoding="utf-8")
            restrict_mode(password_file, 0o600)
        password = password_file.read_text(encoding="utf-8").strip()
    ensure_initial_admin(store, password, os.getenv("LEX_LOCAL_ACTOR", "本地管理员"),
                         reset_password=explicit_password)
    sessions = {}
    attempts = {}
    app = FastAPI(title="LexAegis", docs_url=None, redoc_url=None)
    app.state.store = store
    app.state.root = root
    app.state.runtime_profile = startup_profile
    app.state.runtime_identity = startup_identity
    write_runtime_identity(root / "api-runtime-identity.json", app.state.runtime_identity)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver", "api"])

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if current_profile() != startup_profile:
            return JSONResponse({"detail": "运行环境已改变，拒绝继续服务"}, 503)
        actor_token = current_actor.set("system")
        if request.url.path.startswith("/api/"):
            if request.method not in ("GET", "HEAD"):
                origin = request.headers.get("origin")
                api_port = os.getenv("LEX_API_PORT", "8765")
                allowed = {f"http://127.0.0.1:{api_port}", f"http://localhost:{api_port}",
                           "http://127.0.0.1:8765", "http://localhost:8765",
                           "http://127.0.0.1:5173", "http://localhost:5173", "http://testserver"}
                if origin and origin not in allowed:
                    current_actor.reset(actor_token)
                    return JSONResponse({"detail": "不允许跨站请求"}, 403)
            if request.url.path not in ("/api/v1/login", "/api/v1/health"):
                token = request.cookies.get("lex_session")
                session = sessions.get(token)
                if not session or session["expires"] <= time.time():
                    current_actor.reset(actor_token)
                    return JSONResponse({"detail": "请登录本地工作台"}, 401)
                with store.read() as repo:
                    try:
                        user = repo.get(session["user_id"], "user")
                    except KeyError:
                        user = None
                if not user or user.get("status") != "active":
                    sessions.pop(token, None)
                    current_actor.reset(actor_token)
                    return JSONResponse({"detail": "本地账户已停用"}, 401)
                if session.get("auth_version") != user.get("auth_version", 1):
                    sessions.pop(token, None)
                    current_actor.reset(actor_token)
                    return JSONResponse({"detail": "账户凭据已变化，请重新登录"}, 401)
                session.update(actor=user["display_name"], role=user["role"], username=user["username"])
                current_actor.reset(actor_token)
                actor_token = current_actor.set(user["display_name"])
        try:
            response = await call_next(request)
        finally:
            current_actor.reset(actor_token)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'"
        return response

    @app.exception_handler(service.DomainError)
    @app.exception_handler(ValueError)
    async def invalid(request, error):
        return JSONResponse({"detail": str(error)}, 409)

    @app.exception_handler(KeyError)
    async def missing(request, error):
        return JSONResponse({"detail": "对象不存在"}, 404)

    @app.get("/api/v1/health")
    def health():
        return {
            "status": "ok",
            "version": __version__,
            "runtime_profile": startup_profile,
            "runtime_identity": app.state.runtime_identity.public(),
        }

    @app.post("/api/v1/login")
    def login(body: LoginInput, request: Request, response: Response):
        ip = request.client.host if request.client else "local"
        username = body.username.strip().lower()
        attempt_key = ip + ":" + username
        recent = [t for t in attempts.get(attempt_key, []) if t > time.time()-60]
        if len(recent) >= 10:
            raise HTTPException(429, "尝试过多，请一分钟后重试")
        attempts[attempt_key] = recent + [time.time()]
        with store.read() as repo:
            try:
                user = repo.get("user:" + username, "user")
            except KeyError:
                user = None
        if not user or user.get("status") != "active" or not verify_password(body.password, user):
            raise HTTPException(401, "本地访问口令不正确")
        token = secrets.token_urlsafe(32)
        sessions[token] = {"expires": time.time() + 8*3600, "user_id": user["id"],
                           "username": user["username"], "actor": user["display_name"], "role": user["role"],
                           "auth_version": user.get("auth_version", 1)}
        response.set_cookie("lex_session", token, httponly=True, samesite="strict", max_age=8*3600)
        attempts.pop(attempt_key, None)
        return {"ok": True, "username": username, "actor": sessions[token]["actor"], "role": sessions[token]["role"]}

    def principal(request: Request):
        return sessions.get(request.cookies.get("lex_session"), {"actor": "unknown", "role": "unknown"})

    def require_role(request: Request, *roles):
        identity = principal(request)
        if identity["role"] not in roles and identity["role"] != "admin":
            raise HTTPException(403, "当前本地角色无权执行该操作")
        return identity

    def require_exact_role(request: Request, role: str):
        identity = principal(request)
        if identity["role"] != role:
            raise HTTPException(403, f"仅 {role} 可执行此动作，管理员不能代行")
        return {**identity, "actor_role": identity["role"], "display_name": identity["actor"]}

    if startup_profile == "production":
        from .release_api import register_release_routes
        register_release_routes(app, store, root, require_role, require_exact_role, build_manifest)
        from .runtime_pack_api import register_runtime_pack_routes
        register_runtime_pack_routes(app, store, root, require_role, require_exact_role)

    @app.get("/api/v1/me")
    def me(request: Request):
        identity = principal(request)
        return {key: identity.get(key) for key in ("user_id", "username", "actor", "role")}

    @app.post("/api/v1/logout")
    def logout(request: Request, response: Response):
        sessions.pop(request.cookies.get("lex_session"), None)
        response.delete_cookie("lex_session")
        return {"ok": True}

    @app.get("/api/v1/users")
    def users(request: Request):
        require_role(request, "admin")
        with store.read() as repo:
            return [public_user(user) for user in repo.list("user")]

    @app.post("/api/v1/users")
    def user_create(body: UserCreateInput, request: Request):
        identity = require_role(request, "admin")
        with store.transaction() as repo:
            try:
                repo.get("user:" + body.username.strip().lower(), "user")
                raise service.DomainError("用户名已存在")
            except KeyError:
                pass
            user = create_user_record(body.username, body.display_name, body.role, body.password,
                                      created_by=identity["actor"])
            repo.put("user", user)
            audit(repo, "", "user.created", user_id=user["id"], role=user["role"], actor=identity["actor"])
            return public_user(user)

    @app.put("/api/v1/users/{username}")
    def user_update(username: str, body: UserUpdateInput, request: Request):
        identity = require_role(request, "admin")
        from .auth import password_hash
        with store.transaction() as repo:
            user = repo.get("user:" + username.lower(), "user")
            if body.display_name is not None:
                user["display_name"] = body.display_name.strip()
            if body.role is not None:
                user["role"] = body.role
            if body.status is not None:
                user["status"] = body.status
            if body.password is not None:
                user["password_salt"], user["password_hash"] = password_hash(body.password)
                user["auth_version"] = int(user.get("auth_version", 1)) + 1
            active_admins = [item for item in repo.list("user")
                             if item["id"] != user["id"] and item.get("status") == "active" and item.get("role") == "admin"]
            if (user.get("status") != "active" or user.get("role") != "admin") and not active_admins:
                raise service.DomainError("不能停用或降级最后一个管理员")
            user["updated_at"] = now()
            repo.put("user", user)
            audit(repo, "", "user.updated", user_id=user["id"], role=user["role"],
                  status=user["status"], actor=identity["actor"])
            return public_user(user)

    @app.get("/api/v1/bootstrap")
    def bootstrap():
        from .recording_import import public_recording_case
        with store.read() as repo:
            return {"runtime_profile": startup_profile, "runtime_config": {**profile_config(startup_profile), "external_calls_allowed": startup_profile != "demo", "mock_responses": startup_profile == "demo"},
                    "cases": [public_recording_case(case) for case in repo.list("case")], "packs": repo.list("pack"), "tasks": [t.model_dump() for t in TASKS],
                    "task_definitions": task_definitions(), "providers": repo.list("provider"), "risk_protocols": repo.list("risk_protocol"),
                    "settings": public_settings(repo.get("settings"))}

    @app.get("/api/v1/capabilities")
    def capabilities():
        with store.read() as repo:
            settings = repo.get("settings")
        if startup_profile == "demo":
            return {"runtime_profile": "demo", "edge": {"status": "simulation", "detail": "离线模拟，不发起模型请求"},
                    "cloud": {"status": "disabled", "detail": "离线演示禁止外部调用"},
                    "validation": {"status": "not_verified", "formal_dispatch": "blocked"}}
        edge = EdgeClient(settings["edge_url"], settings["edge_model"]).health()
        try:
            signature = sign({"op": "health"}, os.getenv("LEX_GATEWAY_SECRET", ""))
            result = httpx.get(os.getenv("LEX_GATEWAY_URL", "http://127.0.0.1:8766") + "/health", headers={"X-Gateway-Signature": signature}, timeout=3, trust_env=False)
            result.raise_for_status()
            cloud = result.json()
        except Exception:
            cloud = {"status": "unconfigured", "detail": "外发网关未启动或签名配置不正确"}
        cloud_base = cloud.get("detail") or "外发网关未启动或签名配置不正确"
        cloud = {
            **cloud,
            "detail": (
                f"{cloud_base} 双槽各自绑定已审核档案，未审核备用不会启用；"
                "仅确认请求未离开本地才允许切备，已收包超时记为可能披露。"
                "正式外发仍失败关闭，不代表已完成真实外发验证。"
            ),
        }
        with store.read() as repo:
            published = [pack for pack in repo.list("pack") if pack.get("schema_version") == 2 and pack.get("status") == "published"]
            protocols = repo.list("risk_protocol")
        isolation = isolation_capability(settings)
        host_publish = host_publish_capability()
        edge_detail = (
            "本机边侧已探测"
            if edge.get("status") == "available"
            else "边侧抽取尚未在本机验收"
        )
        isolation_detail = "隔离部署已记录" if isolation.get("status") == "available" else "隔离部署仍未验收"
        host_detail = "宿主机口已发布" if host_publish.get("status") == "available" else "宿主机发布仍未验收"
        return {"technical": {"status": "available", "detail": "V2 契约、确定性检测、稳定 token 和本地复原已实现"},
                "runtime": {"status": "available" if settings.get("cloud_model") else "unconfigured", "detail": "运行配置与实现状态分开报告"},
                "legal": legal_capability(published),
                "validation": {
                    "status": "unconfigured",
                    "detail": f"{edge_detail}；{isolation_detail}；{host_detail}；真实云端外发仍未验收；正式案件仍未验收；未取得证据的能力保持未验证",
                    "edge_runtime": edge.get("status"),
                    "cloud_outbound": "not_verified",
                    "formal_dispatch": product_dispatch_state(),
                    "host_publish": host_publish.get("status"),
                },
                "edge": edge, "cloud": cloud,
                "ocr": ocr_capability(),
                "whisper": whisper_capability(),
                "redteam": redteam_capability(protocols),
                "host_publish": host_publish,
                "isolation": isolation}

    @app.get("/api/v1/domains")
    def domains():
        with store.read() as repo:
            return repo.list("pack")

    @app.get("/api/v1/task-definitions")
    def definitions():
        return task_definitions()

    @app.post("/api/v1/packs/import")
    def pack_import(body: dict, request: Request):
        require_role(request, "admin")
        with store.transaction() as repo:
            return import_pack(repo, body)

    @app.post("/api/v1/packs/{pack_id}/validate")
    def pack_validate(pack_id: str):
        with store.read() as repo:
            pack = repo.get(pack_id, "pack")
        validated = validate_pack({key: value for key, value in pack.items() if key not in ("domain_id",) and not (key == "id" and str(value).startswith("pack:"))} | {"id": pack["domain_id"]})
        return {"valid": True, "pack_id": pack_id, "regressions": run_pack_regressions(validated.model_dump())}

    @app.post("/api/v1/packs/{pack_id}/publish")
    def pack_publish(pack_id: str, body: NamedConfirmation, request: Request):
        identity = require_role(request, "legal_reviewer")
        with store.transaction() as repo:
            pack = repo.get(pack_id, "pack")
            published = publish_pack_record(pack, identity["actor"])
            repo.put("pack", published)
            audit(repo, "", "pack.published", pack_id=pack_id, actor=identity["actor"], content_hash=published["content_hash"])
            return published

    @app.post("/api/v1/packs/{pack_id}/transition")
    def pack_transition(pack_id: str, body: PackTransitionInput, request: Request):
        identity = require_role(request, "legal_reviewer" if body.status == "reviewed" else "admin")
        allowed = {"draft": {"pending_review"}, "pending_review": {"draft", "reviewed"}, "reviewed": {"pending_review"}, "published": {"retired"}, "retired": set()}
        with store.transaction() as repo:
            pack = repo.get(pack_id, "pack")
            if pack.get("schema_version") != 2 or body.status not in allowed.get(pack.get("status"), set()):
                raise service.DomainError("案由包生命周期转换无效")
            if body.status == "reviewed":
                if not body.review_record or not pack.get("references"):
                    raise service.DomainError("法学复核必须填写审核记录并具有法源")
                pack.update(review_record=body.review_record, reviewer=identity["actor"], reviewed_at=now())
            pack["status"] = body.status
            repo.put("pack", pack)
            audit(repo, "", "pack.transitioned", pack_id=pack_id, status=body.status, actor=identity["actor"])
            return pack

    @app.get("/api/v1/domain-packages")
    def domain_package_list(cause_id: str | None = None, package_type: str | None = None,
                            status: str | None = None):
        with store.read() as repo:
            items = repo.list("domain_package")
        if cause_id:
            items = [i for i in items if i.get("cause_id") == cause_id]
        if package_type:
            items = [i for i in items if i.get("package_type") == package_type]
        if status:
            items = [i for i in items if i.get("status") == status]
        return items

    @app.get("/api/v1/domain-package-manifests")
    def domain_package_manifest_list():
        with store.read() as repo:
            return repo.list("domain_package_manifest")

    class DomainPackageTransitionInput(Input):
        status: Literal["validated", "signed", "published", "deprecated", "revoked"]
        reason: str | None = Field(default=None, max_length=500)

    @app.post("/api/v1/domain-packages/{package_id}/transition")
    def domain_package_transition(package_id: str, body: DomainPackageTransitionInput, request: Request):
        from . import domain_packages
        identity = require_role(request, "legal_reviewer" if body.status == "validated" else "admin")
        with store.transaction() as repo:
            record = domain_packages.transition(
                repo, domain_packages.PACKAGE_KIND, package_id, body.status,
                actor=identity["actor"])
            if body.reason and body.status == "revoked":
                record["revocation_reason"] = body.reason
                repo.put(domain_packages.PACKAGE_KIND, record)
            return record

    @app.post("/api/v1/domain-package-manifests/{manifest_id}/transition")
    def domain_manifest_transition(manifest_id: str, body: DomainPackageTransitionInput, request: Request):
        from . import domain_packages
        identity = require_role(request, "legal_reviewer" if body.status == "validated" else "admin")
        with store.transaction() as repo:
            record = domain_packages.transition(
                repo, domain_packages.MANIFEST_KIND, manifest_id, body.status,
                actor=identity["actor"])
            if body.reason and body.status == "revoked":
                record["revocation_reason"] = body.reason
                repo.put(domain_packages.MANIFEST_KIND, record)
            return record

    @app.get("/api/v1/domain-package-manifests/{manifest_id}/bundle")
    def domain_manifest_bundle(manifest_id: str, request: Request):
        """Export a manifest + its packages as a portable bundle (the cloud ->
        edge package-delivery artifact). Admin only."""
        from . import domain_packages
        require_role(request, "admin")
        with store.read() as repo:
            return domain_packages.export_bundle(repo, manifest_id)

    class PackageBundleInput(Input):
        bundle: dict

    @app.post("/api/v1/domain-packages/import-bundle")
    def domain_package_import_bundle(body: PackageBundleInput, request: Request):
        """Import an exported bundle. Fail-closed: hashes/platform_api/refs are
        verified; status survives only for verifiably signed records."""
        from . import domain_packages
        identity = require_role(request, "admin")
        with store.transaction() as repo:
            result = domain_packages.import_bundle(
                repo, body.bundle, actor=identity["actor"])
            audit(repo, "system", "domain_package.bundle_imported",
                  manifest_id=result["manifest"], packages=result["packages"],
                  downgraded=len(result["downgraded"]), actor=identity["actor"])
            return result

    # --- package distribution control plane (desired state + receipts) ------

    class EdgeNodeInput(Input):
        edge_node_id: str = Field(min_length=1, max_length=200)
        labels: dict = Field(default_factory=dict)

    @app.post("/api/v1/edge-nodes")
    def edge_node_register(body: EdgeNodeInput, request: Request):
        """Register an edge node identity. Only registered nodes can receive
        package assignments."""
        from . import package_controller
        identity = require_role(request, "admin")
        with store.transaction() as repo:
            return package_controller.register_node(
                repo, body.edge_node_id, identity["actor"], body.labels)

    @app.get("/api/v1/edge-nodes")
    def edge_node_list(request: Request):
        from . import package_controller
        require_role(request, "admin")
        with store.read() as repo:
            return package_controller.list_nodes(repo)

    class PackageAssignmentInput(Input):
        manifest_id: str = Field(min_length=1)
        edge_node_id: str = Field(min_length=1, max_length=200)

    @app.post("/api/v1/package-assignments")
    def package_assignment_create(body: PackageAssignmentInput, request: Request):
        """Desired state: this edge node should hold this manifest."""
        from . import package_controller
        identity = require_role(request, "admin")
        with store.transaction() as repo:
            return package_controller.assign(
                repo, body.manifest_id, body.edge_node_id, identity["actor"])

    @app.get("/api/v1/package-assignments")
    def package_assignment_list(edge_node_id: str | None = None, request: Request = None):
        from . import package_controller
        require_role(request, "admin")
        with store.read() as repo:
            items = repo.list(package_controller.ASSIGNMENT_KIND)
        if edge_node_id:
            items = [i for i in items if i.get("edge_node_id") == edge_node_id]
        return items

    @app.post("/api/v1/package-assignments/{assignment_id}/deliver")
    def package_assignment_deliver(assignment_id: str, request: Request):
        """Produce the signed bundle for transport and mark delivered."""
        from . import package_controller
        identity = require_role(request, "admin")
        with store.transaction() as repo:
            return package_controller.deliver(
                repo, assignment_id, identity["actor"])

    class PackageReceiptInput(Input):
        kind: Literal["verified", "activated", "revoked", "failed"]
        edge_node_id: str = Field(min_length=1, max_length=200)
        manifest_hash: str | None = Field(default=None, max_length=200)
        detail: dict = Field(default_factory=dict)

    @app.post("/api/v1/package-assignments/{assignment_id}/receipts")
    def package_receipt_create(assignment_id: str, body: PackageReceiptInput,
                               request: Request):
        """Fold an edge acknowledgement into the assignment. Fail-closed on
        wrong node, wrong hash, or out-of-order receipt."""
        from . import package_controller
        require_role(request, "admin")
        with store.transaction() as repo:
            return package_controller.record_receipt(
                repo, assignment_id, body.kind, body.edge_node_id,
                manifest_hash=body.manifest_hash, detail=body.detail)

    class PackageRevocationInput(Input):
        reason: str | None = Field(default=None, max_length=500)

    @app.post("/api/v1/package-assignments/{assignment_id}/revoke")
    def package_assignment_revoke(assignment_id: str, body: PackageRevocationInput,
                                  request: Request):
        """Flip desired state to absent; waits for the edge's revoked receipt."""
        from . import package_controller
        identity = require_role(request, "admin")
        with store.transaction() as repo:
            return package_controller.request_revocation(
                repo, assignment_id, identity["actor"], body.reason)

    @app.get("/api/v1/package-distribution/reconcile")
    def package_distribution_reconcile(edge_node_id: str | None = None,
                                       request: Request = None):
        """Desired-vs-actual report for operators and controllers."""
        from . import package_controller
        require_role(request, "admin")
        with store.read() as repo:
            return package_controller.reconcile(repo, edge_node_id)

    @app.get("/api/v1/supported-causes")
    def supported_cause_list():
        with store.read() as repo:
            return repo.list("supported_cause")

    class SupportedCauseInput(Input):
        cause_id: str = Field(min_length=1, max_length=120)
        status: Literal["supported", "validation", "integration_only",
                        "unsupported", "suspended"] = "validation"
        environments: list[str] = Field(default_factory=list)
        pack_ids: list[str] = Field(default_factory=list)
        manifest_ids: list[str] = Field(default_factory=list)
        capabilities: list[str] = Field(default_factory=list)
        jurisdiction: str | None = None
        notes: str | None = Field(default=None, max_length=500)

    @app.post("/api/v1/supported-causes")
    def supported_cause_upsert(body: SupportedCauseInput, request: Request):
        from . import support_registry
        identity = require_role(request, "admin")
        with store.transaction() as repo:
            return support_registry.upsert_support(
                repo, body.model_dump(), actor=identity["actor"])

    class SupportedCauseTransitionInput(Input):
        status: Literal["supported", "validation", "integration_only",
                        "unsupported", "suspended"]

    @app.post("/api/v1/supported-causes/{cause_id}/transition")
    def supported_cause_transition(cause_id: str, body: SupportedCauseTransitionInput, request: Request):
        from . import support_registry
        identity = require_role(request, "admin")
        with store.transaction() as repo:
            if body.status == "suspended":
                return support_registry.suspend(repo, cause_id, actor=identity["actor"])
            record = support_registry.support_for(repo, cause_id)
            if not record:
                raise service.DomainError(f"案由 {cause_id} 无支持记录")
            return support_registry.upsert_support(
                repo, {**record, "status": body.status}, actor=identity["actor"])

    @app.get("/api/v1/providers")
    def providers():
        with store.read() as repo:
            return repo.list("provider")

    @app.put("/api/v1/providers/{provider_id}")
    def provider_put(provider_id: str, body: ProviderProfile, request: Request):
        identity = require_role(request, "admin")
        if provider_id != body.id:
            raise service.DomainError("服务商标识不一致")
        with store.transaction() as repo:
            profile = body.model_dump()
            try:
                existing = repo.get(provider_id, "provider")
            except KeyError:
                existing = None
            profile["profile_version"] = int((existing or {}).get("profile_version", 0)) + 1
            profile.update(status="draft", reviewed_by=None, reviewed_at=None)
            repo.put("provider", profile)
            audit(repo, "", "provider.updated", provider_id=provider_id, status="draft",
                  version=profile["profile_version"], actor=identity["actor"])
            return profile

    @app.post("/api/v1/providers/{provider_id}/review")
    def provider_review(provider_id: str, body: ProviderReviewInput, request: Request):
        identity = require_role(request, "legal_reviewer")
        with store.transaction() as repo:
            profile = repo.get(provider_id, "provider")
            if body.status == "reviewed":
                required = [
                    profile.get("role") not in (None, "unknown"),
                    bool(profile.get("processing_regions")), bool(profile.get("retention")),
                    profile.get("training_use") != "unknown", profile.get("human_access") != "unknown",
                    profile.get("subprocessor_status") in ("none", "declared"),
                    bool(profile.get("deletion_mechanism")), bool(profile.get("contract_reference")),
                    bool(profile.get("impact_assessment_reference")), bool(profile.get("valid_until")),
                    bool(profile.get("allowed_tasks")), bool(profile.get("allowed_domains")),
                    bool(profile.get("allowed_fields")), "cloud" in profile.get("allowed_transports", []),
                ]
                if not all(required) or (profile.get("subprocessor_status") == "declared" and not profile.get("subprocessors")):
                    raise service.DomainError("服务商关键处理条件或允许范围尚未完整登记")
            profile.update(status=body.status, reviewed_by=identity["actor"], reviewed_at=now(),
                           profile_version=int(profile.get("profile_version", 1)) + 1)
            repo.put("provider", profile)
            audit(repo, "", "provider.reviewed", provider_id=provider_id, status=body.status,
                  version=profile["profile_version"], actor=identity["actor"])
            return profile

    @app.delete("/api/v1/providers/{provider_id}")
    def provider_delete(provider_id: str, request: Request):
        identity = require_role(request, "admin")
        with store.transaction() as repo:
            profile = repo.get(provider_id, "provider")
            settings = repo.get("settings")
            in_use = {
                settings.get("provider_id"),
                (settings.get("cloud_primary") or {}).get("provider_id"),
                (settings.get("cloud_standby") or {}).get("provider_id"),
            }
            if profile.get("status") == "reviewed" or provider_id in in_use:
                raise service.DomainError("经复核或正在使用的服务商档案不能删除，只能标记过期")
            repo.delete(provider_id)
            audit(repo, "", "provider.deleted", provider_id=provider_id, actor=identity["actor"])
        return {"ok": True}

    @app.get("/api/v1/risk-protocols")
    def risk_protocols():
        with store.read() as repo:
            return repo.list("risk_protocol")

    @app.put("/api/v1/risk-protocols/{protocol_id}")
    def risk_protocol_put(protocol_id: str, body: RiskProtocol, request: Request):
        require_role(request, "admin")
        if protocol_id != body.id:
            raise service.DomainError("协议标识不一致")
        protocol = body.model_dump()
        if protocol["status"] == "frozen":
            protocol["content_hash"] = protocol_content_hash(protocol)
        with store.transaction() as repo:
            try:
                existing = repo.get(protocol_id, "risk_protocol")
                if existing.get("status") == "frozen" and existing != protocol:
                    raise service.DomainError("冻结协议不可覆盖，请创建新版本")
            except KeyError:
                pass
            repo.put("risk_protocol", protocol)
            return protocol

    @app.post("/api/v1/cases")
    def create_case(body: CaseInput, request: Request):
        require_role(request, "case_operator")
        with store.transaction() as repo:
            return service.create_case(repo, body.name, body.domain, reference_code=body.reference_code)

    @app.post("/api/v1/demos")
    def demo(body: DemoInput, request: Request):
        require_role(request, "case_operator")
        from .demo import SCENARIOS
        with store.transaction() as repo:
            return service.create_case(repo, SCENARIOS[body.scenario]["name"], scenario=body.scenario)

    @app.post("/api/v1/demos/import")
    async def import_demo_document(request: Request, file: UploadFile = File(...),
                                   expected_scenario: str | None = Form(None)):
        require_role(request, "case_operator")
        if startup_profile != "demo":
            raise HTTPException(409, "此入口仅用于本地案例工作区")
        if Path(file.filename or "").suffix.lower() != ".docx":
            raise HTTPException(400, "请选择配套 Word 材料")
        data = await file.read(2 * 1024 * 1024 + 1)
        if not data or len(data) > 2 * 1024 * 1024:
            raise HTTPException(413, "文件为空或超过 2MB")
        from .demo import SCENARIOS
        from .recording_import import identify_recording, attach_recording_material, public_recording_case
        checksum = hashlib.sha256(data).hexdigest()
        scenario = identify_recording(data)
        if scenario is None:
            raise HTTPException(400, "未识别到三份案例的完整正文。请选择 LA-001、LA-002 或 LA-003 的原始案例标注或完整版 Word；支持重新保存及调整排版，但不支持改动正文。")
        recording_scenarios = {'la001_edge_block', 'la002_human_veto', 'la003_review_release'}
        if expected_scenario is not None:
            if expected_scenario not in recording_scenarios:
                raise HTTPException(400, "未识别的案例入口")
            if scenario != expected_scenario:
                expected_code = {
                    'la001_edge_block': 'LA-001',
                    'la002_human_veto': 'LA-002',
                    'la003_review_release': 'LA-003',
                }[expected_scenario]
                raise HTTPException(409, f"所选文件与当前案例不匹配，请上传 {expected_code} 对应的完整 Word 材料")
        material_path = None
        try:
            with store.transaction() as repo:
                case = service.create_case(repo, SCENARIOS[scenario]["name"], scenario=scenario)
                material_path = attach_recording_material(repo, case, data, file.filename or "案件材料.docx", root)
                audit(repo, case["id"], "demo.document_imported", sha256=checksum,
                      scenario=scenario, transport="local", filename=Path(file.filename).name[:200])
                return public_recording_case(case)
        except Exception:
            if material_path is not None:
                material_path.unlink(missing_ok=True)
            raise

    @app.get("/api/v1/cases/{case_id}")
    def case_detail(case_id: str):
        from .recording_import import case_stage_content, public_recording_case
        with store.read() as repo:
            case = service.get_case(repo, case_id)
            docs = [{k: v for k, v in d.items() if k != "path"} for d in repo.list("document", case_id)]
            docs.sort(key=lambda d: d.get("source_role") != "recording_original")
            return {"case": public_recording_case(case), "stage_content": case_stage_content(case, docs),
                    "local_review_available": startup_profile == "demo"
                    and case.get("scenario") in {"la002_human_veto", "la003_review_release"}
                    and bool(case_stage_content(case, docs)),
                    "documents": docs, "facts": repo.list("fact", case_id), "tasks": [service.task_view(repo, t) for t in repo.list("task", case_id)], "jobs": repo.list("job", case_id), "audit": repo.list("audit", case_id), "ledger": repo.list("disclosure", case_id)}

    @app.get("/api/v1/cases/{case_id}/domain-binding")
    def case_domain_binding(case_id: str):
        with store.read() as repo:
            service.get_case(repo, case_id)
            return repo.list("case_domain_binding", case_id)

    @app.get("/api/v1/cases/{case_id}/context-versions")
    def case_context_versions(case_id: str):
        with store.read() as repo:
            service.get_case(repo, case_id)
            return repo.list("case_context_version", case_id)

    @app.get("/api/v1/tasks/{task_id}/runtime-snapshot")
    def task_runtime_snapshot(task_id: str):
        with store.read() as repo:
            task = repo.get(task_id, "task")
            snapshot_id = task.get("domain_runtime_snapshot_id")
            if not snapshot_id:
                raise HTTPException(404, "task has no runtime snapshot")
            return repo.get(snapshot_id, "domain_runtime_snapshot")

    @app.get("/api/v1/cases/{case_id}/legal-evidence")
    def legal_evidence_list(case_id: str, request: Request):
        require_role(request, "legal_reviewer")
        with store.read() as repo:
            service.get_case(repo, case_id)
            return [public_legal_evidence(item) for item in repo.list("legal_evidence", case_id)]

    @app.post("/api/v1/cases/{case_id}/legal-evidence")
    async def legal_evidence_upload(case_id: str, request: Request,
                                    form_type: str = Form(...), file: UploadFile = File(...)):
        identity = require_role(request, "legal_reviewer")
        if form_type not in LEGAL_FORM_TYPES:
            raise HTTPException(400, "不支持的法学表单类型")
        if Path(file.filename or "").suffix.lower() != ".docx":
            raise HTTPException(400, "法学证据登记仅接受 DOCX")
        with store.read() as repo:
            case = service.get_case(repo, case_id)
            if case["mode"] == "demo":
                raise HTTPException(409, "演示案件不接收法学证据")
        data = await file.read(10*1024*1024+1)
        if not data or len(data) > 10*1024*1024:
            raise HTTPException(413, "文件为空或超过 10MB")
        assert_docx_payload(data)
        sha256 = hashlib.sha256(data).hexdigest()
        with store.transaction() as repo:
            service.get_case(repo, case_id)
            existing = [item for item in repo.list("legal_evidence", case_id)
                        if item["form_type"] == form_type and item["sha256"] == sha256]
            if existing:
                return public_legal_evidence(existing[0])
            ident = uid("legal-evidence")
            path = legal_files / (ident + ".docx")
            path.write_bytes(data)
            restrict_mode(path, 0o600)
            try:
                record = {
                    "id": ident, "case_id": case_id, "form_type": form_type,
                    "name": Path(file.filename).name[:200], "path": path.name,
                    "sha256": sha256, "size": len(data), "uploaded_by": identity["actor"],
                    "uploaded_at": now(), "status": "received_unverified",
                    "findings": [], "basis_references": [], "assessed_by": None, "assessed_at": None,
                    "gate_pass": False,
                }
                repo.put("legal_evidence", record, case_id)
                audit(repo, case_id, "legal_evidence.uploaded", evidence_id=ident,
                      form_type=form_type, sha256=sha256, actor=identity["actor"])
            except Exception:
                path.unlink(missing_ok=True)
                raise
        return public_legal_evidence(record)

    @app.get("/api/v1/cases/{case_id}/legal-evidence/{evidence_id}/file")
    def legal_evidence_file(case_id: str, evidence_id: str, request: Request):
        require_role(request, "legal_reviewer")
        with store.read() as repo:
            record = repo.get(evidence_id, "legal_evidence")
        if record["case_id"] != case_id:
            raise HTTPException(404)
        return FileResponse(legal_files / record["path"], filename=record["name"])

    @app.put("/api/v1/cases/{case_id}/legal-evidence/{evidence_id}/assessment")
    def legal_evidence_assess(case_id: str, evidence_id: str,
                              body: LegalEvidenceAssessmentInput, request: Request):
        identity = require_role(request, "legal_reviewer")
        findings = [item.strip() for item in body.findings if item.strip()]
        basis = [item.strip() for item in body.basis_references if item.strip()]
        if any(len(item) > 500 for item in findings + basis):
            raise HTTPException(400, "单项记录超过 500 字")
        if body.status == "needs_correction" and not findings:
            raise HTTPException(400, "待补正状态须写具体问题")
        if body.status == "evidence_checked" and (findings or not basis):
            raise HTTPException(400, "证据核齐须清空待补项并填写证据引用")
        with store.transaction() as repo:
            record = repo.get(evidence_id, "legal_evidence")
            if record["case_id"] != case_id:
                raise HTTPException(404)
            record.update(status=body.status, findings=findings, basis_references=basis,
                          assessed_by=identity["actor"], assessed_at=now(), gate_pass=False)
            repo.put("legal_evidence", record, case_id)
            audit(repo, case_id, "legal_evidence.assessed", evidence_id=evidence_id,
                  sha256=record["sha256"], status=body.status, actor=identity["actor"])
            return public_legal_evidence(record)

    @app.post("/api/v1/cases/{case_id}/documents")
    async def upload(case_id: str, request: Request, file: UploadFile = File(...)):
        require_role(request, "case_operator")
        extension = Path(file.filename or "").suffix.lower()
        if extension not in UPLOAD_EXTENSIONS:
            raise HTTPException(400, "仅支持 DOCX、PDF、PNG、JPEG、TXT、XLSX、CSV 与常见音视频")
        with store.read() as repo:
            case = service.get_case(repo, case_id)
            if case["mode"] == "demo":
                raise HTTPException(409, "演示模式不接收上传；请新建正式案件")
        data = await file.read(20*1024*1024+1)
        if not data or len(data) > 20*1024*1024:
            raise HTTPException(413, "文件为空或超过 20MB")
        ident = uid("doc")
        path = root / "files" / (ident + extension)
        path.write_bytes(data)
        restrict_mode(path, 0o600)
        try:
            with store.transaction() as repo:
                case = service.get_case(repo, case_id)
                service.assert_editable(repo, case_id)
                doc = {"id": ident, "case_id": case_id, "name": Path(file.filename).name[:200], "extension": extension, "path": path.name, "version": 1, "status": "pending", "ir": None}
                repo.put("document", doc, case_id)
                service.touch_case(repo, case, "document.uploaded")
                return service.queue_job(repo, case_id, "parse", {"document_id": ident})
        except Exception:
            path.unlink(missing_ok=True)
            raise

    @app.get("/api/v1/cases/{case_id}/documents/{document_id}/file")
    def original(case_id: str, document_id: str):
        with store.read() as repo:
            doc = repo.get(document_id, "document")
        if doc["case_id"] != case_id or not doc["path"]:
            raise HTTPException(404)
        return FileResponse(root / "files" / doc["path"], filename=doc["name"])

    @app.post("/api/v1/cases/{case_id}/documents/{document_id}/retry")
    def retry_document(case_id: str, document_id: str, request: Request):
        require_role(request, "case_operator")
        with store.transaction() as repo:
            case = service.get_case(repo, case_id)
            service.assert_editable(repo, case_id)
            doc = repo.get(document_id, "document")
            if doc.get("case_id") != case_id:
                raise HTTPException(404, "材料不存在")
            if case["mode"] == "demo" or doc.get("status") != "failed" or not doc.get("path"):
                raise service.DomainError("仅可重试已失败且保留原件的正式材料")
            if not (root / "files" / doc["path"]).is_file():
                raise service.DomainError("原件缺失，请恢复原件后重试")
            if any(j.get("kind") == "parse" and j.get("payload", {}).get("document_id") == document_id
                   and j.get("status") in {"pending", "running"} for j in repo.list("job", case_id)):
                raise service.DomainError("此材料已有解析作业")
            doc.update(status="pending", error=None)
            repo.put("document", doc, case_id)
            return service.queue_job(repo, case_id, "parse", {"document_id": document_id})

    @app.get("/api/v1/cases/{case_id}/documents/{document_id}/page/{page_number}")
    def render_page(case_id: str, document_id: str, page_number: int):
        with store.read() as repo:
            doc = repo.get(document_id, "document")
        if doc["case_id"] != case_id:
            raise HTTPException(404)
        material = root / "files" / doc["path"]
        if doc["extension"] == ".pdf":
            import pypdfium2 as pdfium
            pdf = pdfium.PdfDocument(material)
            try:
                if not 1 <= page_number <= len(pdf):
                    raise HTTPException(404)
                page = pdf[page_number-1]
                image = page.render(scale=min(1.5, 1600/max(page.get_size()))).to_pil()
                page.close()
            finally:
                pdf.close()
        elif doc["extension"] in (".png", ".jpg", ".jpeg"):
            if page_number != 1:
                raise HTTPException(404)
            from PIL import Image
            with Image.open(material) as source:
                image = source.convert("RGB")
        else:
            raise HTTPException(404)
        output = io.BytesIO()
        image.save(output, format="PNG")
        return Response(output.getvalue(), media_type="image/png")

    @app.put("/api/v1/cases/{case_id}/documents/{document_id}/correction")
    def correction(case_id: str, document_id: str, body: Correction, request: Request):
        require_role(request, "case_operator")
        with store.transaction() as repo:
            return service.correct_document(repo, case_id, document_id, body.block_id, body.text)

    @app.put("/api/v1/cases/{case_id}/documents/{document_id}/confirmation")
    def confirmation(case_id: str, document_id: str, body: BlockConfirmation, request: Request):
        require_role(request, "case_operator")
        with store.transaction() as repo:
            return service.confirm_document_block(repo, case_id, document_id, body.block_id)

    @app.get("/api/v1/cases/{case_id}/anchors")
    def anchors(case_id: str):
        with store.read() as repo:
            service.get_case(repo, case_id)
            return list(service.anchor_index(repo, case_id, current_only=False).values())

    @app.post("/api/v1/cases/{case_id}/facts")
    def add_fact(case_id: str, body: FactInput, request: Request):
        require_role(request, "case_operator")
        with store.transaction() as repo:
            return service.save_fact(repo, case_id, body.model_dump(exclude_none=True))

    @app.put("/api/v1/cases/{case_id}/facts/{fact_id}")
    def edit_fact(case_id: str, fact_id: str, body: FactInput, request: Request):
        require_role(request, "case_operator")
        with store.transaction() as repo:
            return service.save_fact(repo, case_id, body.model_dump(exclude_none=True), fact_id)

    @app.delete("/api/v1/cases/{case_id}/facts/{fact_id}")
    def delete_fact(case_id: str, fact_id: str, request: Request):
        require_role(request, "case_operator")
        with store.transaction() as repo:
            case = service.get_case(repo, case_id)
            service.assert_editable(repo, case_id)
            if case["mode"] == "demo" or repo.get(fact_id, "fact")["case_id"] != case_id:
                raise service.DomainError("不能删除该事实")
            repo.delete(fact_id)
            service.touch_case(repo, case, "fact.deleted")
        return {"ok": True}

    @app.post("/api/v1/cases/{case_id}/extract")
    def extract(case_id: str, request: Request):
        require_role(request, "case_operator")
        with store.transaction() as repo:
            case = service.get_case(repo, case_id)
            if case["mode"] == "demo":
                raise service.DomainError("固定演示无需重新提取")
            service.assert_editable(repo, case_id)
            if not repo.get("settings")["edge_model"]:
                raise service.DomainError("边侧模型未配置，请人工添加事实")
            documents = repo.list("document", case_id)
            if any(d.get("status") != "ready" or not isinstance(d.get("ir"), dict) or (d.get("ir") or {}).get("needs_review") for d in documents):
                raise service.DomainError("请先完成材料、OCR 或转写复核")
            blocks = list(service.anchor_index(repo, case_id).values())
            if not blocks or sum(len(b["text"]) for b in blocks) > 50000:
                raise service.DomainError("无可提取文本或超过首版 5 万字预算，请缩减材料")
            return service.queue_job(repo, case_id, "extract", {"revision": case["revision"], "blocks": blocks})

    @app.post("/api/v1/cases/{case_id}/tasks")
    def task(case_id: str, body: TaskInput, request: Request):
        require_role(request, "case_operator")
        with store.transaction() as repo:
            return service.create_task(repo, case_id, body.transport, body.task_type, body.pack_id, body.sub_purpose, body.parent_task_id)

    @app.post("/api/v1/cases/{case_id}/followups/{todo_id}/dismiss")
    def dismiss_followup(case_id: str, todo_id: str, request: Request):
        require_role(request, "case_operator")
        with store.transaction() as repo:
            return service.dismiss_followup(repo, case_id, todo_id)

    @app.post("/api/v1/cases/{case_id}/followups/task")
    def followup_task(case_id: str, body: FollowupTaskInput, request: Request):
        require_role(request, "case_operator")
        with store.transaction() as repo:
            return service.create_followup_task(repo, case_id, body.transport, body.task_type)

    @app.patch("/api/v1/tasks/{task_id}/decisions/{fact_id}")
    def decision(task_id: str, fact_id: str, body: DecisionInput, request: Request):
        require_role(request, "case_operator")
        with store.transaction() as repo:
            return service.update_decision(repo, task_id, fact_id, body.transform, body.necessity, body.output, body.candidate_id)

    @app.post("/api/v1/tasks/{task_id}/evaluate")
    def evaluate(task_id: str, request: Request):
        require_role(request, "case_operator")
        context = release_service.collect_context(store, root, build_manifest=build_manifest)
        # Live edge inference may take tens of seconds on CPU. Capture a versioned
        # read snapshot, release SQLite, call the model, then atomically apply only
        # if the task, case and settings are unchanged.
        with store.read() as repo:
            snapshot = service.edge_review_snapshot(repo, task_id)
        edge_review = service.edge_review_for_task(
            snapshot["case"], snapshot["settings"], snapshot["facts"],
            snapshot["transport"],
        )
        with store.transaction() as repo:
            return service.evaluate_task(
                repo, task_id, release_context=context,
                edge_review_override=edge_review, edge_snapshot=snapshot,
            )

    @app.get("/api/v1/tasks/{task_id}/attacks")
    def task_attacks(task_id: str):
        with store.read() as repo:
            repo.get(task_id, "task")
            return repo.list("attack_run", task_id)

    @app.post("/api/v1/tasks/{task_id}/attacks/run")
    def run_task_attacks(task_id: str, body: AttackBatchInput, request: Request):
        require_role(request, "case_operator")
        with store.transaction() as repo:
            return service.queue_attack_run(repo, task_id, body.auxiliary)

    @app.post("/api/v1/tasks/{task_id}/approve")
    def approve(task_id: str, body: ApprovalInput, request: Request):
        identity = require_exact_role(request, "approver")
        context = release_service.collect_context(store, root, build_manifest=build_manifest)
        with store.transaction() as repo:
            return service.approve_task(repo, task_id, body.request_hash, identity["actor"], "approver", identity["user_id"], release_context=context)

    @app.post("/api/v1/tasks/{task_id}/review-draft")
    def review_draft(task_id: str, request: Request):
        """Local worksheet draft. It is not a legal-review record and does not authorize dispatch."""
        require_exact_role(request, "legal_reviewer")
        with store.read() as repo:
            snapshot = service.review_draft_snapshot(repo, task_id)
        return service.compose_review_draft(snapshot)

    @app.post("/api/v1/tasks/{task_id}/legal-review")
    def legal_review(task_id: str, body: LegalReviewInput, request: Request):
        identity = require_exact_role(request, "legal_reviewer")
        with store.transaction() as repo:
            return service.record_legal_review(repo, task_id, body.model_dump(), identity)

    def recording_review_actor(repo, task_id, request, role):
        from .recording_import import case_stage_content
        identity = principal(request)
        if startup_profile != "demo" or identity["role"] != "admin":
            raise HTTPException(403, "此入口仅供本地案例管理员使用")
        task = repo.get(task_id, "task")
        case = repo.get(task["case_id"], "case")
        if (task.get("transport") != "mock" or case.get("mode") != "demo"
                or case.get("scenario") not in {"la002_human_veto", "la003_review_release"}
                or not case_stage_content(case, repo.list("document", case["id"]))):
            raise HTTPException(403, "仅支持已导入的本地人工复核案例")
        # Preserve the actual account identity and explicitly record the local
        # workflow role. The production endpoints retain exact-role checks.
        audit(repo, case["id"], "demo.review_role_used", task_id=task_id,
              actor=identity["actor"], user_id=identity["user_id"],
              account_role=identity["role"], workflow_role=role, transport="mock")
        return {**identity, "actor_role": role, "display_name": identity["actor"]}

    @app.post("/api/v1/demos/tasks/{task_id}/review-draft")
    def recording_review_draft(task_id: str, request: Request):
        with store.transaction() as repo:
            recording_review_actor(repo, task_id, request, "legal_reviewer")
            snapshot = service.review_draft_snapshot(repo, task_id)
        return service.compose_review_draft(snapshot)

    @app.post("/api/v1/demos/tasks/{task_id}/legal-review")
    def recording_legal_review(task_id: str, body: LegalReviewInput, request: Request):
        with store.transaction() as repo:
            identity = recording_review_actor(repo, task_id, request, "legal_reviewer")
            return service.record_legal_review(repo, task_id, body.model_dump(), identity)

    @app.post("/api/v1/demos/tasks/{task_id}/approve")
    def recording_approve(task_id: str, body: ApprovalInput, request: Request):
        context = release_service.collect_context(store, root, build_manifest=build_manifest)
        with store.transaction() as repo:
            identity = recording_review_actor(repo, task_id, request, "approver")
            return service.approve_task(repo, task_id, body.request_hash, identity["actor"],
                                        "approver", identity["user_id"], release_context=context)

    @app.post("/api/v1/tasks/{task_id}/review-issues")
    def review_issue(task_id: str, body: ReviewIssueInput, request: Request):
        identity = require_exact_role(request, "technical_reviewer")
        with store.transaction() as repo:
            return service.submit_review_issue(repo, task_id, body.model_dump(), identity)

    @app.post("/api/v1/tasks/{task_id}/send")
    def send(task_id: str, request: Request):
        require_role(request, "case_operator")
        context = release_service.collect_context(store, root, build_manifest=build_manifest)
        with store.transaction() as repo:
            return service.reserve_send(repo, task_id, release_context=context)

    @app.post("/api/v1/tasks/{task_id}/stop")
    def stop(task_id: str, request: Request):
        require_role(request, "case_operator")
        with store.transaction() as repo:
            return service.stop_task(repo, task_id)

    @app.post("/api/v1/tasks/{task_id}/reconcile")
    def reconcile(task_id: str, request: Request):
        require_role(request, "case_operator")
        with store.transaction() as repo:
            task = repo.get(task_id, "task")
            if task["status"] != "unknown":
                raise service.DomainError("仅对结果不明的请求查询网关记录")
            return service.queue_job(repo, task["case_id"], "reconcile", {"task_id": task_id})

    @app.post("/api/v1/tasks/{task_id}/claims/{claim_id}/review")
    def review_claim(task_id: str, claim_id: str, request: Request, body: NamedConfirmation | None = None):
        identity = require_role(request, "legal_reviewer", "approver")
        with store.transaction() as repo:
            task = repo.get(task_id, "task")
            service.assert_current(repo, task)
            if task["status"] != "complete" or not task["artifact"]:
                raise service.DomainError("结果尚未完成")
            claim = next((c for c in task["artifact"]["claims"] if c["id"] == claim_id), None)
            if not claim or not claim["anchors"] or "引用不存在或指向未披露事实" in claim["issues"] or "日期或金额存在未在引用事实中出现的数字" in claim["issues"]:
                raise service.DomainError("存在无效引用或无依据数字，不能确认；请重做任务")
            claim["reviewed"] = True
            claim["status"] = "confirmed"
            claim["reviewer"] = identity["actor"]
            claim["reviewed_at"] = now()
            repo.put("task", task, task["case_id"])
            audit(repo, task["case_id"], "claim.reviewed", task_id=task_id, claim_id=claim_id)
            return task

    @app.post("/api/v1/tasks/{task_id}/confirm")
    def confirm(task_id: str, request: Request):
        identity = require_role(request, "legal_reviewer", "approver")
        with store.transaction() as repo:
            task = repo.get(task_id, "task")
            service.assert_current(repo, task)
            if task["status"] != "complete" or not task["artifact"] or not all(c["reviewed"] for c in task["artifact"]["claims"]):
                raise service.DomainError("请先逐项查看原文并确认摘要陈述")
            task["artifact"]["confirmed"] = True
            task["artifact"]["confirmed_by"] = identity["actor"]
            task["artifact"]["confirmed_at"] = now()
            decision = HumanDecision(
                id=uid("hdec"), task_id=task_id, case_id=task["case_id"],
                artifact_hash=digest(task["artifact"]),
                request_hash=task.get("request_hash"),
                actor=identity["actor"], actor_role=identity["role"],
                created_at=now(),
            ).model_dump()
            repo.put("human_decision", decision, task["case_id"])
            repo.put("task", task, task["case_id"])
            audit(repo, task["case_id"], "artifact.confirmed", task_id=task_id,
                  human_decision_id=decision["id"])
            return task

    @app.get("/api/v1/tasks/{task_id}/cloud-result-envelopes")
    def cloud_result_envelopes(task_id: str):
        with store.read() as repo:
            return [item for item in repo.list("cloud_result_envelope")
                    if item["task_id"] == task_id]

    @app.get("/api/v1/tasks/{task_id}/human-decisions")
    def human_decisions(task_id: str):
        with store.read() as repo:
            return [item for item in repo.list("human_decision")
                    if item["task_id"] == task_id]

    @app.get("/api/v1/tasks/{task_id}/restoration")
    def restoration(task_id: str):
        with store.read() as repo:
            task = repo.get(task_id, "task")
        if not task.get("artifact"):
            raise HTTPException(409, "尚无可复原结果")
        return task["artifact"]

    @app.post("/api/v1/tasks/{task_id}/local-export-approval")
    def approve_local_export(task_id: str, body: NamedConfirmation, request: Request):
        from datetime import datetime, timezone, timedelta
        identity = require_role(request, "legal_reviewer", "approver")
        with store.transaction() as repo:
            task = repo.get(task_id, "task")
            service.assert_current(repo, task)
            if not task.get("artifact") or not task["artifact"].get("confirmed"):
                raise service.DomainError("本地复原结果须先逐项确认")
            record = {"id": uid("local_export"), "task_id": task_id, "task_version": task["version"],
                      "artifact_hash": digest(task["artifact"]),
                      "actor": identity["actor"], "actor_role": identity["role"], "at": now(),
                      "expires_at": (datetime.now(timezone.utc)+timedelta(minutes=15)).isoformat()}
            repo.put("local_export_approval", record, task_id)
            audit(repo, task["case_id"], "local_export.approved", task_id=task_id, actor=identity["actor"])
            return record

    @app.get("/api/v1/tasks/{task_id}/export")
    def export(task_id: str, view: Literal["cloud", "local"] = "cloud"):
        from datetime import datetime, timezone
        with store.read() as repo:
            task = repo.get(task_id, "task")
            local_approvals = repo.list("local_export_approval", task_id)
        if not task.get("artifact"):
            raise HTTPException(409, "尚无结果")
        if view == "local":
            valid = [item for item in local_approvals
                     if item.get("task_version") == task["version"]
                     and item.get("artifact_hash") == digest(task["artifact"])
                     and datetime.fromisoformat(item["expires_at"]) > datetime.now(timezone.utc)]
            if task.get("stale") or not task["artifact"].get("confirmed") or not valid:
                raise HTTPException(409, "含真实身份的本地复原包需要当前版本的限时具名二次确认")
        artifact = json.loads(json.dumps(task["artifact"]))
        if view == "cloud":
            for claim in artifact.get("claims", []):
                claim.pop("local_text", None)
                claim.pop("anchors", None)
        mode = task["request"]["mode"] if task.get("request") else "local"
        body = {"task_id": task_id, "view": view,
                "runtime_profile": startup_profile, "data_origin": task.get("data_origin"),
                "bundle_type": "cloud_view" if view == "cloud" else "local_review_bundle",
                "mode": mode, "stale": task["stale"], "artifact": artifact,
                "request_hash": task.get("request_hash"), "pack": task["pack_id"]}
        return Response(json.dumps(body, ensure_ascii=False, indent=2), media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{task_id}.json"'})

    @app.get("/api/v1/cases/{case_id}/audit-export")
    def audit_export(case_id: str):
        with store.read() as repo:
            service.get_case(repo, case_id)
            events = repo.list("audit", case_id)
        return Response(json.dumps(events, ensure_ascii=False, indent=2), media_type="application/json", headers={"Content-Disposition": 'attachment; filename="audit.json"'})

    @app.put("/api/v1/settings")
    def settings(body: SettingsInput, request: Request):
        require_role(request, "admin")
        primary = _slot_from(body.cloud_primary, body.cloud_url, body.cloud_model, body.provider_id)
        standby = _slot_from(body.cloud_standby)
        _require_cloud_url(primary["url"])
        if standby["url"]:
            _require_cloud_url(standby["url"])
        edge = urlparse(body.edge_url)
        edge_hosts = set(os.getenv("LEX_EDGE_ALLOWED_HOSTS", "127.0.0.1,localhost,edge-model").split(","))
        if edge.scheme not in ("http", "https") or edge.hostname not in edge_hosts or edge.username or edge.password or edge.query or edge.fragment:
            raise service.DomainError("边侧地址必须位于已登记的本地或可信内网主机")
        with store.transaction() as repo:
            if any(t["status"] in ("queued", "sending") for t in repo.list("task")):
                raise service.DomainError("请等待正在发送的任务结束")
            previous = repo.get("settings")
            result = {"id": "settings", "version": previous["version"]+1, "cloud_url": primary["url"],
                      "cloud_model": primary["model"], "provider_id": primary["provider_id"],
                      "cloud_primary": primary, "cloud_standby": standby,
                      "edge_url": body.edge_url, "edge_model": body.edge_model,
                      "disclosure_budget_chars": body.disclosure_budget_chars,
                      "disclosure_budget_entries": body.disclosure_budget_entries}
            for provider_id in {primary["provider_id"], standby["provider_id"]}:
                if provider_id:
                    repo.get(provider_id, "provider")
            # UI configuration cannot self-attest isolation; only preserve an existing isolated attestation.
            result["deployment_mode"] = previous.get("deployment_mode", os.getenv("LEX_DEPLOYMENT_MODE", "native"))
            result["isolation_verified"] = bool(previous.get("isolation_verified")) if result["deployment_mode"] == "isolated" else False
            repo.put("settings", result)
            for task in repo.list("task"):
                task["stale"] = True
                repo.put("task", task, task["case_id"])
            audit(repo, "", "settings.updated", version=result["version"])
            return result

    @app.post("/api/v1/jobs/{job_id}/cancel")
    def cancel(job_id: str, request: Request):
        require_role(request, "case_operator")
        with store.transaction() as repo:
            job = repo.get(job_id, "job")
            if job["status"] != "pending" or job["kind"] in ("send", "reconcile"):
                raise service.DomainError("只能取消尚未开始的本地处理任务")
            job["status"] = "cancelled"
            repo.put("job", job, job["case_id"])
            if job["kind"] == "parse":
                doc = repo.get(job["payload"]["document_id"])
                doc.update(status="failed", error="解析已取消")
                repo.put("document", doc, job["case_id"])
            return job

    @app.get("/api/v1/cases/{case_id}/events")
    async def events(case_id: str, request: Request):
        with store.read() as repo:
            service.get_case(repo, case_id)
        async def stream():
            last = request.headers.get("last-event-id", "")
            while not await request.is_disconnected():
                with store.read() as repo:
                    rows = repo.list("audit", case_id)
                    cursor = rows[-1]["id"] if rows else "empty"
                if cursor != last:
                    yield f"id: {cursor}\nevent: changed\ndata: {{}}\n\n"
                    last = cursor
                else:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(2)
        return StreamingResponse(stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})

    installed_dist = Path(__file__).resolve().parent / "frontend"
    source_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    dist = installed_dist if (installed_dist / "index.html").exists() else source_dist
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app
