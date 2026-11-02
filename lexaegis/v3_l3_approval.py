"""Record two distinct L3 organization-role actions without granting release.

Assignments are read from the already signed gate profile, never from client
identity fields. The existing L3 block and all existing formal gates remain in
force because this layer does not validate PIA/CTIA or real organizational
credentials. HMAC protects local records; it is not proof of professional status.
"""
from datetime import datetime, timedelta, timezone
import hmac
import os
import re

from . import v3_grade_guard
from .util import audit, digest, sign, uid


KIND = "v3_l3_role_action"
ROLE_TO_ACCOUNT = {"legal_partner": "legal_reviewer", "data_protection_officer": "approver"}
USER_ID = re.compile(r"^user:[a-z][a-z0-9_.-]{2,31}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
DOMAIN = "lexaegis.v3.l3-role-action.v1"


def _assignments(config):
    mapping = config.get("l3_role_holders")
    if not isinstance(mapping, dict) or set(mapping) != set(ROLE_TO_ACCOUNT):
        raise ValueError("L3 组织角色签名配置缺失")
    result = {}
    for role, entries in mapping.items():
        if not isinstance(entries, list) or not 1 <= len(entries) <= 50:
            raise ValueError("L3 组织角色配置无效")
        users = {}
        for entry in entries:
            if (not isinstance(entry, dict) or set(entry) != {"user_id", "authority_hash"}
                    or not isinstance(entry["user_id"], str) or not USER_ID.fullmatch(entry["user_id"])
                    or not isinstance(entry["authority_hash"], str) or not SHA256.fullmatch(entry["authority_hash"])
                    or entry["user_id"] in users):
                raise ValueError("L3 组织角色配置无效")
            users[entry["user_id"]] = entry["authority_hash"]
        result[role] = users
    if set(result["legal_partner"]) & set(result["data_protection_officer"]):
        raise ValueError("L3 合伙人和数据保护负责人的账户须分离")
    return result


def _signature(row):
    key = os.getenv("LEX_PACKAGE_SIGNING_KEY", "")
    if len(key.encode("utf-8")) < 32:
        raise ValueError("L3 签名配置无效")
    content = {k:v for k,v in row.items() if k != "signature"}
    return sign({"domain": DOMAIN, "content": content}, key)


def _valid_action(repo, row, task, assessment, assignments, at):
    try:
        sig = row.get("signature")
        if not isinstance(sig, str) or not hmac.compare_digest(sig, _signature(row)):
            return False
        role = row["organization_role"]
        actor_id = row["actor_user_id"]
        user = repo.get(actor_id, "user")
        return bool(
            role in ROLE_TO_ACCOUNT and actor_id in assignments[role]
            and row.get("authority_hash") == assignments[role][actor_id]
            and user.get("status") == "active" and user.get("role") == ROLE_TO_ACCOUNT[role]
            and row.get("actor_state_hash") == v3_grade_guard._reviewer_state(user)
            and row.get("case_id") == task.get("case_id") and row.get("task_id") == task.get("id")
            and row.get("request_hash") == task.get("request_hash")
            and row.get("assessment_id") == assessment["id"]
            and row.get("assessment_hash") == digest(assessment)
            and row.get("profile_hash") == assessment["profile_hash"]
            and v3_grade_guard._instant(row.get("signed_at")) <= at
            < v3_grade_guard._instant(row.get("expires_at"))
            <= v3_grade_guard._instant(assessment["expires_at"])
        )
    except (KeyError, ValueError, TypeError):
        return False


def status(repo, task, case):
    """Revalidate both role records, but never assert L3 release readiness."""
    assessment, config = v3_grade_guard.validated_assessment(repo, task, case)
    if assessment.get("grade") != "L3":
        raise ValueError("仅 L3 请求需要双重组织角色记录")
    assignments = _assignments(config)
    stamp = datetime.now(timezone.utc)
    matches = {role: [] for role in ROLE_TO_ACCOUNT}
    for row in repo.list(KIND, case["id"]):
        if row.get("assessment_id") == assessment["id"] and _valid_action(repo,row,task,assessment,assignments,stamp):
            matches[row["organization_role"]].append(row)
    # Duplicate live approvals of a role are ambiguous and fail closed.
    present = {role: len(rows) == 1 for role, rows in matches.items()}
    distinct = (all(present.values()) and matches["legal_partner"][0]["actor_user_id"]
                != matches["data_protection_officer"][0]["actor_user_id"])
    return {"state": "roles_recorded" if distinct else "pending_roles",
            "legal_partner": present["legal_partner"],
            "data_protection_officer": present["data_protection_officer"],
            "distinct_accounts": bool(distinct), "authorized_to_send": False,
            "notice": "仅记录组织角色动作；L3 法域、PIA/CTIA 和原有门禁仍须核验。"}


def record(repo, task, case, *, organization_role, actor):
    """Persist a server-authenticated role action, bound to a current assessment."""
    if task.get("status") != "review":
        raise ValueError("仅待审批的当前请求可以记录 L3 角色动作")
    assessment, config = v3_grade_guard.validated_assessment(repo, task, case)
    if assessment.get("grade") != "L3" or organization_role not in ROLE_TO_ACCOUNT:
        raise ValueError("仅 L3 请求可以登记已知组织角色")
    assignments = _assignments(config)
    actor_id = actor.get("user_id") if isinstance(actor, dict) else None
    expected_role = ROLE_TO_ACCOUNT[organization_role]
    if not actor_id or actor.get("actor_role") != expected_role or actor_id not in assignments[organization_role]:
        raise ValueError("当前账户不在签名规则包的对应组织角色名单")
    try:
        user = repo.get(actor_id, "user")
    except KeyError as exc:
        raise ValueError("L3 账户不存在") from exc
    if user.get("status") != "active" or user.get("role") != expected_role:
        raise ValueError("L3 账户未启用或本地角色已变化")
    stamp = datetime.now(timezone.utc)
    current = []
    for old in repo.list(KIND, case["id"]):
        if old.get("assessment_id") == assessment["id"] and _valid_action(repo,old,task,assessment,assignments,stamp):
            current.append(old)
    for old in current:
        if old["organization_role"] == organization_role:
            if old["actor_user_id"] == actor_id:
                return old
            raise ValueError("当前组织角色已有有效确认")
        if old["actor_user_id"] == actor_id:
            raise ValueError("L3 两项组织角色须由不同账户确认")
    row = {"id":uid("v3l3"), "case_id":case["id"], "task_id":task["id"],
           "assessment_id":assessment["id"], "assessment_hash":digest(assessment),
           "request_hash":task["request_hash"], "profile_hash":assessment["profile_hash"],
           "organization_role":organization_role, "actor_user_id":actor_id,
           "actor_state_hash":v3_grade_guard._reviewer_state(user),
           "authority_hash":assignments[organization_role][actor_id], "signed_at":stamp.isoformat(),
           "expires_at":min(stamp+timedelta(minutes=30),v3_grade_guard._instant(assessment["expires_at"])).isoformat()}
    row["signature"] = _signature(row)
    repo.put(KIND,row,case["id"])
    task["product_release"] = {"state":"blocked","reason":"已记录角色动作，请重新检查 L3 法学准入。"}
    repo.put("task",task,case["id"])
    audit(repo,case["id"],"v3.l3_role_action",task_id=task["id"],request_hash=task["request_hash"],
          assessment_id=assessment["id"],organization_role=organization_role,actor_user_id=actor_id,
          authority_hash=row["authority_hash"])
    return row
