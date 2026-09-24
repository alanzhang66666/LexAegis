"""V2.2 Domain package SPI (P5): the only sanctioned consumption surface.

Packages are declarative data — the SPI exposes typed, read-only views over a
package record's content. Kernel code must never hand a package credentials,
raw sockets, G10 material, or another case's data; this module has no such
parameters to pass.
"""
from types import MappingProxyType
from typing import Any, Protocol


class FactReader(Protocol):
    def fact_fields(self) -> list[str]: ...
    def task_field_matrix(self) -> list[dict[str, Any]]: ...


class RuleEvaluator(Protocol):
    def rules(self) -> list[dict[str, Any]]: ...
    def legal_sources(self) -> list[dict[str, Any]]: ...
    def immutable_relations(self) -> list[dict[str, Any]]: ...


class ContextBuilder(Protocol):
    def direct_identifier_patterns(self) -> list[str]: ...
    def forbidden_terms(self) -> list[str]: ...


class ReviewSchemaProvider(Protocol):
    def manual_review_conditions(self) -> list[dict[str, Any]]: ...
    def sensitive_object_rules(self) -> list[dict[str, Any]]: ...
    def not_hard_ban_categories(self) -> list[str]: ...
    def conflict_checklist(self) -> list[dict[str, Any]]: ...


class ArtifactBuilder(Protocol):
    def reply_templates(self) -> list[Any]: ...


class GateProfileReader(Protocol):
    def risk_weights(self) -> dict[str, Any]: ...


class AcceptanceSuiteReader(Protocol):
    def synthetic_cases(self) -> list[dict[str, Any]]: ...


class CapabilityBindingReader(Protocol):
    def binding_id(self) -> str | None: ...
    def task_type(self) -> str | None: ...
    def capability_id(self) -> str | None: ...
    def execution(self) -> str | None: ...
    def task_definition_version(self) -> str | None: ...
    def provider_profile(self) -> str | None: ...
    def risk_protocols(self) -> list[dict[str, Any]]: ...


class DomainPackageSPI:
    """Read-only adapter over a domain_package record.

    ``content`` is exposed through an immutable mapping proxy; nested
    structure is returned as-is (callers treat it as read-only — mutation
    would corrupt the content hash anyway).
    """

    def __init__(self, package: dict[str, Any]):
        self._package = package
        self._content = MappingProxyType(dict(package.get("content") or {}))

    @property
    def id(self) -> str:
        return self._package["id"]

    @property
    def package_type(self) -> str:
        return self._package.get("package_type") or ""

    @property
    def content_hash(self) -> str:
        return self._package.get("content_hash") or ""

    @property
    def content(self) -> MappingProxyType:
        return self._content

    # -- cause_pack ---------------------------------------------------------
    def fact_fields(self) -> list[str]:
        return list(self._content.get("fact_schema") or [])

    def task_field_matrix(self) -> list[dict[str, Any]]:
        return list(self._content.get("task_templates") or [])

    # -- cause_pack / legal_rule_pack ---------------------------------------
    def rules(self) -> list[dict[str, Any]]:
        return list(self._content.get("rules") or [])

    def references(self) -> list[Any]:
        return list(self._content.get("references") or [])

    def legal_sources(self) -> list[dict[str, Any]]:
        return list(self._content.get("sources") or [])

    def mapper(self) -> dict[str, Any]:
        """Declarative return-pipeline mapper config (cause_pack)."""
        return dict(self._content.get("mapper") or {})

    def immutable_relations(self) -> list[dict[str, Any]]:
        return list(self._content.get("immutable_relations") or [])

    # -- minimization_profile -----------------------------------------------
    def direct_identifier_patterns(self) -> list[str]:
        return list(self._content.get("direct_identifier_patterns") or [])

    def forbidden_terms(self) -> list[str]:
        return list(self._content.get("forbidden_terms") or [])

    # -- review_schema ------------------------------------------------------
    def manual_review_conditions(self) -> list[dict[str, Any]]:
        return list(self._content.get("manual_review_conditions") or [])

    def sensitive_object_rules(self) -> list[dict[str, Any]]:
        return list(self._content.get("sensitive_object_rules") or [])

    def not_hard_ban_categories(self) -> list[str]:
        return list(self._content.get("not_hard_ban_categories") or [])

    def conflict_checklist(self) -> list[dict[str, Any]]:
        return list(self._content.get("conflict_checklist") or [])

    # -- artifact_schema ----------------------------------------------------
    def reply_templates(self) -> list[Any]:
        return list(self._content.get("reply_templates") or [])

    # -- gate_profile -------------------------------------------------------
    def risk_weights(self) -> dict[str, Any]:
        return dict(self._content.get("risk_weights") or {})

    # -- domain_acceptance_suite --------------------------------------------
    def synthetic_cases(self) -> list[dict[str, Any]]:
        return list(self._content.get("synthetic_cases") or [])

    # -- capability_binding ---------------------------------------------------
    def binding_id(self) -> str | None:
        return self._content.get("binding_id")

    def task_type(self) -> str | None:
        return self._content.get("task_type")

    def capability_id(self) -> str | None:
        return self._content.get("capability_id")

    def execution(self) -> str | None:
        return self._content.get("execution")

    def task_definition_version(self) -> str | None:
        return self._content.get("task_definition_version")

    def provider_profile(self) -> str | None:
        return self._content.get("provider_profile")

    def risk_protocols(self) -> list[dict[str, Any]]:
        return list(self._content.get("risk_protocols") or [])


def spi_for(package: dict[str, Any]) -> DomainPackageSPI:
    """Attach the read-only SPI to a domain_package record."""
    if not package or package.get("package_type") not in {
        "cause_pack", "legal_rule_pack", "capability_binding",
        "review_schema", "artifact_schema", "minimization_profile",
        "gate_profile", "domain_acceptance_suite",
    }:
        raise ValueError("SPI 仅可附着于 domain_package 记录")
    return DomainPackageSPI(package)
