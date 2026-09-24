"""V2.2 domain mapper: package-provided declarative mapping over the
validated cloud result in the return pipeline.

Packages are data, never code — a mapper is a declarative config living in
the ``cause_pack`` package content under ``mapper``. The kernel runs this
generic engine; the package supplies only the mapping table.

Config grammar (all keys optional, unknown keys are rejected):

- ``applies_to``: list of task types this mapper serves. Absent/empty means
  it applies to every task type.
- ``claim_list_key``: where the claim list lives inside a dict-shaped
  validated result (default ``"claims"``). A list-shaped result is treated
  as the claim list itself.
- ``field_map``: ``{source: target}`` — rename claim keys.
- ``value_map``: ``{field: {raw: canonical}}`` — normalize claim values.
- ``defaults``: ``{field: value}`` — set fields the claim does not carry.
- ``required_fields``: fields every mapped claim must still have —
  fail-closed assertion against pipeline/validator drift.

The mapper never touches source materials or identity mappings: it only
rewrites the candidate claim structures that the later identity/evidence
relink and human-decision stages still gate.
"""

MAPPER_KEYS = {
    "applies_to", "claim_list_key", "field_map", "value_map",
    "defaults", "required_fields",
}


class DomainMapperError(ValueError):
    """Fail-closed mapper error — surfaces as ``invalid_cloud_result``."""


def applies(config, task_type):
    wanted = config.get("applies_to") or []
    return not wanted or task_type in wanted


def apply_mapper(config, validated):
    """Execute the declarative mapping over ``validated`` in place.

    Returns ``{"mapped": int, "claims_key": key}`` or ``None`` when the
    result carries no claim list to map. Raises DomainMapperError on
    malformed config or a claim that violates the mapper contract."""
    unknown = set(config) - MAPPER_KEYS
    if unknown:
        raise DomainMapperError(f"mapper 配置含未知键: {sorted(unknown)}")
    claims_key = config.get("claim_list_key") or "claims"
    if isinstance(validated, list):
        claims = validated
    elif isinstance(validated, dict):
        claims = validated.get(claims_key)
    else:
        claims = None
    if claims is None:
        return None
    if not isinstance(claims, list):
        raise DomainMapperError(f"mapper 目标 {claims_key} 不是数组")
    field_map = config.get("field_map") or {}
    value_map = config.get("value_map") or {}
    defaults = config.get("defaults") or {}
    required = config.get("required_fields") or []
    for name, table in (("field_map", field_map), ("value_map", value_map),
                        ("defaults", defaults)):
        if not isinstance(table, dict):
            raise DomainMapperError(f"mapper.{name} 必须是对象")
    if not isinstance(required, list):
        raise DomainMapperError("mapper.required_fields 必须是数组")
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            raise DomainMapperError(f"mapper 目标第 {index} 项不是对象")
        for source, target in field_map.items():
            if source in claim:
                claim[target] = claim.pop(source)
        for field, table in value_map.items():
            if field in claim and claim[field] in table:
                claim[field] = table[claim[field]]
        for field, value in defaults.items():
            claim.setdefault(field, value)
        missing = [field for field in required if field not in claim]
        if missing:
            raise DomainMapperError(
                f"mapper 映射后第 {index} 项缺少必填字段: {missing}")
    return {"mapped": len(claims), "claims_key": claims_key}
