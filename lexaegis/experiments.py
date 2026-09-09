# SPDX-License-Identifier: Apache-2.0
# Modified for LexAegis from concepts in kubeedge/ianvs PRs #282/#283 at 8150672e.
"""Reproducible offline privacy experiments; never imported by dispatch."""
from __future__ import annotations

import json
import math
import platform
import random
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .contracts import PrivacyTransformRun
from .util import digest


FORBIDDEN_EXPERIMENT_KEYS = {
    "mapping", "mapping_entries", "original_value", "local_text", "anchors",
    "raw_text", "gateway_secret", "api_key", "case_database",
}


def assert_experiment_payload(value):
    if isinstance(value, dict):
        if FORBIDDEN_EXPERIMENT_KEYS & {str(key).lower() for key in value}:
            raise ValueError("实验输入包含正式链路或边侧专属数据")
        for child in value.values():
            assert_experiment_payload(child)
    elif isinstance(value, list):
        for child in value:
            assert_experiment_payload(child)


def _finite_vector(vector) -> list[float]:
    if not isinstance(vector, list) or not vector:
        raise ValueError("向量不能为空")
    values = [float(value) for value in vector]
    if any(not math.isfinite(value) for value in values):
        raise ValueError("向量只能包含有限数值")
    return values


def validate_vectors(vectors) -> list[list[float]]:
    if not isinstance(vectors, list) or not vectors:
        raise ValueError("必须提供真实实验向量")
    result = [_finite_vector(vector) for vector in vectors]
    width = len(result[0])
    if any(len(vector) != width for vector in result) or len(result) > 10000 or width > 10000:
        raise ValueError("向量维度不一致或超过实验上限")
    return result


def l2_clip(vector: list[float], max_norm: float) -> list[float]:
    if max_norm <= 0:
        raise ValueError("max_norm 必须大于 0")
    vector = _finite_vector(vector)
    norm = math.sqrt(sum(value ** 2 for value in vector))
    scale = min(1.0, max_norm / max(norm, 1e-12))
    return [value * scale for value in vector]


def gaussian_dp(vector: list[float], *, max_norm: float, noise_multiplier: float, seed: int) -> dict:
    if noise_multiplier <= 0:
        raise ValueError("noise_multiplier 必须大于 0")
    clipped = l2_clip(vector, max_norm)
    rng = random.Random(seed)
    sigma = max_norm * noise_multiplier
    return {"vector": [value + rng.gauss(0, sigma) for value in clipped],
            "clipped_norm": math.sqrt(sum(value * value for value in clipped)), "sigma": sigma}


def rdp_gaussian(*, noise_multiplier: float, steps: int, orders: list[float]) -> dict[float, float]:
    if noise_multiplier <= 0 or steps < 0 or any(order <= 1 for order in orders):
        raise ValueError("RDP 参数无效")
    return {float(order): steps * float(order) / (2 * noise_multiplier ** 2) for order in orders}


def rdp_to_epsilon(rdp: dict[float, float], delta: float) -> float:
    if not 0 < delta < 1 or not rdp:
        raise ValueError("delta 或 RDP 为空")
    return min(value + math.log(1 / delta) / (order - 1) for order, value in rdp.items())


def random_projection(vectors: list[list[float]], target_dim: int, seed: int) -> dict:
    vectors = validate_vectors(vectors)
    source_dim = len(vectors[0])
    if not 0 < target_dim <= source_dim:
        raise ValueError("投影目标维度无效")
    rng = random.Random(seed)
    scale = 1 / math.sqrt(target_dim)
    matrix = [[rng.gauss(0, scale) for _ in range(target_dim)] for _ in range(source_dim)]
    output = _apply_projection(vectors, matrix)
    return {"vectors": output, "matrix": matrix, "seed": seed}


def sparse_random_projection(vectors: list[list[float]], target_dim: int, seed: int) -> dict:
    vectors = validate_vectors(vectors)
    source_dim = len(vectors[0])
    if not 0 < target_dim <= source_dim:
        raise ValueError("投影目标维度无效")
    rng = random.Random(seed)
    scale = math.sqrt(3 / target_dim)
    choices = (-scale, 0.0, 0.0, 0.0, 0.0, scale)
    matrix = [[rng.choice(choices) for _ in range(target_dim)] for _ in range(source_dim)]
    return {"vectors": _apply_projection(vectors, matrix), "matrix": matrix, "seed": seed}


