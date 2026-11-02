"""Opt-in, request-bound V3 legal-grade guard; it never grants dispatch.

A named legal reviewer may bind a grade to an existing allow-processing review
and a signed, currently published gate profile. Existing gates and grants remain
mandatory. Unsupported levels fail closed; particularly, generic local account
roles must not be misrepresented as partner/DPO authority for L3.
"""
from datetime import datetime, timedelta, timezone
import hmac
import os

from . import domain_packages
from .util import audit, digest, sign, uid


KIND = "v3_grade_assessment"
GRADES = frozenset({"L0", "L1", "L2", "L3", "L4", "UNKNOWN"})


def required(task):
    flag = os.getenv("LEX_V3_GRADE_GUARD", "").strip()
    if flag not in {"", "0", "1"}:
        raise ValueError("LEX_V3_GRADE_GUARD 只能为 0 或 1")
    return flag == "1" or bool(task.get("v3_grade_assessment_id"))


def _instant(value):
    if not isinstance(value, str):
        raise ValueError("V3 审批配置缺少有效期")
    try:
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError
        return value.astimezone(timezone.utc)
    except ValueError as exc:
        raise ValueError("V3 审批配置时间须含时区") from exc


def _current_request(task, case):
    request = task.get("request")
    if (not isinstance(request, dict) or not task.get("request_hash")
            or digest(request) != task.get("request_hash")
            or request.get("task_id") != task.get("id")
            or request.get("case_id") != case.get("id")
            or request.get("mode") != "formal" or request.get("transport") != "cloud"
            or task.get("transport") != "cloud" or task.get("stale")
            or task.get("case_revision") != case.get("revision")):
        raise ValueError("V3 等级须绑定当前正式云端请求及材料版本")


def _profile(repo, task, profile_id, at):
    try:
        profile = repo.get(profile_id, "domain_package")
        snapshot = repo.get(task.get("domain_runtime_snapshot_id") or "", "domain_runtime_snapshot")
    except KeyError as exc:
        raise ValueError("V3 等级规则或任务快照不存在") from exc
    expected = domain_packages._package_content_hash(profile)
    key = os.getenv("LEX_PACKAGE_SIGNING_KEY", "")
    if (len(key.encode("utf-8")) < 32 or profile.get("package_type") != "gate_profile" or profile.get("status") != "published"
            or profile.get("content_hash") != expected or not domain_packages.verify_signature(profile, key)
            or snapshot.get("gate_profile_hash") != expected
            or snapshot.get("pack_id") != task.get("pack_id")):
        raise ValueError("V3 等级规则包未发布、签名无效或与任务快照不匹配")
    if not _instant(profile.get("effective_from")) <= at < _instant(profile.get("effective_to")):
        raise ValueError("V3 等级规则包尚未生效或已过期")
    config = (profile.get("content") or {}).get("v3_grade_policy")
    if (not isinstance(config, dict) or type(config.get("version")) is not int or config.get("version") != 1
            or not isinstance(config.get("permitted_grades"), list)
            or not config["permitted_grades"]
            or any(not isinstance(item, str) for item in config["permitted_grades"])
            or len(set(config["permitted_grades"])) != len(config["permitted_grades"])
            or not set(config["permitted_grades"]) <= GRADES):
        raise ValueError("V3 等级规则配置缺失或无效")
    return profile, config, snapshot


def _risk_floor(task, grade):
    # The existing deterministic disposition can only increase the grade;
    # a human declaration must never turn an already prohibited or unknown
    # request into a lower-risk one. This does not classify legal risk.
    risk = task.get("risk") or {}
    disposition = risk.get("disposition")
    allowed = {
        "allowed": GRADES,
        "needs_minimization": {"L2", "L3", "L4", "UNKNOWN"},
        "needs_verification": {"L3", "L4", "UNKNOWN"},
        "prohibited": {"L4", "UNKNOWN"},
    }
    if disposition not in allowed or grade not in allowed[disposition]:
        raise ValueError("当前风险状态缺失或不允许降低 V3 等级")


