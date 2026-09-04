import os
import time
from pathlib import Path
import httpx
from . import service
from .contracts import AttackRun
from .governance import protocol_content_hash
from .parsing import parse
from .policy import check_claims
from .providers import EdgeClient
from .storage import Store
from .util import app_dir, audit, digest, exclusive_lock, now, sign, uid


def finish_response(repo, task, record):
    status = record["status"]
    disclosure = repo.get(task["request"]["request_id"], "disclosure")
    if status == "complete":
        try:
            claims = check_claims(record["result"], task, task["fact_snapshot"])
            case = service.get_case(repo, task["case_id"])
            all_anchors = service.anchor_index(repo, task["case_id"], current_only=False)
            current_anchors = service.anchor_index(repo, task["case_id"], current_only=True)
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
                anchor_ids = claim["anchors"]
                claim["anchors"] = [all_anchors[anchor_id] for anchor_id in anchor_ids if anchor_id in all_anchors]
                if any(anchor_id not in current_anchors for anchor_id in anchor_ids):
                    claim["issues"].append("引用包含历史材料版本锚点，确认前须显式核对")
                    claim["status"] = "needs_review"
            task["artifact"] = {"schema_version": 2, "claims": claims, "provenance": "simulation" if task["transport"] == "mock" else "cloud", "confirmed": False}
            task["status"] = "complete"
        except ValueError as error:
            task.update(status="failed", error=str(error))
        disclosure["status"] = "sent"
    elif status in ("unknown", "sending"):
        task.update(status="unknown", error="发送结果不明。仅可查询网关记录，不会重新提交。")
        disclosure["status"] = "unknown"
    else:
        task.update(status="failed", error="网关未接受该请求")
        disclosure["status"] = "rejected"
    repo.put("disclosure", disclosure, task["case_id"])
    repo.put("task", task, task["case_id"])
    audit(repo, task["case_id"], "send."+task["status"], task_id=task["id"])


def recover(store):
    with store.transaction() as repo:
        for job in repo.list("job"):
            if job["status"] != "running":
                continue
            if job["kind"] in ("send", "reconcile"):
                task = repo.get(job["payload"]["task_id"], "task")
                finish_response(repo, task, {"status": "unknown"})
                job.update(status="failed", error="工作进程中断；查询网关记录，不自动重发")
            elif job["kind"] == "redteam":
                task = repo.get(job["payload"]["task_id"], "task")
                for protocol_id in job["payload"].get("protocol_ids", []):
                    try:
                        protocol = repo.get(protocol_id, "risk_protocol")
                    except KeyError:
                        continue
                    run = AttackRun(
                        id=uid("attack"), protocol_id=protocol_id,
                        protocol_hash=protocol.get("content_hash") or protocol_content_hash(protocol),
                        task_id=task["id"], task_version=job["payload"]["task_version"],
                        attack_input_hash=job["payload"]["attack_input_hash"], outcome="error",
                        evidence=["工作进程在红队运行期间中断"], started_at=job.get("started_at", now()),
                        finished_at=now(),
                    ).model_dump()
                    run["result_hash"] = digest({key: value for key, value in run.items() if key != "result_hash"})
                    repo.put("attack_run", run, task["id"])
                task["redteam_status"] = "error"
                repo.put("task", task, task["case_id"])
                job.update(status="failed", error="红队作业在重启前中断；所有未完成协议记为 error")
            else:
                job.update(status="failed", error="本地任务在重启前中断；请重新发起")
                if job["kind"] == "parse":
                    doc = repo.get(job["payload"]["document_id"], "document")
                    doc.update(status="failed", error=job["error"])
                    repo.put("document", doc, job["case_id"])
            repo.put("job", job, job["case_id"])
            audit(repo, job["case_id"], "job.interrupted", job_id=job["id"])


