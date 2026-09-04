import asyncio
import hmac
import io
import json
import os
import secrets
import time
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
import httpx
from fastapi import FastAPI, HTTPException, Request, Response, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, ConfigDict, Field
from . import service
from .parsing import ocr_available
from .providers import EdgeClient
from .contracts import ProviderProfile, RiskProtocol
from .governance import publish_pack_record
from .registry import TASKS, import_pack, task_definitions, validate_pack
from .storage import Store
from .util import app_dir, audit, now, restrict_mode, sign, uid


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CaseInput(Input):
    name: str = Field(min_length=1, max_length=120)
    domain: str = "labor"


class DemoInput(Input):
    scenario: Literal["success", "linkage", "stop"] = "success"


class FactInput(Input):
    field: str
    value: str = Field(min_length=1, max_length=10000)
    source_ids: list[str] = Field(min_length=1, max_length=100)
    confirmed: bool = False


class Correction(Input):
    block_id: str
    text: str = Field(min_length=1, max_length=100000)


class TaskInput(Input):
    transport: Literal["local", "mock", "cloud"] = "cloud"
    task_type: str = "fact_summary"
    pack_id: str | None = None


class DecisionInput(Input):
    transform: Literal["keep", "pseudonymize", "generalize", "delete"]
    necessity: Literal["required", "conditional", "unnecessary", "uncertain"]
    output: str | None = Field(default=None, max_length=10000)


class ApprovalInput(Input):
    request_hash: str
    actor: str = Field(default="local-lawyer", min_length=1, max_length=120)
    actor_role: Literal["approver"] = "approver"


class NamedConfirmation(Input):
    actor: str = Field(min_length=1, max_length=120)
    actor_role: Literal["legal_reviewer", "approver"]


class PackTransitionInput(Input):
    status: Literal["pending_review", "reviewed", "retired"]
    review_record: str | None = Field(default=None, max_length=5000)


class SettingsInput(Input):
    cloud_url: str
    cloud_model: str = Field(max_length=200)
    edge_url: str
    edge_model: str = Field(max_length=200)
    provider_id: str | None = None
    deployment_mode: Literal["native", "isolated"] = "native"
    isolation_verified: bool = False


