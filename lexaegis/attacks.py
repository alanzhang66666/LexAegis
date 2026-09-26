# SPDX-License-Identifier: Apache-2.0
# New LexAegis implementation following the Ianvs privacy-evaluation taxonomy.
"""Engineering-baseline red-team executor: attacker and scorer are separate.

This module is not a formal attack conclusion and is not a legal endorsement.
The isolated red-team service must not receive mapping or ground-truth keys.
"""
from __future__ import annotations

import re
import time

from .util import digest

FORBIDDEN_KEYS = {"mapping", "mapping_entries", "original_value", "local_text", "anchors", "raw_text", "truth"}
TOKEN = re.compile(r"\[\[LEX:P\d{4,}\]\]")
PERSON_HINT = re.compile(r"(?:申请人|劳动者|职工|员工|原告|被告)(?P<name>[\u4e00-\u9fff]{2,4})")
ID_HINT = re.compile(r"\b\d{17}[\dXx]\b")
PHONE_HINT = re.compile(r"\b1[3-9]\d{9}\b")
AMOUNT_HINT = re.compile(r"(?:工资|加班费|报酬)(?P<value>\d{3,})")

EXECUTOR_VERSION = "lexaegis.attacks.executor/0.2-baseline"
SCORER_VERSION = "lexaegis.attacks.scorer/0.2-baseline"
AUXILIARY_LIBRARY_VERSION = "lexaegis.attacks.auxiliary/0.2"
BASELINE_NOTE = "工程基线执行器，不是正式攻击结论，不能作为法学背书"

# Known-vulnerable synthetic leak used only as a positive control.
POSITIVE_CONTROL_REQUEST = {
    "facts": [
        {
            "id": "fact_positive_control",
            "text": "申请人张三（身份证110101199001011234）主张加班工资12000元",
        }
    ]
}

FORMAL_EXECUTOR_VERSION = "lexaegis.attacks.executor/1.0"
FORMAL_SCORER_VERSION = "lexaegis.attacks.scorer/1.0"
FORMAL_SUITE_NOTE = ("正式攻击套件：协议已冻结并校验哈希，辅助数据按类型+内容哈希声明，"
                     "阳性对照先行；结果仍须法09具名认可才计入 G8")


def assert_isolated_payload(value):
    if isinstance(value, dict):
        if FORBIDDEN_KEYS & {str(key).lower() for key in value}:
            raise ValueError("攻击载荷包含边侧专属数据")
        for child in value.values():
            assert_isolated_payload(child)
    elif isinstance(value, list):
        for child in value:
            assert_isolated_payload(child)


def propose(protocol: dict, request: dict, history: list[dict], auxiliary: list[dict]) -> dict:
    """Attacker: emit candidates, ranking, predictions, and retrieval evidence only."""
    kind = protocol["kind"]
    query_budget = int(protocol.get("query_budget", 0))
    history = history[-query_budget:] if query_budget else []
    text = str(request)
    process = [f"读取攻击者视图 kind={kind}", "未向攻击器提供评分真值"]
    if kind == "identity":
        candidates = _identity_candidates(text, auxiliary)
        process.append(f"从披露文本与辅助线索检索到 {len(candidates)} 个身份候选")
        return _artifacts(kind, candidates, [], process, query_budget, history, text)
    if kind == "candidate_set":
        candidates = _identity_candidates(text, auxiliary)
        process.append(f"由检索证据构造候选集合，大小 {len(candidates)}，不读取传入的 candidate_count")
        return _artifacts(kind, candidates, [], process, query_budget, history, text)
    if kind == "sensitive_inference":
        predictions = _attribute_predictions(text, auxiliary)
        process.append(f"从披露文本与辅助线索得到 {len(predictions)} 条属性预测，不读取传入的 confidence")
        return _artifacts(kind, [], predictions, process, query_budget, history, text)
    if kind == "cross_round":
        current = set(TOKEN.findall(text))
        linked = [item for item in history if current and current & set(TOKEN.findall(str(item)))]
        process.append(f"在 {len(history)} 轮历史中检索到 {len(linked)} 轮稳定 token 关联")
        return {
            "kind": kind,
            "candidates": [],
            "ranking": [],
            "predictions": [],
            "retrieval": [f"shared_tokens={sorted(current)}", f"linked_rounds={len(linked)}"],
            "linked_rounds": len(linked),
            "has_history": bool(history),
            "has_tokens": bool(current),
            "process": process,
            "query_budget": query_budget,
            "history_used": len(history),
            "disclosed_text": text,
        }
    return {
        "kind": kind,
        "candidates": [],
        "ranking": [],
        "predictions": [],
        "retrieval": [],
        "process": process + ["未知攻击类型，攻击器未产出候选"],
        "query_budget": query_budget,
        "history_used": len(history),
        "disclosed_text": text,
        "unknown_kind": True,
    }