def process_one(store, root, gateway_client=None, redteam_client=None):
    with store.transaction() as repo:
        pending = [j for j in repo.list("job") if j["status"] == "pending"]
        if not pending:
            return False
        job = pending[0]
        job.update(status="running", started_at=now())
        repo.put("job", job, job["case_id"])
        audit(repo, job["case_id"], "job.started", job_id=job["id"], kind=job["kind"])
    try:
        if job["kind"] == "parse":
            with store.read() as repo:
                doc = repo.get(job["payload"]["document_id"], "document")
            result = parse(Path(root)/"files"/doc["path"], doc["id"], doc["version"])
            with store.transaction() as repo:
                doc.update(ir=result, status="ready")
                repo.put("document", doc, job["case_id"])
                repo.put("document_version", {"id": f"{doc['id']}:v{doc['version']}", "ir": result}, job["case_id"])
                case = service.get_case(repo, job["case_id"])
                service.touch_case(repo, case, "document.parsed")
        elif job["kind"] == "extract":
            with store.read() as repo:
                settings = repo.get("settings")
            facts = EdgeClient(settings["edge_url"], settings["edge_model"]).extract(job["payload"]["blocks"])
            with store.transaction() as repo:
                case = service.get_case(repo, job["case_id"])
                if case["revision"] != job["payload"]["revision"]:
                    raise ValueError("提取期间材料已变化，结果未写入")
                for fact in facts:
                    service.save_fact(repo, case["id"], {"field": fact["field"], "value": fact["value"], "source_ids": fact["source_ids"], "confirmed": False, "model_suggestion": {"transform": fact["suggested_transform"], "reason": fact["disclosure_reason"]}}, origin="edge_model")
        elif job["kind"] == "redteam":
            with store.read() as repo:
                task = repo.get(job["payload"]["task_id"], "task")
                service.assert_current(repo, task)
                if (task["version"] != job["payload"]["task_version"]
                        or task.get("attack_input_hash") != job["payload"]["attack_input_hash"]):
                    raise ValueError("红队运行期间任务输入已变化，结果未写入")
                protocols = [repo.get(ident, "risk_protocol") for ident in job["payload"]["protocol_ids"]]
                history = [
                    item.get("request", {}).get("wire_payload")
                    for item in repo.list("disclosure", task["case_id"])
                    if item.get("request", {}).get("wire_payload")
                ]
            secret = os.getenv("LEX_REDTEAM_SECRET", "")
            base = os.getenv("LEX_REDTEAM_URL", "http://redteam:8767")
            client = redteam_client or httpx.Client(trust_env=False)
            runs = []
            try:
                for protocol in protocols:
                    started_at = now()
                    view = {
                        "protocol": protocol,
                        "request": task["request"]["wire_payload"],
                        "disclosed_history": history[-protocol["query_budget"]:] if protocol["query_budget"] else [],
                        "auxiliary": (job["payload"]["auxiliary"].get(protocol["id"])
                                      or job["payload"]["auxiliary"].get(protocol["kind"]) or []),
                        "query_budget": max(1, protocol["query_budget"]),
                    }
                    try:
                        if not secret:
                            raise RuntimeError("redteam secret missing")
                        response = client.post(
                            base + "/evaluate",
                            json={"view": view, "signature": sign(view, secret)},
                            timeout=protocol["time_budget_seconds"],
                        )
                        response.raise_for_status()
                        result = response.json()
                        if (result.get("protocol") != protocol["kind"]
                                or result.get("outcome") not in {"resisted", "succeeded", "uncertain", "error", "not_run"}):
                            raise ValueError("红队返回契约无效")
                        outcome = result["outcome"]
                        score = result.get("score")
                        evidence = [str(item)[:1000] for item in result.get("evidence", [])][:50]
                        query_count = int(result.get("query_count", 0))
                        duration_ms = int(result.get("duration_ms", 0))
                    except Exception as error:
                        outcome, score, query_count, duration_ms = "error", None, 0, 0
                        evidence = [f"红队服务失败：{type(error).__name__}"]
                    run = AttackRun(
                        id=uid("attack"), protocol_id=protocol["id"],
                        protocol_hash=protocol["content_hash"], task_id=task["id"],
                        task_version=task["version"], attack_input_hash=task["attack_input_hash"],
                        outcome=outcome, score=score, evidence=evidence,
                        query_count=query_count, duration_ms=duration_ms,
                        started_at=started_at, finished_at=now(),
                    ).model_dump()
                    run["result_hash"] = digest({key: value for key, value in run.items() if key != "result_hash"})
                    runs.append(run)
            finally:
                if redteam_client is None:
                    client.close()
            with store.transaction() as repo:
                current = repo.get(task["id"], "task")
                service.assert_current(repo, current)
                if (current["version"] != job["payload"]["task_version"]
                        or current.get("attack_input_hash") != job["payload"]["attack_input_hash"]):
                    raise ValueError("红队运行期间任务输入已变化，结果未写入")
                for run in runs:
                    repo.put("attack_run", run, task["id"])
                    audit(repo, task["case_id"], "redteam.protocol.completed",
                          task_id=task["id"], protocol_id=run["protocol_id"],
                          outcome=run["outcome"], result_hash=run["result_hash"])
                current["redteam_status"] = ("complete" if all(run["outcome"] in ("resisted", "succeeded") for run in runs)
                                                else "incomplete")
                repo.put("task", current, task["case_id"])
        elif job["kind"] in ("send", "reconcile"):
            with store.transaction() as repo:
                task = repo.get(job["payload"]["task_id"], "task")
                if job["kind"] == "send":
                    service.assert_current(repo, task)
                    task["status"] = "sending"
                    repo.put("task", task, task["case_id"])
            secret = os.getenv("LEX_GATEWAY_SECRET", "")
            base = os.getenv("LEX_GATEWAY_URL", "http://127.0.0.1:8766")
            client = gateway_client or httpx.Client(timeout=100, trust_env=False)
            try:
                if job["kind"] == "send":
                    content = {"request": task["request"], "approval": task["approval"]}
                    response = client.post(base+"/dispatch", json={**content, "signature": sign(content, secret)})
                else:
                    ident = task["request"]["request_id"]
                    response = client.get(base+"/requests/"+ident, headers={"X-Gateway-Signature": sign({"op": "status", "request_id": ident}, secret)})
                if response.status_code in (400, 403, 409, 422):
                    record = {"status": "rejected"}
                elif response.status_code == 404:
                    record = {"status": "unknown"}
                else:
                    response.raise_for_status()
                    record = response.json()
            except Exception:
                record = {"status": "unknown"}
            finally:
                if gateway_client is None:
                    client.close()
            with store.transaction() as repo:
                task = repo.get(task["id"], "task")
                finish_response(repo, task, record)
        with store.transaction() as repo:
            job.update(status="complete", finished_at=now())
            repo.put("job", job, job["case_id"])
            audit(repo, job["case_id"], "job.complete", job_id=job["id"])
    except Exception as error:
        with store.transaction() as repo:
            # Domain errors contain no provider response text. Other errors are only named.
            detail = str(error) if isinstance(error, ValueError) else type(error).__name__
            job.update(status="failed", error=detail, finished_at=now())
            repo.put("job", job, job["case_id"])
            if job["kind"] == "parse":
                doc = repo.get(job["payload"]["document_id"], "document")
                doc.update(status="failed", error=detail)
                repo.put("document", doc, job["case_id"])
            if job["kind"] == "send":
                task = repo.get(job["payload"]["task_id"], "task")
                finish_response(repo, task, {"status": "unknown"})
            audit(repo, job["case_id"], "job.failed", job_id=job["id"], error_type=type(error).__name__)
    return True


def run():
    root = app_dir()
    root.mkdir(parents=True, exist_ok=True)
    with exclusive_lock(root / "worker.lock", error=SystemExit("已有一个工作进程在运行")):
        store = Store(root / "app.sqlite")
        service.initialize(store)
        recover(store)
        while True:
            if not process_one(store, root):
                time.sleep(0.7)


if __name__ == "__main__":
    run()