def create_app(data_dir=None, password=None):
    root = Path(data_dir or app_dir()).resolve()
    root.mkdir(parents=True, exist_ok=True)
    restrict_mode(root, 0o700)
    (root / "files").mkdir(exist_ok=True)
    store = Store(root / "app.sqlite")
    service.initialize(store)
    password = password or os.getenv("LEX_LOCAL_PASSWORD", "")
    if not password:
        password_file = root / "local-password"
        if not password_file.exists():
            password_file.write_text(secrets.token_urlsafe(18), encoding="utf-8")
            restrict_mode(password_file, 0o600)
        password = password_file.read_text(encoding="utf-8").strip()
    sessions = {}
    attempts = {}
    app = FastAPI(title="LexAegis", docs_url=None, redoc_url=None)
    app.state.store = store
    app.state.root = root
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver", "api"])

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if request.url.path.startswith("/api/"):
            if request.method not in ("GET", "HEAD"):
                origin = request.headers.get("origin")
                allowed = {"http://127.0.0.1:8765", "http://localhost:8765", "http://127.0.0.1:5173", "http://localhost:5173", "http://testserver"}
                if origin and origin not in allowed:
                    return JSONResponse({"detail": "不允许跨站请求"}, 403)
            if request.url.path not in ("/api/v1/login", "/api/v1/health"):
                session = sessions.get(request.cookies.get("lex_session"))
                if not session or session["expires"] <= time.time():
                    return JSONResponse({"detail": "请登录本地工作台"}, 401)
        response = await call_next(request)
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
        return {"status": "ok", "version": "0.2.0"}

    @app.post("/api/v1/login")
    def login(body: dict, request: Request, response: Response):
        ip = request.client.host if request.client else "local"
        recent = [t for t in attempts.get(ip, []) if t > time.time()-60]
        if len(recent) >= 10:
            raise HTTPException(429, "尝试过多，请一分钟后重试")
        attempts[ip] = recent + [time.time()]
        if not hmac.compare_digest(str(body.get("password", "")), password):
            raise HTTPException(401, "本地访问口令不正确")
        token = secrets.token_urlsafe(32)
        sessions[token] = {"expires": time.time() + 8*3600, "actor": os.getenv("LEX_LOCAL_ACTOR", "local-lawyer"),
                           "role": os.getenv("LEX_LOCAL_ROLE", "admin")}
        response.set_cookie("lex_session", token, httponly=True, samesite="strict", max_age=8*3600)
        return {"ok": True, "actor": sessions[token]["actor"], "role": sessions[token]["role"]}

    def principal(request: Request):
        return sessions.get(request.cookies.get("lex_session"), {"actor": "unknown", "role": "unknown"})

    def require_role(request: Request, *roles):
        identity = principal(request)
        if identity["role"] not in roles and identity["role"] != "admin":
            raise HTTPException(403, "当前本地角色无权执行该操作")
        return identity

    @app.get("/api/v1/me")
    def me(request: Request):
        identity = principal(request)
        return {"actor": identity["actor"], "role": identity["role"]}

    @app.post("/api/v1/logout")
    def logout(request: Request, response: Response):
        sessions.pop(request.cookies.get("lex_session"), None)
        response.delete_cookie("lex_session")
        return {"ok": True}

    @app.get("/api/v1/bootstrap")
    def bootstrap():
        with store.read() as repo:
            return {"cases": repo.list("case"), "packs": repo.list("pack"), "tasks": [t.model_dump() for t in TASKS],
                    "task_definitions": task_definitions(), "providers": repo.list("provider"), "risk_protocols": repo.list("risk_protocol"),
                    "settings": repo.get("settings")}

    @app.get("/api/v1/capabilities")
    def capabilities():
        with store.read() as repo:
            settings = repo.get("settings")
        edge = EdgeClient(settings["edge_url"], settings["edge_model"]).health()
        try:
            signature = sign({"op": "health"}, os.getenv("LEX_GATEWAY_SECRET", ""))
            result = httpx.get(os.getenv("LEX_GATEWAY_URL", "http://127.0.0.1:8766") + "/health", headers={"X-Gateway-Signature": signature}, timeout=3, trust_env=False)
            result.raise_for_status()
            cloud = result.json()
        except Exception:
            cloud = {"status": "unconfigured", "detail": "外发网关未启动或签名配置不正确"}
        with store.read() as repo:
            published = [pack for pack in repo.list("pack") if pack.get("schema_version") == 2 and pack.get("status") == "published"]
            protocols = repo.list("risk_protocol")
        isolation_ok = bool(settings.get("isolation_verified")) and settings.get("deployment_mode") == "isolated"
        return {"technical": {"status": "available", "detail": "V2 契约、确定性检测、稳定 token 和本地复原已实现"},
                "runtime": {"status": "available" if settings.get("cloud_model") else "unconfigured", "detail": "运行配置与实现状态分开报告"},
                "legal": {"status": "available" if published else "unconfigured", "detail": f"已发布 V2 案由包 {len(published)} 个"},
                "validation": {"status": "unconfigured", "detail": "真实模型、真实云端和正式案件尚未验收"},
                "edge": edge, "cloud": cloud,
                "ocr": {"status": "available" if ocr_available() else "unconfigured", "detail": "已启用；模型资产需离线预置" if ocr_available() else "PaddleOCR 可选依赖或离线模型未配置"},
                "redteam": {"status": "available" if len([p for p in protocols if p.get('status') == 'frozen']) >= 4 else "unconfigured", "detail": "未运行、错误和不确定均不算通过"},
                "isolation": {"status": "available" if isolation_ok else "unconfigured", "detail": "已记录隔离验收" if isolation_ok else "尚无通过的隔离验收记录"}}

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
        validate_pack({key: value for key, value in pack.items() if key not in ("domain_id",) and not (key == "id" and str(value).startswith("pack:"))} | {"id": pack["domain_id"]})
        return {"valid": True, "pack_id": pack_id}

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

    @app.get("/api/v1/providers")
    def providers():
        with store.read() as repo:
            return repo.list("provider")

    @app.put("/api/v1/providers/{provider_id}")
    def provider_put(provider_id: str, body: ProviderProfile, request: Request):
        require_role(request, "admin")
        if provider_id != body.id:
            raise service.DomainError("服务商标识不一致")
        with store.transaction() as repo:
            repo.put("provider", body.model_dump())
            audit(repo, "", "provider.updated", provider_id=provider_id, status=body.status)
            return body

    @app.get("/api/v1/risk-protocols")
    def risk_protocols():
        with store.read() as repo:
            return repo.list("risk_protocol")

    @app.put("/api/v1/risk-protocols/{protocol_id}")
    def risk_protocol_put(protocol_id: str, body: RiskProtocol, request: Request):
        from .util import digest
        require_role(request, "admin")
        if protocol_id != body.id:
            raise service.DomainError("协议标识不一致")
        protocol = body.model_dump()
        if protocol["status"] == "frozen":
            protocol["content_hash"] = digest({key: value for key, value in protocol.items() if key != "content_hash"})
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
    def create_case(body: CaseInput):
        with store.transaction() as repo:
            return service.create_case(repo, body.name, body.domain)

    @app.post("/api/v1/demos")
    def demo(body: DemoInput):
        from .demo import SCENARIOS
        with store.transaction() as repo:
            return service.create_case(repo, SCENARIOS[body.scenario]["name"], scenario=body.scenario)

    @app.get("/api/v1/cases/{case_id}")
    def case_detail(case_id: str):
        with store.read() as repo:
            case = service.get_case(repo, case_id)
            docs = [{k: v for k, v in d.items() if k != "path"} for d in repo.list("document", case_id)]
            return {"case": case, "documents": docs, "facts": repo.list("fact", case_id), "tasks": repo.list("task", case_id), "jobs": repo.list("job", case_id), "audit": repo.list("audit", case_id), "ledger": repo.list("disclosure", case_id)}

    @app.post("/api/v1/cases/{case_id}/documents")
    async def upload(case_id: str, file: UploadFile = File(...)):
        extension = Path(file.filename or "").suffix.lower()
        if extension not in (".docx", ".pdf", ".png", ".jpg", ".jpeg"):
            raise HTTPException(400, "仅支持 DOCX、PDF、PNG 和 JPEG")
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

    @app.get("/api/v1/cases/{case_id}/documents/{document_id}/page/{page_number}")
    def render_page(case_id: str, document_id: str, page_number: int):
        import pypdfium2 as pdfium
        with store.read() as repo:
            doc = repo.get(document_id, "document")
        if doc["case_id"] != case_id or doc["extension"] != ".pdf":
            raise HTTPException(404)
        pdf = pdfium.PdfDocument(root / "files" / doc["path"])
        try:
            if not 1 <= page_number <= len(pdf):
                raise HTTPException(404)
            page = pdf[page_number-1]
            image = page.render(scale=min(1.5, 1600/max(page.get_size()))).to_pil()
            output = io.BytesIO()
            image.save(output, format="PNG")
            page.close()
        finally:
            pdf.close()
        return Response(output.getvalue(), media_type="image/png")

    @app.put("/api/v1/cases/{case_id}/documents/{document_id}/correction")
    def correction(case_id: str, document_id: str, body: Correction):
        with store.transaction() as repo:
            return service.correct_document(repo, case_id, document_id, body.block_id, body.text)

    @app.get("/api/v1/cases/{case_id}/anchors")
    def anchors(case_id: str):
        with store.read() as repo:
            service.get_case(repo, case_id)
            return list(service.anchor_index(repo, case_id, current_only=False).values())

    @app.post("/api/v1/cases/{case_id}/facts")
    def add_fact(case_id: str, body: FactInput):
        with store.transaction() as repo:
            return service.save_fact(repo, case_id, body.model_dump())

    @app.put("/api/v1/cases/{case_id}/facts/{fact_id}")
    def edit_fact(case_id: str, fact_id: str, body: FactInput):
        with store.transaction() as repo:
            return service.save_fact(repo, case_id, body.model_dump(), fact_id)

    @app.delete("/api/v1/cases/{case_id}/facts/{fact_id}")
    def delete_fact(case_id: str, fact_id: str):
        with store.transaction() as repo:
            case = service.get_case(repo, case_id)
            service.assert_editable(repo, case_id)
            if case["mode"] == "demo" or repo.get(fact_id, "fact")["case_id"] != case_id:
                raise service.DomainError("不能删除该事实")
            repo.delete(fact_id)
            service.touch_case(repo, case, "fact.deleted")
        return {"ok": True}

    @app.post("/api/v1/cases/{case_id}/extract")
    def extract(case_id: str):
        with store.transaction() as repo:
            case = service.get_case(repo, case_id)
            if case["mode"] == "demo":
                raise service.DomainError("固定演示无需重新提取")
            service.assert_editable(repo, case_id)
            if not repo.get("settings")["edge_model"]:
                raise service.DomainError("边侧模型未配置，请人工添加事实")
            blocks = list(service.anchor_index(repo, case_id).values())
            if not blocks or sum(len(b["text"]) for b in blocks) > 50000:
                raise service.DomainError("无可提取文本或超过首版 5 万字预算，请缩减材料")
            if any(d["status"] != "ready" or d["ir"]["needs_review"] for d in repo.list("document", case_id)):
                raise service.DomainError("请先完成材料和 OCR 复核")
            return service.queue_job(repo, case_id, "extract", {"revision": case["revision"], "blocks": blocks})

    @app.post("/api/v1/cases/{case_id}/tasks")
    def task(case_id: str, body: TaskInput):
        with store.transaction() as repo:
            return service.create_task(repo, case_id, body.transport, body.task_type, body.pack_id)

    @app.patch("/api/v1/tasks/{task_id}/decisions/{fact_id}")
    def decision(task_id: str, fact_id: str, body: DecisionInput):
        with store.transaction() as repo:
            return service.update_decision(repo, task_id, fact_id, body.transform, body.necessity, body.output)

    @app.post("/api/v1/tasks/{task_id}/evaluate")
    def evaluate(task_id: str):
        with store.transaction() as repo:
            return service.evaluate_task(repo, task_id)

    @app.post("/api/v1/tasks/{task_id}/approve")
    def approve(task_id: str, body: ApprovalInput, request: Request):
        identity = require_role(request, "approver")
        with store.transaction() as repo:
            return service.approve_task(repo, task_id, body.request_hash, identity["actor"], "approver")

    @app.post("/api/v1/tasks/{task_id}/send")
    def send(task_id: str):
        with store.transaction() as repo:
            return service.reserve_send(repo, task_id)

    @app.post("/api/v1/tasks/{task_id}/stop")
    def stop(task_id: str):
        with store.transaction() as repo:
            task = repo.get(task_id, "task")
            if task["status"] in ("queued", "sending", "unknown", "complete"):
                raise service.DomainError("不能撤回已进入发送阶段的请求")
            task.update(status="stopped", approval=None)
            repo.put("task", task, task["case_id"])
            audit(repo, task["case_id"], "task.stopped", task_id=task_id)
            return task

    @app.post("/api/v1/tasks/{task_id}/reconcile")
    def reconcile(task_id: str):
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
    def confirm(task_id: str):
        with store.transaction() as repo:
            task = repo.get(task_id, "task")
            service.assert_current(repo, task)
            if task["status"] != "complete" or not task["artifact"] or not all(c["reviewed"] for c in task["artifact"]["claims"]):
                raise service.DomainError("请先逐项查看原文并确认摘要陈述")
            task["artifact"]["confirmed"] = True
            repo.put("task", task, task["case_id"])
            audit(repo, task["case_id"], "artifact.confirmed", task_id=task_id)
            return task

    @app.get("/api/v1/tasks/{task_id}/restoration")
    def restoration(task_id: str):
        with store.read() as repo:
            task = repo.get(task_id, "task")
        if not task.get("artifact"):
            raise HTTPException(409, "尚无可复原结果")
        return task["artifact"]

    @app.post("/api/v1/tasks/{task_id}/local-export-approval")
    def approve_local_export(task_id: str, body: NamedConfirmation, request: Request):
        identity = require_role(request, "legal_reviewer", "approver")
        with store.transaction() as repo:
            task = repo.get(task_id, "task")
            if not task.get("artifact") or not task["artifact"].get("confirmed"):
                raise service.DomainError("本地复原结果须先逐项确认")
            record = {"id": uid("local_export"), "task_id": task_id, "actor": identity["actor"], "actor_role": identity["role"], "at": now()}
            repo.put("local_export_approval", record, task_id)
            audit(repo, task["case_id"], "local_export.approved", task_id=task_id, actor=identity["actor"])
            return record

    @app.get("/api/v1/tasks/{task_id}/export")
    def export(task_id: str, view: Literal["cloud", "local"] = "cloud"):
        with store.read() as repo:
            task = repo.get(task_id, "task")
            local_approvals = repo.list("local_export_approval", task_id)
        if not task.get("artifact"):
            raise HTTPException(409, "尚无结果")
        if view == "local" and not local_approvals:
            raise HTTPException(409, "含真实身份的本地复原包需要具名二次确认")
        artifact = json.loads(json.dumps(task["artifact"]))
        if view == "cloud":
            for claim in artifact.get("claims", []):
                claim.pop("local_text", None)
                claim.pop("anchors", None)
        mode = task["request"]["mode"] if task.get("request") else "local"
        body = {"task_id": task_id, "view": view, "mode": mode, "stale": task["stale"], "artifact": artifact,
                "request_hash": task.get("request_hash"), "pack": task["pack_id"]}
        return Response(json.dumps(body, ensure_ascii=False, indent=2), media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{task_id}.json"'})

    @app.get("/api/v1/cases/{case_id}/audit-export")
    def audit_export(case_id: str):
        with store.read() as repo:
            service.get_case(repo, case_id)
            events = repo.list("audit", case_id)
        return Response(json.dumps(events, ensure_ascii=False, indent=2), media_type="application/json", headers={"Content-Disposition": 'attachment; filename="audit.json"'})

    @app.put("/api/v1/settings")
    def settings(body: SettingsInput):
        cloud, edge = urlparse(body.cloud_url), urlparse(body.edge_url)
        edge_hosts = set(os.getenv("LEX_EDGE_ALLOWED_HOSTS", "127.0.0.1,localhost,edge-model").split(","))
        if cloud.scheme != "https" or not cloud.hostname or cloud.username or cloud.password or cloud.query or cloud.fragment:
            raise service.DomainError("云端 API 需要不带凭据或查询参数的 HTTPS 地址")
        if edge.scheme not in ("http", "https") or edge.hostname not in edge_hosts or edge.username or edge.password or edge.query or edge.fragment:
            raise service.DomainError("边侧地址必须位于已登记的本地或可信内网主机")
        with store.transaction() as repo:
            if any(t["status"] in ("queued", "sending") for t in repo.list("task")):
                raise service.DomainError("请等待正在发送的任务结束")
            previous = repo.get("settings")
            result = {"id": "settings", "version": previous["version"]+1, **body.model_dump()}
            if result.get("provider_id"):
                repo.get(result["provider_id"], "provider")
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
    def cancel(job_id: str):
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