def _apply_projection(vectors, matrix):
    return [[sum(row[index] * matrix[index][column] for index in range(len(row)))
             for column in range(len(matrix[0]))] for row in vectors]


def _dot(left, right):
    return sum(a * b for a, b in zip(left, right))


def _normalize(vector):
    norm = math.sqrt(_dot(vector, vector))
    return [value / max(norm, 1e-12) for value in vector]


def pca_projection(vectors: list[list[float]], target_dim: int, seed: int, iterations: int = 100) -> dict:
    """Small dependency-free PCA using deterministic power iteration."""
    vectors = validate_vectors(vectors)
    source_dim = len(vectors[0])
    if not 0 < target_dim <= min(source_dim, len(vectors)):
        raise ValueError("PCA 目标维度无效")
    means = [sum(row[index] for row in vectors) / len(vectors) for index in range(source_dim)]
    centered = [[value - means[index] for index, value in enumerate(row)] for row in vectors]
    covariance = [[sum(row[i] * row[j] for row in centered) / max(1, len(centered) - 1)
                   for j in range(source_dim)] for i in range(source_dim)]
    rng = random.Random(seed)
    components = []
    eigenvalues = []
    residual = [row[:] for row in covariance]
    for _ in range(target_dim):
        vector = _normalize([rng.uniform(-1, 1) for _ in range(source_dim)])
        for _ in range(iterations):
            vector = _normalize([_dot(row, vector) for row in residual])
        eigenvalue = max(0.0, _dot(vector, [_dot(row, vector) for row in residual]))
        components.append(vector)
        eigenvalues.append(eigenvalue)
        for i in range(source_dim):
            for j in range(source_dim):
                residual[i][j] -= eigenvalue * vector[i] * vector[j]
    matrix = [[components[column][row] for column in range(target_dim)] for row in range(source_dim)]
    return {"vectors": _apply_projection(centered, matrix), "matrix": matrix, "mean": means,
            "eigenvalues": eigenvalues, "seed": seed}


def distance_preservation(original: list[list[float]], projected: list[list[float]]) -> dict:
    if len(original) != len(projected):
        raise ValueError("距离比较样本数不一致")
    distortions = []
    for i in range(len(original)):
        for j in range(i + 1, len(original)):
            before = math.sqrt(sum((a - b) ** 2 for a, b in zip(original[i], original[j])))
            after = math.sqrt(sum((a - b) ** 2 for a, b in zip(projected[i], projected[j])))
            if before > 1e-12:
                distortions.append(abs(after / before - 1))
    if not distortions:
        return {"outcome": "not_applicable", "detail": "没有非零样本对距离"}
    return {"outcome": "measured", "pair_count": len(distortions),
            "mean_relative_distortion": sum(distortions) / len(distortions),
            "max_relative_distortion": max(distortions)}


def saliency_mask(tokens: list[str], scores: list[float], fraction: float, mask_token: str = "[MASK]") -> list[str]:
    if len(tokens) != len(scores) or not 0 <= fraction <= 1:
        raise ValueError("显著性掩码参数无效")
    if any(not math.isfinite(float(score)) for score in scores):
        raise ValueError("显著性分数无效")
    count = math.ceil(len(tokens) * fraction)
    selected = {index for index, _ in sorted(enumerate(scores), key=lambda item: (-float(item[1]), item[0]))[:count]}
    return [mask_token if index in selected else token for index, token in enumerate(tokens)]


def heuristic_saliency(tokens: list[str]) -> list[float]:
    return [float(any(char.isdigit() for char in token)) + min(len(token), 8) / 16 for token in tokens]


def _auc(member_scores: list[float], nonmember_scores: list[float]) -> dict:
    if not member_scores or not nonmember_scores:
        return {"outcome": "not_applicable", "detail": "成员或非成员真实输出为空"}
    scores = member_scores + nonmember_scores
    if len(set(round(value, 12) for value in scores)) < 2:
        return {"outcome": "uncertain", "detail": "指标分数为常量，禁止报告伪区分能力"}
    wins = sum(1 if member > nonmember else .5 if member == nonmember else 0
               for member in member_scores for nonmember in nonmember_scores)
    return {"outcome": "measured", "auc": wins / (len(member_scores) * len(nonmember_scores)),
            "member_count": len(member_scores), "nonmember_count": len(nonmember_scores)}


