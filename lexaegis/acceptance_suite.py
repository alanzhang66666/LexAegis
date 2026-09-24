"""V2.2 P8 DomainAcceptanceSuite runner.

Executes the package-level baselines of a cause's acceptance suite against
stored domain_package / manifest records. Baselines that require live
workflow evidence (G-gates, send/recover, disconnect drills) are reported as
``test_mapped`` or ``manual_gate`` — they are covered by the pytest suite or
by human acceptance, and are NEVER silently marked passed here.

CLI: ``python -m lexaegis.acceptance_suite --data <app data dir> --cause labor``
"""
import argparse
import re
import sys

from .contracts import PLATFORM_API_VERSION
from .domain_packages import _manifest_content_hash, _package_content_hash
from .spi import spi_for

ASSERTED = "package_asserted"      # executed here, pass/fail
TEST_MAPPED = "test_mapped"        # covered by the pytest suite
MANUAL_GATE = "manual_gate"        # requires human/real-environment evidence

# The 18 V2.2 baselines. Only entries marked ASSERTED run in this module.
BASELINES = [
    {"id": "cause_pack_schema", "name": "CausePack 结构校验", "kind": ASSERTED},
    {"id": "legal_rule_sources", "name": "法源版本与生效期", "kind": ASSERTED},
    {"id": "binding_compat", "name": "能力绑定兼容", "kind": ASSERTED},
    {"id": "minimization_profile", "name": "最小化画像完整", "kind": ASSERTED},
    {"id": "gate_profile", "name": "门禁画像完整", "kind": ASSERTED},
    {"id": "package_hash_stable", "name": "包内容哈希稳定", "kind": ASSERTED},
    {"id": "manifest_integrity", "name": "manifest 引用与哈希一致", "kind": ASSERTED},
    {"id": "platform_api_match", "name": "platform_api 与内核匹配", "kind": ASSERTED},
    {"id": "provenance_chain", "name": "provenance 链完整", "kind": ASSERTED},
    {"id": "acceptance_fixtures", "name": "套件自带 fixture", "kind": ASSERTED},
    {"id": "leakage_and_gates", "name": "泄漏检查与 G0–G10 唯一 gate",
     "kind": TEST_MAPPED, "covered_by": "tests/test_outbound_gate.py, tests/test_gateway*.py"},
    {"id": "request_hash_stable", "name": "request_hash 稳定",
     "kind": TEST_MAPPED, "covered_by": "tests/test_domain_runtime.py"},
    {"id": "wrong_source_ids_blocked", "name": "错 source_ids 阻断",
     "kind": TEST_MAPPED, "covered_by": "tests/test_workflow.py"},
    {"id": "return_relink", "name": "回流重链（锚点/身份）",
     "kind": TEST_MAPPED, "covered_by": "tests/test_return_pipeline.py"},
    {"id": "human_three_branches", "name": "人审三分支",
     "kind": TEST_MAPPED, "covered_by": "tests/test_workflow.py, tests/test_review_races.py"},
    {"id": "context_supersede", "name": "ContextVersion 失效与非静默升级",
     "kind": TEST_MAPPED, "covered_by": "tests/test_domain_runtime.py"},
    {"id": "disconnect_autonomy", "name": "断连自治 waiting-cloud",
     "kind": TEST_MAPPED, "covered_by": "tests/test_return_pipeline.py"},
    {"id": "revocation_and_audit", "name": "撤包传播与审计完整",
     "kind": TEST_MAPPED, "covered_by": "tests/test_domain_packages.py"},
    {"id": "g10_real_send", "name": "G10 真实外发验收",
     "kind": MANUAL_GATE, "covered_by": "docs/DUAL_TRACK_ACCEPTANCE.md"},
]


def _check(condition, detail):
    return {"status": "passed" if condition else "failed", "detail": detail}


def _manifests_for(repo, cause_id):
    return [m for m in repo.list("domain_package_manifest")
            if m.get("cause_id") == cause_id]


def _packages_for(repo, cause_id):
    return [p for p in repo.list("domain_package")
            if p.get("cause_id") == cause_id]


def _resolve(repo, ref, manifest):
    package = repo.get(ref["id"], "domain_package")
    if package.get("content_hash") != ref.get("content_hash"):
        raise ValueError(f"包 {ref['id']} 内容哈希漂移")
    return package