def score(protocol: dict, artifacts: dict, labels: dict | None = None) -> dict:
    """Scorer: read labels independently. Never trust attacker-supplied scores."""
    kind = artifacts.get("kind") or protocol["kind"]
    threshold = float(protocol["threshold"])
    criteria = protocol.get("success_criteria") or {}
    operator = criteria.get("operator", "gte")
    if artifacts.get("unknown_kind"):
        return {"outcome": "error", "score": None, "evidence": ["未知攻击类型"], "completion": "incomplete"}
    if operator not in ("gte", "gt", "lte", "lt"):
        return {"outcome": "error", "score": None, "evidence": ["success_criteria.operator 不受支持"], "completion": "incomplete"}
    labels = labels or {}
    text = str(artifacts.get("disclosed_text", ""))
    if kind == "identity":
        names = [item["candidate"] for item in artifacts.get("candidates") or []]
        if not names:
            return _uncertain("攻击器未产出身份候选，记为无能力，不得视为 resisted")
        expected = labels.get("identity")
        recovered = expected in names if expected else any(_leaked_identifier(name, text) for name in names)
        if expected and not recovered:
            return _compared(0.0, threshold, operator, [f"评分器对照真值，未恢复 {expected}"])
        if recovered:
            return _compared(1.0, threshold, operator, [f"评分器确认身份恢复：{names[0]}"])
        return _uncertain("有候选但无独立真值可核对，不能记为 resisted")
    if kind == "candidate_set":
        names = [item["candidate"] for item in artifacts.get("candidates") or []]
        if not names:
            return _uncertain("攻击器未产出候选集合，记为无能力，不得视为 resisted")
        expected = labels.get("identity")
        if expected and expected not in names:
            return _compared(0.0, threshold, operator, ["评分器对照真值，候选集合未覆盖主体"])
        return _compared(1 / len(names), threshold, operator, [f"评分器按攻击器集合计分，大小 {len(names)}"])
    if kind == "sensitive_inference":
        predictions = artifacts.get("predictions") or []
        if not predictions:
            return _uncertain("攻击器未产出属性预测，记为无能力，不得视为 resisted")
        expected = labels.get("attribute")
        if expected:
            matched = any(item.get("value") == expected or item.get("attribute") == expected for item in predictions)
            return _compared(1.0 if matched else 0.0, threshold, operator, ["评分器对照属性真值"])
        grounded = [item for item in predictions if str(item.get("value", "")) and str(item["value"]) in text]
        if not grounded:
            return _uncertain("属性预测缺少可核对的披露依据，不能记为 resisted")
        return _compared(max(float(item.get("confidence") or 0) for item in grounded), threshold, operator,
                         ["评分器按披露文本核对属性预测"])
    if kind == "cross_round":
        if not artifacts.get("has_history"):
            return _uncertain("没有跨轮历史，攻击器无能力，不得视为 resisted")
        if not artifacts.get("has_tokens"):
            return _uncertain("当前披露没有可关联 token，不能记为 resisted")
        budget = max(1, int(artifacts.get("query_budget") or protocol.get("query_budget") or 1))
        score = min(1.0, int(artifacts.get("linked_rounds") or 0) / budget)
        return _compared(score, threshold, operator, [f"评分器统计 {artifacts.get('linked_rounds', 0)} 轮可关联披露"])
    return {"outcome": "error", "score": None, "evidence": ["未知攻击类型"], "completion": "incomplete"}


