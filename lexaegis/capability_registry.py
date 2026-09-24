"""V2.2 Capability Registry + CapabilityBinding resolution (P5).

Capabilities are registered from task_engine definitions (built-in or
entrypoint-loaded). A CapabilityBinding domain_package binds
cause_id + task_type -> capability (+ optional minimization/provider refs).
Calls without a registered, available capability are rejected.
"""
from .contracts import Capability
from .util import now


class CapabilityError(ValueError):
    """Fail-closed capability resolution error."""


CAPABILITY_KIND = "capability"


def capability_for(repo, capability_id):
    for record in repo.list(CAPABILITY_KIND):
        if record.get("capability_id") == capability_id:
            return record
    return None


def capability_for_task(repo, task_type):
    for record in repo.list(CAPABILITY_KIND):
        if record.get("task_type") == task_type:
            return record
    return None


def ensure_registered(repo, task_type, registered_by="system"):
    """Register the task_engine definition of ``task_type`` as a capability
    record. Idempotent; entrypoint-loaded task types are registered on first
    use, which is what the registry is for."""
    existing = capability_for_task(repo, task_type)
    if existing:
        return existing
    from .task_engine import registered_tasks
    definition = registered_tasks().get(task_type)
    if not definition:
        return None
    record = Capability(
        id=f"cap:{task_type}",
        capability_id=f"R_{task_type}",
        task_type=task_type,
        api_version=str(definition.get("version") or "1.0"),
        name=definition.get("name") or task_type,
        execution_type=definition.get("execution_type") or "",
        transports=list(definition.get("transports") or []),
        input_schema=dict(definition.get("input_schema") or {}),
        output_schema=dict(definition.get("output_schema") or {}),
        privacy_contract=dict(definition.get("privacy_contract") or {}),
        status="available" if definition.get("status") == "available" else "disabled",
        registered_by=registered_by,
        created_at=now(),
    ).model_dump()
    repo.put(CAPABILITY_KIND, record)
    return record


def seed_capabilities(repo):
    """Register every available task_engine definition. Idempotent."""
    from .task_engine import registered_tasks
    seeded = 0
    for task_type, definition in registered_tasks().items():
        if capability_for_task(repo, task_type):
            continue
        record = Capability(
            id=f"cap:{task_type}",
            capability_id=f"R_{task_type}",
            task_type=task_type,
            api_version=str(definition.get("version") or "1.0"),
            name=definition.get("name") or task_type,
            execution_type=definition.get("execution_type") or "",
            transports=list(definition.get("transports") or []),
            input_schema=dict(definition.get("input_schema") or {}),
            output_schema=dict(definition.get("output_schema") or {}),
            privacy_contract=dict(definition.get("privacy_contract") or {}),
            status="available" if definition.get("status") == "available" else "disabled",
            registered_by="seed",
            created_at=now(),
        ).model_dump()
        repo.put(CAPABILITY_KIND, record)
        seeded += 1
    return seeded


def assert_capability(repo, task_type, binding=None):
    """The capability must be registered and available; when a binding is
    supplied its capability_id must match a registered capability and any
    declared provider_profile_ref must resolve to a real provider record."""
    capability = ensure_registered(repo, task_type)
    if not capability:
        raise CapabilityError(f"能力 R_{task_type} 未注册")
    if capability.get("status") != "available":
        raise CapabilityError(f"能力 R_{task_type} 已禁用")
    if binding:
        content = (binding or {}).get("content") or {}
        bound_task = content.get("task_type")
        if bound_task and bound_task != task_type:
            raise CapabilityError(
                f"绑定任务类型 {bound_task} 与请求任务类型 {task_type} 不一致")
        bound_capability = content.get("capability_id")
        if bound_capability and bound_capability != capability["capability_id"]:
            raise CapabilityError(
                f"绑定指向能力 {bound_capability}，与注册能力 "
                f"{capability['capability_id']} 不一致")
        provider_ref = content.get("provider_profile")
        if provider_ref:
            try:
                repo.get(provider_ref, "provider")
            except KeyError:
                raise CapabilityError(
                    f"绑定引用的服务商档案不存在: {provider_ref}")
    return capability