def _verify_assessment_signature(assessment):
    key = os.getenv("LEX_PACKAGE_SIGNING_KEY", "")
    signature = assessment.get("signature")
    content = {k: v for k, v in assessment.items() if k != "signature"}
    if (len(key.encode("utf-8")) < 32 or not isinstance(signature, str)
            or not hmac.compare_digest(signature, sign({"domain": "lexaegis.v3.grade.v1", "content": content}, key))):
        raise ValueError("V3 等级评估签名无效")


def resolve_references(repo, task, *, profile_id=None, legal_review_id=None):
    """Resolve omitted IDs from persisted task state; never trust a client projection."""
    if not profile_id:
        try:
            snapshot = repo.get(task.get("domain_runtime_snapshot_id") or "", "domain_runtime_snapshot")
        except KeyError as exc:
            raise ValueError("当前任务缺少领域快照") from exc
        matches = [item for item in repo.list("domain_package")
                   if item.get("package_type") == "gate_profile" and item.get("status") == "published"
                   and item.get("content_hash") == snapshot.get("gate_profile_hash")]
        if len(matches) != 1:
            raise ValueError("当前领域快照未匹配唯一已发布的等级规则包")
        profile_id = matches[0]["id"]
    if not legal_review_id:
        legal_review_id = (task.get("legal_review") or {}).get("id")
        if not legal_review_id:
            raise ValueError("当前请求缺少法学复核记录")
    return profile_id, legal_review_id


def _review(repo, task, case, review_id):
    try:
        review = repo.get(review_id, "legal_review_record")
    except KeyError as exc:
        raise ValueError("V3 等级关联的法学复核不存在") from exc
    if (review.get("task_id") != task.get("id") or review.get("case_id") != case.get("id")
            or review.get("request_hash") != task.get("request_hash")
            or review.get("material_version") != case.get("revision")
            or review.get("conclusion") != "allow_processing"
            or review.get("reviewer_role") != "legal_reviewer"
            or not review.get("reviewer_user_id") or not review.get("legal_source_ids")
            or not review.get("reviewed_condition_ids") or not review.get("evidence_ids")
            or task.get("review_status") != "cleared"):
        raise ValueError("V3 等级须绑定当前具名法学通过记录")
    try:
        reviewer = repo.get(review["reviewer_user_id"], "user")
    except KeyError as exc:
        raise ValueError("法学复核账户不存在") from exc
    if reviewer.get("status") != "active" or reviewer.get("role") != "legal_reviewer":
        raise ValueError("法学复核账户已停用或角色已变化")
    return review, reviewer


def _reviewer_state(reviewer):
    return digest({key: reviewer.get(key) for key in ("id", "role", "status", "auth_version", "updated_at")})