def membership_metrics(target_outputs) -> dict:
    if not target_outputs or target_outputs.get("source") != "real_target_model" or not target_outputs.get("model_hash"):
        return {name: {"outcome": "not_applicable", "detail": "未提供带模型哈希的真实目标模型输出"}
                for name in ("loss", "neighbourhood", "lira", "inversion")}
    members = target_outputs.get("members") or []
    nonmembers = target_outputs.get("nonmembers") or []

    def scores(key, transform=lambda value: float(value)):
        left = [transform(item[key]) for item in members if isinstance(item, dict) and key in item]
        right = [transform(item[key]) for item in nonmembers if isinstance(item, dict) and key in item]
        return _auc(left, right)

    loss = scores("loss", lambda value: -float(value))
    lira = scores("lira_score")
    inversion = scores("inversion_similarity")

    def neighbourhood(items):
        result = []
        for item in items:
            if not isinstance(item, dict):
                continue
            values = item.get("neighbour_losses")
            if "loss" not in item or not isinstance(values, list) or not values:
                continue
            result.append(sum(float(value) for value in values) / len(values) - float(item["loss"]))
        return result

    neighbour = _auc(neighbourhood(members), neighbourhood(nonmembers))
    return {"loss": loss, "neighbourhood": neighbour, "lira": lira, "inversion": inversion}


def mia_requires_real_outputs(target_outputs) -> dict:
    metrics = membership_metrics(target_outputs)
    if all(item["outcome"] == "not_applicable" for item in metrics.values()):
        return {"outcome": "not_applicable", "detail": "未提供真实目标模型输出；禁止生成模拟 loss 或常量指标。"}
    return {"outcome": "measured", "metrics": metrics}


def _environment() -> dict[str, str]:
    return {"python": platform.python_version(), "platform": platform.platform(),
            "implementation": platform.python_implementation()}


def _run_record(algorithm, input_hash, parameters, output, *, input_model_hash=None,
                matrix=None, provenance="numeric_input", budget=None, metrics=None):
    core = {"algorithm": algorithm, "input_hash": input_hash, "input_model_hash": input_model_hash,
            "parameters": parameters, "output_hash": digest(output),
            "matrix_hash": digest(matrix) if matrix is not None else None,
            "provenance": provenance, "budget": budget or {}, "metrics": metrics or {}}
    return PrivacyTransformRun(
        id="transform_" + digest(core)[:16], **core, environment=_environment(),
        created_at=datetime.now(timezone.utc).isoformat(),
    ).model_dump()