def evaluate(protocol: dict, request: dict, history: list[dict], auxiliary: list[dict], labels: dict | None = None) -> dict:
    started = time.monotonic()
    assert_isolated_payload({"request": request, "history": history, "auxiliary": auxiliary})
    required_auxiliary = protocol.get("auxiliary_data", [])
    if required_auxiliary and not auxiliary:
        return _result(protocol.get("kind"), "uncertain", None, ["协议声明了辅助数据，但本次运行未提供"], 0, started,
                       request, history, auxiliary, ["辅助库为空"])
    artifacts = propose(protocol, request, history, auxiliary)
    judged = score(protocol, artifacts, labels)
    evidence = [BASELINE_NOTE, *artifacts.get("process", []), *judged.get("evidence", [])]
    return _result(artifacts.get("kind") or protocol.get("kind"), judged["outcome"], judged.get("score"), evidence,
                   artifacts.get("history_used", 0), started, request, history, auxiliary, artifacts.get("process", []),
                   artifacts)


def _identity_candidates(text: str, auxiliary: list[dict]) -> list[dict]:
    found = []
    seen = set()

    def add(candidate, evidence, rank):
        key = str(candidate).strip()
        if not key or key in seen:
            return
        seen.add(key)
        found.append({"candidate": key, "evidence": evidence, "rank": rank})

    for match in PERSON_HINT.finditer(text):
        add(match.group("name"), f"披露文本称谓后出现 {match.group('name')}", 1.1)
    for match in ID_HINT.finditer(text):
        add(match.group(0), "披露文本含身份证号", 1.0)
    for match in PHONE_HINT.finditer(text):
        add(match.group(0), "披露文本含手机号", 0.9)
    for item in auxiliary:
        candidate = item.get("candidate")
        clue = str(item.get("clue", ""))
        if candidate and clue and clue in text:
            add(candidate, f"辅助线索命中披露文本：{clue}", 0.8)
        elif candidate and str(candidate) in text:
            add(candidate, "辅助候选直接出现在披露文本", 0.85)
    found.sort(key=lambda item: (-item["rank"], item["candidate"]))
    return found


def _attribute_predictions(text: str, auxiliary: list[dict]) -> list[dict]:
    predictions = []
    for match in AMOUNT_HINT.finditer(text):
        predictions.append({
            "attribute": "wage",
            "value": match.group("value"),
            "confidence": 1.0,
            "evidence": f"披露文本含金额线索 {match.group('value')}",
        })
    for item in auxiliary:
        attribute = item.get("attribute")
        value = item.get("value")
        clue = str(item.get("clue", ""))
        if attribute and value is not None and clue and clue in text:
            predictions.append({
                "attribute": str(attribute),
                "value": str(value),
                "confidence": 0.8,
                "evidence": f"辅助属性线索命中：{clue}",
            })
    return predictions


def _leaked_identifier(name: str, text: str) -> bool:
    return bool(name) and name in text


def _artifacts(kind, candidates, predictions, process, query_budget, history, text):
    return {
        "kind": kind,
        "candidates": candidates,
        "ranking": [item["candidate"] for item in candidates],
        "predictions": predictions,
        "retrieval": [item.get("evidence") for item in candidates + predictions],
        "process": process,
        "query_budget": query_budget,
        "history_used": len(history),
        "disclosed_text": text,
    }


def _compared(score, threshold, operator, evidence):
    comparisons = {"gte": score >= threshold, "gt": score > threshold, "lte": score <= threshold, "lt": score < threshold}
    outcome = "succeeded" if comparisons[operator] else "resisted"
    return {"outcome": outcome, "score": score, "evidence": evidence, "completion": "complete"}


def _uncertain(message):
    return {"outcome": "uncertain", "score": None, "evidence": [message], "completion": "incomplete"}


def _result(kind, outcome, score, evidence, query_count, started, request, history, auxiliary, process, artifacts=None):
    duration_ms = int((time.monotonic() - started) * 1000) if started is not None else 0
    view_hash = digest({"request": request, "history": history, "auxiliary": auxiliary})
    return {
        "capability": "available",
        "completion": "complete" if outcome in ("resisted", "succeeded") else "incomplete",
        "outcome": outcome,
        "protocol": kind,
        "score": score,
        "evidence": evidence,
        "query_count": query_count,
        "duration_ms": duration_ms,
        "executor_version": EXECUTOR_VERSION,
        "scorer_version": SCORER_VERSION,
        "auxiliary_library_version": AUXILIARY_LIBRARY_VERSION,
        "attacker_view_hash": view_hash,
        "query_budget": int((artifacts or {}).get("query_budget") or 0),
        "process": process,
        "baseline": "engineering",
    }