def run_suite(repo, cause_id):
    """Execute package-level baselines. Returns a report dict; never raises
    on a failed check — failures are data."""
    results = []
    manifests = _manifests_for(repo, cause_id)
    packages = _packages_for(repo, cause_id)
    by_type = {}
    for package in packages:
        by_type.setdefault(package["package_type"], []).append(package)

    checks = {
        "cause_pack_schema": lambda: _check(
            bool(by_type.get("cause_pack"))
            and all(spi_for(p).fact_fields() and spi_for(p).task_field_matrix()
                    for p in by_type["cause_pack"]),
            f"cause_pack={len(by_type.get('cause_pack') or [])}"),
        "legal_rule_sources": lambda: _check(
            bool(by_type.get("legal_rule_pack"))
            and all(spi_for(p).legal_sources() for p in by_type["legal_rule_pack"]),
            f"legal_rule_pack={len(by_type.get('legal_rule_pack') or [])}"),
        "binding_compat": lambda: _binding_compat(repo, by_type),
        "minimization_profile": lambda: _check(
            bool(by_type.get("minimization_profile"))
            and all(
                "direct_identifier_patterns" in spi_for(p).content
                and "forbidden_terms" in spi_for(p).content
                and all(re.compile(pattern)
                        for pattern in spi_for(p).direct_identifier_patterns())
                for p in by_type["minimization_profile"]),
            f"minimization_profile={len(by_type.get('minimization_profile') or [])}"),
        "gate_profile": lambda: _check(
            bool(by_type.get("gate_profile"))
            and all("risk_weights" in spi_for(p).content
                    for p in by_type["gate_profile"]),
            f"gate_profile={len(by_type.get('gate_profile') or [])}"),
        "package_hash_stable": lambda: _check(
            bool(packages)
            and all(p.get("content_hash") == _package_content_hash(p) for p in packages),
            f"packages={len(packages)}"),
        "manifest_integrity": lambda: _manifest_integrity(repo, manifests),
        "platform_api_match": lambda: _check(
            bool(packages)
            and all(p.get("platform_api") == PLATFORM_API_VERSION for p in packages),
            f"kernel={PLATFORM_API_VERSION}"),
        "provenance_chain": lambda: _check(
            bool(packages)
            and all((p.get("provenance") or {}).get("source_pack_id") for p in packages),
            "全部包记录 source_pack_id"),
        "acceptance_fixtures": lambda: _check(
            bool(by_type.get("domain_acceptance_suite"))
            and any(spi_for(p).synthetic_cases() for p in by_type["domain_acceptance_suite"]),
            f"suite={len(by_type.get('domain_acceptance_suite') or [])}"),
    }

    for baseline in BASELINES:
        entry = {"id": baseline["id"], "name": baseline["name"],
                 "kind": baseline["kind"]}
        if baseline["kind"] == ASSERTED:
            try:
                entry.update(checks[baseline["id"]]())
            except Exception as error:
                entry.update(status="failed",
                             detail=f"{type(error).__name__}: {error}")
        else:
            entry.update(status=baseline["kind"],
                         covered_by=baseline.get("covered_by"))
        results.append(entry)

    return {
        "cause_id": cause_id,
        "asserted": sum(1 for r in results if r.get("status") == "passed"),
        "asserted_failed": [r["id"] for r in results if r.get("status") == "failed"],
        "test_mapped": [r["id"] for r in results if r.get("status") == TEST_MAPPED],
        "manual_gate": [r["id"] for r in results if r.get("status") == MANUAL_GATE],
        "results": results,
    }


def _binding_compat(repo, by_type):
    from . import capability_registry
    bindings = by_type.get("capability_binding") or []
    if not bindings:
        return _check(False, "无 capability_binding")
    missing = []
    for binding in bindings:
        spi = spi_for(binding)
        task_type = spi.task_type()
        capability = capability_registry.capability_for_task(repo, task_type) if task_type else None
        if not capability or capability.get("status") != "available":
            missing.append(task_type)
            continue
        if spi.capability_id() and spi.capability_id() != capability["capability_id"]:
            missing.append(f"{task_type}:capability_mismatch")
    return _check(not missing,
                  f"bindings={len(bindings)}" + (f" 未注册/不一致={missing}" if missing else ""))


def _manifest_integrity(repo, manifests):
    if not manifests:
        return _check(False, "无 manifest")
    problems = []
    for manifest in manifests:
        if manifest.get("content_hash") != _manifest_content_hash(manifest):
            problems.append(f"{manifest['id']}:manifest_hash")
            continue
        for refs in (manifest.get("package_refs") or {}).values():
            for ref in refs:
                try:
                    _resolve(repo, ref, manifest)
                except (KeyError, ValueError) as error:
                    problems.append(str(error)[:80])
    return _check(not problems,
                  f"manifests={len(manifests)}" + (f" 问题={problems}" if problems else ""))


def main(argv=None):
    parser = argparse.ArgumentParser(description="DomainAcceptanceSuite runner")
    parser.add_argument("--data", required=True, help="app data dir (contains app.sqlite)")
    parser.add_argument("--cause", default="labor")
    args = parser.parse_args(argv)
    from .storage import Store
    store = Store(f"{args.data}/app.sqlite")
    with store.read() as repo:
        report = run_suite(repo, args.cause)
    import json
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["asserted_failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