def record(repo, task, case, *, grade, profile_id, legal_review_id, actor):
    """Persist one immutable supplemental grade after authenticated legal review."""
    if task.get("status") != "review":
        raise ValueError("只有待审批请求可以登记 V3 等级")
    _current_request(task, case)
    if grade not in GRADES:
        raise ValueError("未知 V3 等级")
    at = datetime.now(timezone.utc)
    _risk_floor(task, grade)
    profile, config, snapshot = _profile(repo, task, profile_id, at)
    review, reviewer = _review(repo, task, case, legal_review_id)
    actor_id = actor.get("user_id") if isinstance(actor, dict) else None
    if (not actor_id or actor.get("actor_role") != "legal_reviewer"
            or review.get("reviewer_user_id") != actor_id):
        raise ValueError("只有当前法学结论的具名复核人可以登记等级")
    if grade not in config["permitted_grades"]:
        raise ValueError("当前签名规则不允许登记该等级")
    existing_id = task.get("v3_grade_assessment_id")
    if existing_id:
        try:
            existing = repo.get(existing_id, KIND)
        except KeyError as exc:
            raise ValueError("V3 等级评估记录不存在") from exc
        _verify_assessment_signature(existing)
        if (existing.get("grade") == grade and existing.get("request_hash") == task["request_hash"]
                and existing.get("profile_id") == profile_id and existing.get("legal_review_id") == legal_review_id
                and existing.get("reviewer_user_id") == actor_id
                and existing.get("profile_hash") == profile["content_hash"]
                and existing.get("snapshot_hash") == digest(snapshot)
                and existing.get("review_hash") == digest(review)
                and existing.get("reviewer_state_hash") == _reviewer_state(reviewer)):
            if not _instant(existing.get("assessed_at")) <= at < _instant(existing.get("expires_at")):
                raise ValueError("V3 等级评估已过期，请重新生成请求")
            return existing
        if (existing.get("task_id") != task["id"] or existing.get("case_id") != case["id"]
                or existing.get("request_hash") == task["request_hash"]):
            raise ValueError("当前请求的 V3 等级已冻结；修改须重新生成请求")
    expiry = min(at + timedelta(minutes=30), _instant(profile["effective_to"]))
    row = {"id": uid("v3grade"), "task_id": task["id"], "case_id": case["id"],
           "request_hash": task["request_hash"], "grade": grade, "profile_id": profile_id,
           "profile_hash": profile["content_hash"], "legal_review_id": legal_review_id,
           "review_hash": digest(review), "snapshot_hash": digest(snapshot),
           "reviewer_state_hash": _reviewer_state(reviewer),
           "reviewer_user_id": actor_id, "assessed_at": at.isoformat(), "expires_at": expiry.isoformat()}
    row["signature"] = sign({"domain": "lexaegis.v3.grade.v1", "content": row}, os.environ["LEX_PACKAGE_SIGNING_KEY"])
    repo.put(KIND, row, case["id"])
    task["v3_grade_assessment_id"] = row["id"]
    task["v3_grade_assessment_request_hash"] = row["request_hash"]
    task["product_release"] = {"state": "blocked", "reason": "等级已登记，请重新检查正式门禁。"}
    repo.put("task", task, case["id"])
    audit(repo, case["id"], "v3.grade_assessed", task_id=task["id"],
          request_hash=task["request_hash"], grade=grade, reviewer_user_id=actor_id,
          profile_hash=profile["content_hash"], assessment_id=row["id"])
    return row


def validated_assessment(repo, task, case):
    """Revalidate a persisted assessment and its signed policy dependencies."""
    _current_request(task, case)
    ident = task.get("v3_grade_assessment_id")
    if not ident:
        raise ValueError("V3 等级评估缺失，禁止审批和发送")
    try:
        assessment = repo.get(ident, KIND)
    except KeyError as exc:
        raise ValueError("V3 等级评估记录不存在") from exc
    _verify_assessment_signature(assessment)
    if (assessment.get("task_id") != task.get("id") or assessment.get("case_id") != case.get("id")
            or assessment.get("request_hash") != task.get("request_hash")):
        raise ValueError("V3 等级评估不匹配当前请求")
    at = datetime.now(timezone.utc)
    profile, config, snapshot = _profile(repo, task, assessment.get("profile_id"), at)
    review, reviewer = _review(repo, task, case, assessment.get("legal_review_id"))
    grade = assessment.get("grade")
    _risk_floor(task, grade)
    if not _instant(assessment.get("assessed_at")) <= at < _instant(assessment.get("expires_at")) <= _instant(profile["effective_to"]):
        raise ValueError("V3 等级评估已过期或有效期无效")
    if (assessment.get("profile_hash") != profile.get("content_hash") or grade not in config["permitted_grades"]
            or assessment.get("snapshot_hash") != digest(snapshot) or assessment.get("review_hash") != digest(review)
            or assessment.get("reviewer_state_hash") != _reviewer_state(reviewer)
            or review.get("reviewer_user_id") != assessment.get("reviewer_user_id")):
        raise ValueError("V3 等级评估依赖已变化")
    return assessment, config


def require_current(repo, task, case):
    """Enforce an extra gate; never replaces G0-G10 or an authorized grant."""
    assessment, _config = validated_assessment(repo, task, case)
    grade = assessment.get("grade")
    if grade in {"L4", "UNKNOWN"}:
        raise ValueError("V3 L4 或未知等级禁止外发")
    if grade == "L3":
        raise ValueError("V3 L3 尚缺组织角色双重授权，禁止外发")
    if grade == "L0":
        raise ValueError("V3 L0 尚缺公开内容证明，禁止自动外发")
    if grade not in {"L1", "L2"}:
        raise ValueError("未知 V3 等级，禁止外发")
    return assessment
