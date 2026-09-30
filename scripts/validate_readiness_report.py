#!/usr/bin/env python3
"""Validate readiness and raw engineering evidence without network access."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import ValidationError

from lexaegis.contracts import ReadinessReport


RAW_REQUIRED = {
    "schema_version", "check_id", "status", "source_commit", "image_digests",
    "source_kind", "source_command", "environment", "generated_at", "valid_until",
    "redaction_profile", "results",
}
RAW_CHECKS = {"compose_isolation", "k8s_conformance", "host_firewall", "supply_chain"}


def validate(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "mode" in payload and "checks" in payload:
        ReadinessReport.model_validate(payload)
        return
    if not isinstance(payload, dict) or not RAW_REQUIRED <= set(payload):
        raise ValueError("missing raw engineering evidence fields")
    if payload["schema_version"] != 1 or payload["check_id"] not in RAW_CHECKS:
        raise ValueError("unsupported raw engineering evidence kind")
    if payload["status"] not in {"pass", "fail"}:
        raise ValueError("raw evidence status must be pass or fail")
    if not re.fullmatch(r"[0-9a-f]{40}", payload["source_commit"]):
        raise ValueError("raw evidence source_commit must be a git sha")
    if payload["source_kind"] not in {"manual_upload", "command_generated"}:
        raise ValueError("invalid evidence source_kind")
    if not isinstance(payload["image_digests"], dict) or not all(
        isinstance(k, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", v)
        for k, v in payload["image_digests"].items()
    ):
        raise ValueError("image_digests must use immutable sha256 references")
    if not isinstance(payload["results"], dict):
        raise ValueError("raw evidence results must be an object")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    try:
        validate(args.path)
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        print(f"invalid readiness report: {exc}")
        return 1
    print(f"valid readiness report: {args.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