POSITIVE_CONTROL_PROTOCOL = {
    "id": "positive_control", "kind": "identity", "version": "control-1.0",
    "attacker_view": {}, "auxiliary_data": [], "query_budget": 0,
    "time_budget_seconds": 30, "success_criteria": {"operator": "gte"}, "threshold": 0.5,
}


def check_positive_control(evaluate_fn) -> dict:
    """阳性对照先行：在已知泄漏输入上，评测链必须能检出恢复，否则本次套件无效。"""
    result = evaluate_fn(POSITIVE_CONTROL_PROTOCOL, POSITIVE_CONTROL_REQUEST, [], [], None)
    detected = result.get("outcome") == "succeeded"
    return {
        "detected": bool(detected),
        "outcome": result.get("outcome"),
        "score": result.get("score"),
        "evidence": [*(result.get("evidence") or [])[:5]],
        "attacker_view_hash": result.get("attacker_view_hash"),
        "engine_version": result.get("executor_version"),
    }


def validate_auxiliary_sets(protocols: list[dict], auxiliary_sets: dict | None) -> dict:
    """声明式辅助数据集：逐集合校验 content_hash，按协议 declared auxiliary_data 覆盖。

    auxiliary_sets = {protocol_id|kind: [{dataset_id, dataset_kind, content_hash, entries}]}
    返回 {protocol_id: flattened_entries}。"""
    auxiliary_sets = auxiliary_sets or {}
    provided = {}
    for protocol in protocols:
        datasets = (auxiliary_sets.get(protocol["id"]) or auxiliary_sets.get(protocol["kind"]) or [])
        for dataset in datasets:
            entries = dataset.get("entries")
            if not isinstance(entries, list):
                raise ValueError(f"辅助数据集 {dataset.get('dataset_id')} 缺 entries")
            if digest(entries) != dataset.get("content_hash"):
                raise ValueError(f"辅助数据集 {dataset.get('dataset_id')} content_hash 与 entries 不符")
            assert_isolated_payload(entries)
        required = protocol.get("auxiliary_data") or []
        covered = {item.get("dataset_kind") for item in datasets}
        missing = [kind for kind in required if kind not in covered]
        if missing:
            raise ValueError(f"协议 {protocol['id']} 声明的辅助数据未提供：" + "、".join(missing))
        provided[protocol["id"]] = [entry for dataset in datasets for entry in dataset["entries"]]
    return provided


