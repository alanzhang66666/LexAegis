"""V2.2 P8: DomainAcceptanceSuite runner — package-level baselines."""
from lexaegis import acceptance_suite
from lexaegis.domain_packages import _package_content_hash


def test_suite_passes_on_seeded_labor(env):
    with env["app"].state.store.read() as repo:
        report = acceptance_suite.run_suite(repo, "labor")
    assert report["asserted_failed"] == []
    # every ASSERTED baseline ran and passed
    kinds = {r["id"]: r["kind"] for r in report["results"]}
    asserted = [r for r in report["results"] if r["kind"] == "package_asserted"]
    assert len(asserted) == 10
    assert all(r["status"] == "passed" for r in asserted)
    # non-asserted baselines are never silently marked passed
    assert "g10_real_send" in report["manual_gate"]
    for mapped in report["test_mapped"]:
        entry = next(r for r in report["results"] if r["id"] == mapped)
        assert entry["covered_by"]


def test_suite_fails_closed_on_package_drift(env):
    with env["app"].state.store.transaction() as repo:
        package = next(
            p for p in repo.list("domain_package")
            if p["package_type"] == "gate_profile" and p["cause_id"] == "labor")
        package = dict(package)
        package["content"] = {k: v for k, v in package["content"].items()
                              if k != "risk_weights"}
        package["content_hash"] = _package_content_hash(package)
        repo.put("domain_package", package)
    with env["app"].state.store.read() as repo:
        report = acceptance_suite.run_suite(repo, "labor")
    assert "gate_profile" in report["asserted_failed"]
    # drifted content vs manifest ref must also surface
    assert "manifest_integrity" in report["asserted_failed"]


def test_suite_unknown_cause_reports_failures_not_crash(env):
    with env["app"].state.store.read() as repo:
        report = acceptance_suite.run_suite(repo, "no_such_cause")
    assert report["asserted"] == 0
    assert report["asserted_failed"]