def run_ianvs_profile(payload: dict | None, *, seed=23, target_dim=2, max_norm=1.0,
                      noise_multiplier=1.0, delta=1e-5, mask_fraction=.25,
                      epsilon_budget=None) -> dict:
    if payload is None:
        return {"schema_version": 1, "profile": "ianvs-pipl", "production_dispatch": False,
                "status": "input_required", "transforms": [],
                "mia": mia_requires_real_outputs(None),
                "detail": "提供显式实验向量后才运行；不会从文本构造哈希伪向量。"}
    assert_experiment_payload(payload)
    vectors = validate_vectors(payload.get("vectors"))
    input_hash = digest(vectors)
    input_model_hash = payload.get("input_model_hash")
    if not isinstance(input_model_hash, str) or not input_model_hash.strip():
        raise ValueError("完整实验必须提供输入模型或向量生成器哈希")
    dimensions = min(int(target_dim), len(vectors[0]), len(vectors))
    if dimensions <= 0:
        raise ValueError("目标维度无效")
    transforms = []

    dp_vectors = [gaussian_dp(vector, max_norm=max_norm, noise_multiplier=noise_multiplier, seed=seed + index)
                  for index, vector in enumerate(vectors)]
    orders = [2.0, 4.0, 8.0, 16.0, 32.0]
    rdp = rdp_gaussian(noise_multiplier=noise_multiplier, steps=len(vectors), orders=orders)
    epsilon = rdp_to_epsilon(rdp, delta)
    budget = {"accountant": "rdp", "orders": {str(key): value for key, value in rdp.items()},
              "delta": delta, "epsilon": epsilon, "limit": epsilon_budget,
              "status": "within_budget" if epsilon_budget is None or epsilon <= epsilon_budget else "exceeded"}
    transforms.append(_run_record("gaussian_dp", input_hash,
                      {"max_norm": max_norm, "noise_multiplier": noise_multiplier, "seed": seed},
                      [item["vector"] for item in dp_vectors], input_model_hash=input_model_hash, budget=budget))

    jl = random_projection(vectors, dimensions, seed)
    jl_metric = distance_preservation(vectors, jl["vectors"])
    transforms.append(_run_record("jl", input_hash, {"target_dim": dimensions, "seed": seed},
                      jl["vectors"], input_model_hash=input_model_hash, matrix=jl["matrix"],
                      metrics={"distance_preservation": jl_metric}))

    sparse = sparse_random_projection(vectors, dimensions, seed)
    transforms.append(_run_record("random_projection", input_hash, {"target_dim": dimensions, "seed": seed},
                      sparse["vectors"], input_model_hash=input_model_hash, matrix=sparse["matrix"],
                      metrics={"distance_preservation": distance_preservation(vectors, sparse["vectors"])}))

    pca = pca_projection(vectors, dimensions, seed)
    transforms.append(_run_record("pca", input_hash, {"target_dim": dimensions, "seed": seed, "iterations": 100},
                      pca["vectors"], input_model_hash=input_model_hash, matrix=pca["matrix"],
                      metrics={"eigenvalues": pca["eigenvalues"],
                               "distance_preservation": distance_preservation(vectors, pca["vectors"])}))

    saliency = payload.get("saliency")
    if saliency:
        tokens = saliency.get("tokens")
        if not isinstance(tokens, list) or not all(isinstance(token, str) for token in tokens):
            raise ValueError("显著性输入必须包含 token 字符串数组")
        source = saliency.get("source", "heuristic")
        if source == "experimental_model":
            scores = saliency.get("scores")
            model_hash = saliency.get("model_hash")
            if not model_hash or not isinstance(scores, list):
                raise ValueError("实验模型显著性必须提供分数和模型哈希")
            provenance = "experimental_model"
        elif source == "heuristic":
            scores = saliency.get("scores") or heuristic_saliency(tokens)
            model_hash = None
            provenance = "heuristic"
        else:
            raise ValueError("显著性来源必须为 heuristic 或 experimental_model")
        masked = saliency_mask(tokens, scores, mask_fraction)
        transforms.append(_run_record("saliency_mask", digest(tokens),
                          {"fraction": mask_fraction, "mask_token": "[MASK]"}, masked,
                          input_model_hash=model_hash, provenance=provenance))

    metrics = membership_metrics(payload.get("target_outputs"))
    frozen_transforms = [
        {key: value for key, value in item.items() if key not in ("created_at", "environment")}
        for item in transforms
    ]
    report_core = {"profile": "ianvs-pipl", "input_hash": input_hash, "input_model_hash": input_model_hash,
                   "parameters": {"seed": seed, "target_dim": dimensions, "max_norm": max_norm,
                                  "noise_multiplier": noise_multiplier, "delta": delta,
                                  "mask_fraction": mask_fraction, "epsilon_budget": epsilon_budget},
                   "transforms": frozen_transforms, "membership_metrics": metrics}
    return {"schema_version": 1, **report_core, "transforms": transforms, "report_hash": digest(report_core),
            "production_dispatch": False, "status": "complete",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "environment": _environment(),
            "detail": "Ianvs 分类的实验性对照；不替代可读事实、证据回链或正式风险门禁。"}