def run_formal_suite(repo, task: dict, *, evaluate_fn, auxiliary_sets: dict | None = None,
                     labels: dict | None = None, history: list | None = None,
                     transport: str = "isolated_redteam", at=None) -> dict:
    """正式攻击套件执行器 1.0。

    - 协议必须冻结且 content_hash 与请求依赖中 risk_protocol_hashes 逐字一致
    - 辅助数据集按内容哈希声明，孤立载荷校验后进入攻击者视图
    - 阳性对照先行；对照失败 -> 全部 not_run，套件 invalid
    - 每次 run 绑定 request_hash / attack_input_hash / task_version，不可跨版本复用
    返回 attack_suite_run 记录（kind="attack_suite_run"），并写入 attack_run 明细。"""
    from .contracts import AttackRun
    from .governance import protocols_for_pack
    from .util import now, uid

    request_hash = task.get("request_hash")
    if not request_hash:
        raise ValueError("任务尚未冻结 request_hash，不能运行正式攻击套件")
    attack_input_hash = task.get("attack_input_hash")
    if not attack_input_hash:
        raise ValueError("任务缺少 attack_input_hash，不能运行正式攻击套件")
    pack = repo.get(task["pack_id"], "pack")
    protocols = protocols_for_pack(repo, pack)
    frozen_hashes = ((task.get("request") or {}).get("dependencies") or {}).get("risk_protocol_hashes") or {}
    for protocol in protocols:
        bound = frozen_hashes.get(protocol["kind"])
        if bound and bound != protocol["content_hash"]:
            raise ValueError(f"协议 {protocol['id']} 哈希与请求冻结版本不符，攻击运行不可复用")
    provided = validate_auxiliary_sets(protocols, auxiliary_sets)

    suite_id = uid("attacksuite")
    started_at = now()
    control = check_positive_control(evaluate_fn)
    suite = {
        "id": suite_id, "task_id": task["id"], "task_version": task["version"],
        "request_hash": request_hash, "attack_input_hash": attack_input_hash,
        "transport": transport, "executor_version": FORMAL_EXECUTOR_VERSION,
        "scorer_version": FORMAL_SCORER_VERSION,
        "positive_control": control,
        "auxiliary_sets": [
            {"protocol_id": protocol["id"],
             "datasets": [{"dataset_id": d.get("dataset_id"), "dataset_kind": d.get("dataset_kind"),
                           "content_hash": d.get("content_hash"), "entry_count": len(d["entries"])}
                          for d in (auxiliary_sets or {}).get(protocol["id"], (auxiliary_sets or {}).get(protocol["kind"], []) or [])]}
            for protocol in protocols
        ],
        "run_ids": [], "run_hashes": [], "conclusion": "invalid",
        "all_resisted": False, "created_at": started_at, "note": FORMAL_SUITE_NOTE,
    }
    if control["detected"]:
        history = history or []
        runs = []
        for protocol in protocols:
            budget = max(1, int(protocol.get("query_budget") or 1))
            view_history = history[-protocol["query_budget"]:] if protocol.get("query_budget") else []
            try:
                result = evaluate_fn(protocol, task["request"]["wire_payload"], view_history,
                                     provided.get(protocol["id"]) or [], labels)
                outcome = result.get("outcome")
                if outcome not in {"resisted", "succeeded", "uncertain", "error"}:
                    raise ValueError("引擎返回契约无效")
                run = AttackRun(
                    id=uid("attack"), protocol_id=protocol["id"],
                    protocol_hash=protocol["content_hash"], task_id=task["id"],
                    task_version=task["version"], attack_input_hash=attack_input_hash,
                    outcome=outcome, score=result.get("score"),
                    evidence=[FORMAL_SUITE_NOTE,
                              f"engine={result.get('executor_version')}",
                              *[str(item)[:1000] for item in result.get("evidence", [])][:48]],
                    query_count=int(result.get("query_count", 0)),
                    duration_ms=int(result.get("duration_ms", 0)),
                    executor_version=FORMAL_EXECUTOR_VERSION, suite_id=suite_id,
                    request_hash=request_hash, started_at=now(), finished_at=now(),
                ).model_dump()
            except Exception as error:
                run = AttackRun(
                    id=uid("attack"), protocol_id=protocol["id"],
                    protocol_hash=protocol["content_hash"], task_id=task["id"],
                    task_version=task["version"], attack_input_hash=attack_input_hash,
                    outcome="error", evidence=[f"正式套件执行异常：{type(error).__name__}"],
                    executor_version=FORMAL_EXECUTOR_VERSION, suite_id=suite_id,
                    request_hash=request_hash, started_at=now(), finished_at=now(),
                ).model_dump()
            run["result_hash"] = digest({k: v for k, v in run.items() if k != "result_hash"})
            repo.put("attack_run", run, task["id"])
            runs.append(run)
        suite["run_ids"] = [run["id"] for run in runs]
        suite["run_hashes"] = [run["result_hash"] for run in runs]
        suite["engine_versions"] = {protocol["kind"]: run.get("evidence", [None])[1]
                                    for protocol, run in zip(protocols, runs)}
        suite["all_resisted"] = all(run["outcome"] == "resisted" for run in runs)
        suite["conclusion"] = "complete"
    else:
        for protocol in protocols:
            run = AttackRun(
                id=uid("attack"), protocol_id=protocol["id"],
                protocol_hash=protocol["content_hash"], task_id=task["id"],
                task_version=task["version"], attack_input_hash=attack_input_hash,
                outcome="not_run",
                evidence=["阳性对照未检出已知泄漏，评测链不可信，本次套件无效"],
                executor_version=FORMAL_EXECUTOR_VERSION, suite_id=suite_id,
                request_hash=request_hash, started_at=started_at, finished_at=now(),
            ).model_dump()
            run["result_hash"] = digest({k: v for k, v in run.items() if k != "result_hash"})
            repo.put("attack_run", run, task["id"])
            suite["run_ids"].append(run["id"])
            suite["run_hashes"].append(run["result_hash"])
    suite["finished_at"] = now()
    suite["suite_hash"] = digest({k: v for k, v in suite.items() if k != "suite_hash"})
    repo.put("attack_suite_run", suite, task["id"])
    return suite