COMPARABLE_IDENTITY_K = 3
COMPARABLE_QUERY_BUDGET = 8
COMPARABLE_IDENTITY_PROTOCOL = {
    "kind": "identity",
    "query_budget": COMPARABLE_QUERY_BUDGET,
    "threshold": 1.0,
    "success_criteria": {"operator": "gte", "metric": "identity_top1"},
    "auxiliary_data": ["frozen_local_synthetic_directory"],
    "k": COMPARABLE_IDENTITY_K,
}
UNSCORED_COMPARABLE = {
    "legal_availability": {
        "outcome": "not_scored",
        "detail": "法学可用性依赖双人标注与盲审，当前标注为 pending，不生成或推断分数",
    },
    "privacy_reduction_rate": {
        "outcome": "not_scored",
        "detail": "未定义可核对的隐私降低率，禁止用标识计数冒充降低率",
    },
    "aura": {
        "outcome": "not_applicable",
        "detail": "不得把 AURA 或其他论文数字搬到本劳动争议冒烟结果",
    },
    "human_cost": {
        "outcome": "not_applicable",
        "detail": "未测量复核时间、修改次数或人工放弃；分母也不构造",
    },
    "interval_estimate": {
        "outcome": "not_applicable",
        "detail": "8 条为冒烟规模，不报告区间估计或总体推断",
    },
    "sensitive_inference": {
        "outcome": "not_scored",
        "detail": "无独立属性标注，不把攻击器置信度当成功率",
    },
    "cross_round": {
        "outcome": "not_scored",
        "detail": "本对照无跨轮历史",
    },
}
_TOKEN_SPAN = re.compile(r"\[\[LEX:[POLC]\d{4,}\]\]")
_NUM_SPAN = re.compile(r"\d+(?:\.\d+)?")


def pending_labels_document() -> dict:
    return {
        "schema_version": 1,
        "status": "pending",
        "annotator_a": None,
        "annotator_b": None,
        "adjudication": None,
        "records": {},
        "note": "双人独立标注尚未开始。此模板不含标签，不得当作已有法学标注。",
    }


def load_comparable_labels(path=None) -> dict:
    pending = pending_labels_document()
    if path is None:
        return pending
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("标注文件必须是 JSON 对象")
    if raw.get("status") != "complete" or not raw.get("records"):
        return {**pending, "source_path": str(path), "status": raw.get("status") or "pending"}
    return raw


def _proxy(kind: str, *, failure_class=None) -> dict:
    if kind == "not_applicable":
        return {"outcome": "not_applicable", "numerator": 0, "denominator": 0, "failure_class": None}
    if kind == "pass":
        return {"outcome": "measured", "numerator": 1, "denominator": 1, "failure_class": None}
    return {"outcome": "measured", "numerator": 0, "denominator": 1,
            "failure_class": failure_class or "failed"}


def _fact_text(record: dict, fact_id: str) -> str:
    for fact in record.get("facts") or []:
        if fact.get("id") == fact_id:
            return fact.get("text") or fact.get("value") or ""
    return ""


def _fact_output(artifact: dict, fact_id: str) -> str:
    for item in artifact.get("fact_outputs") or []:
        if item.get("fact_id") == fact_id:
            return item.get("output") or ""
    return ""


def _source_text(record: dict) -> str:
    blocks = (record.get("document") or {}).get("blocks") or []
    return "".join(block.get("text") or "" for block in blocks)


def legal_utility_proxies(record: dict, artifact: dict) -> dict:
    """Deterministic proxies only. Empty or missing inputs stay not_applicable."""
    from .disclosure import NEGATION_MARKERS, has_calendar_day, month_truncated, shifted_calendar

    source = _source_text(record)
    payload = artifact.get("payload") or ""
    person = _fact_text(record, "fact_person")
    employer = _fact_text(record, "fact_employer")
    evidence = _fact_text(record, "fact_evidence")
    date_text = _fact_text(record, "fact_date")
    amount_text = _fact_text(record, "fact_amount")
    person_out = _fact_output(artifact, "fact_person")
    employer_out = _fact_output(artifact, "fact_employer")
    evidence_out = _fact_output(artifact, "fact_evidence")
    date_out = _fact_output(artifact, "fact_date")
    amount_out = _fact_output(artifact, "fact_amount")

    if employer and person_out and employer in person_out and person not in person_out:
        subject = _proxy("fail", failure_class="subject_swapped")
    elif person and employer_out and person in employer_out and employer not in employer_out:
        subject = _proxy("fail", failure_class="subject_swapped")
    elif not (person_out or employer_out or person in payload or employer in payload
              or "某劳动者" in payload or "[[LEX:" in payload):
        subject = _proxy("fail", failure_class="deleted_decisive_fact")
    else:
        subject = _proxy("pass")

    if evidence_out or (evidence and evidence in payload):
        evidence_metric = _proxy("pass")
    elif evidence:
        evidence_metric = _proxy("fail", failure_class="deleted_decisive_fact")
    else:
        evidence_metric = _proxy("not_applicable")

    date_view = date_out or payload
    iso_month = bool(re.search(r"\d{4}[-/]\d{1,2}(?![-/\d])", date_view)) and not has_calendar_day(date_view)
    if not date_text:
        date_metric = _proxy("not_applicable")
    elif (month_truncated(date_text, date_view) or month_truncated(source, payload)
          or (has_calendar_day(date_text) and iso_month and date_text not in date_view)):
        date_metric = _proxy("fail", failure_class="calendar_truncated")
    elif shifted_calendar(date_text, date_view) or shifted_calendar(source, payload):
        date_metric = _proxy("fail", failure_class="calendar_shifted")
    elif date_text in payload or date_text in date_out or has_calendar_day(date_view):
        date_metric = _proxy("pass")
    else:
        date_metric = _proxy("fail", failure_class="deleted_decisive_fact")

    amount_digits = "".join(_NUM_SPAN.findall(amount_text))
    if not amount_digits:
        amount_metric = _proxy("not_applicable")
    elif amount_digits in payload or amount_digits in amount_out:
        amount_metric = _proxy("pass")
    else:
        amount_metric = _proxy("fail", failure_class="deleted_decisive_fact")

    present = [marker for marker in NEGATION_MARKERS if marker in source]
    if not present:
        negation = _proxy("not_applicable")
    elif not payload:
        negation = _proxy("fail", failure_class="negation_lost")
    elif any(marker in payload for marker in present):
        negation = _proxy("pass")
    else:
        negation = _proxy("fail", failure_class="negation_lost")

    extra = set(_NUM_SPAN.findall(_TOKEN_SPAN.sub("", payload))) - set(_NUM_SPAN.findall(source))
    unsupported = _proxy("fail", failure_class="unsupported_number") if extra else _proxy("pass")

    return {
        "subject_attribution": subject,
        "evidence_attribution": evidence_metric,
        "date_relation": date_metric,
        "amount_relation": amount_metric,
        "unsupported_statements": unsupported,
        "negation_loss": negation,
    }


def score_identity_ranks(artifacts: dict, labels: dict | None, k: int = COMPARABLE_IDENTITY_K) -> dict:
    expected = (labels or {}).get("identity")
    ranking = [str(item) for item in (artifacts.get("ranking") or [])]
    if not expected:
        return {
            "outcome": "not_scored",
            "detail": "无独立身份真值，不记 top-1/top-k",
            "top1": _proxy("not_applicable"),
            "topk": {**_proxy("not_applicable"), "k": k},
        }
    if not ranking:
        empty = _proxy("fail", failure_class="attacker_no_candidates")
        return {"outcome": "measured", "top1": empty, "topk": {**empty, "k": k}}
    top1_hit = ranking[0] == expected
    topk_hit = expected in ranking[:k]
    if top1_hit:
        top1 = _proxy("pass")
    elif expected in ranking:
        top1 = _proxy("fail", failure_class="truth_not_in_top1")
    else:
        top1 = _proxy("fail", failure_class="truth_not_in_ranking")
    if topk_hit:
        topk = {**_proxy("pass"), "k": k}
    else:
        topk = {**_proxy("fail", failure_class="truth_not_in_ranking"), "k": k}
    return {"outcome": "measured", "top1": top1, "topk": topk}


def isolated_identity_probe(disclosed_text: str, auxiliary: list[dict], labels: dict | None,
                            *, query_budget: int = COMPARABLE_QUERY_BUDGET) -> dict:
    from .attacks import EXECUTOR_VERSION, SCORER_VERSION, assert_isolated_payload, propose, score

    protocol = {**COMPARABLE_IDENTITY_PROTOCOL, "query_budget": query_budget}
    request = {"facts": [{"id": "disclosed", "text": disclosed_text}]}
    view = {"request": request, "history": [], "auxiliary": auxiliary}
    assert_isolated_payload(view)
    if isinstance(labels, dict) and ("truth" in labels or "mapping" in labels):
        raise ValueError("评分标签含禁止字段")
    artifacts = propose(protocol, request, [], auxiliary)
    ranks = score_identity_ranks(artifacts, labels, k=protocol["k"])
    judged = score(protocol, artifacts, labels)
    return {
        "attacker_view_hash": digest(view),
        "ranking": artifacts.get("ranking") or [],
        "ranking_size": len(artifacts.get("ranking") or []),
        "process": artifacts.get("process") or [],
        "ranks": ranks,
        "protocol_outcome": judged.get("outcome"),
        "executor_version": EXECUTOR_VERSION,
        "scorer_version": SCORER_VERSION,
        "query_budget": query_budget,
        "attempt_count": 1,
        "isolation": {
            "attacker_received_labels": False,
            "scorer_received_labels": bool((labels or {}).get("identity")),
            "public_search": False,
        },
    }


def _merge_classes(rows: list[dict], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        item = row.get(field) or {}
        if item.get("outcome") == "not_applicable":
            counts["not_applicable"] = counts.get("not_applicable", 0) + 1
        elif item.get("failure_class"):
            name = item["failure_class"]
            counts[name] = counts.get(name, 0) + 1
    return counts


def _sum_ratio(rows: list[dict], field: str) -> dict:
    measured = [row[field] for row in rows if (row.get(field) or {}).get("outcome") == "measured"]
    numerator = sum(int(item.get("numerator") or 0) for item in measured)
    denominator = sum(int(item.get("denominator") or 0) for item in measured)
    if not denominator:
        return {"outcome": "not_applicable", "numerator": 0, "denominator": 0, "failure_classes": _merge_classes(rows, field)}
    return {
        "outcome": "measured",
        "numerator": numerator,
        "denominator": denominator,
        "failure_classes": _merge_classes(rows, field),
    }


def aggregate_comparable_rows(rows: list[dict]) -> dict:
    if not rows:
        return {"outcome": "not_applicable", "case_count": 0}
    identity_top1 = _sum_ratio(rows, "identity_top1")
    identity_topk = _sum_ratio(rows, "identity_topk")
    return {
        "outcome": "measured_on_synthetic_smoke",
        "case_count": len(rows),
        "identity_top1": identity_top1,
        "identity_topk": identity_topk,
        "subject_attribution": _sum_ratio(rows, "subject_attribution"),
        "evidence_attribution": _sum_ratio(rows, "evidence_attribution"),
        "date_relation": _sum_ratio(rows, "date_relation"),
        "amount_relation": _sum_ratio(rows, "amount_relation"),
        "unsupported_statements": _sum_ratio(rows, "unsupported_statements"),
        "negation_loss": _sum_ratio(rows, "negation_loss"),
        "engineering": {
            "outcome": "measured",
            "latency_ms_total": sum(int(row.get("latency_ms") or 0) for row in rows),
            "attempt_count_total": sum(int(row.get("attempt_count") or 0) for row in rows),
            "attempt_count_mean": sum(int(row.get("attempt_count") or 0) for row in rows) / len(rows),
        },
        "human_cost": UNSCORED_COMPARABLE["human_cost"],
    }


def assert_honest_comparable_report(report: dict) -> None:
    if report.get("production_dispatch") is not False:
        raise ValueError("对照报告不得打开正式外发")
    if report.get("winner") or report.get("best_method") or report.get("method_ranking"):
        raise ValueError("对照报告不得宣布方法胜出")
    for key, expected in (
        ("legal_availability", "not_scored"),
        ("privacy_reduction_rate", "not_scored"),
        ("aura", "not_applicable"),
        ("human_cost", "not_applicable"),
        ("interval_estimate", "not_applicable"),
    ):
        if (report.get(key) or {}).get("outcome") != expected:
            raise ValueError(f"{key} 必须为 {expected}")
    for key in ("legal_availability_score", "privacy_reduction", "aura_score", "aura_auc"):
        if key in report:
            raise ValueError(f"禁止写入伪造指标 {key}")
