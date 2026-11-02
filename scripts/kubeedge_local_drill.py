#!/usr/bin/env python3
"""Synthetic kind/KubeEdge distribution drill with fail-closed evidence."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

CP = os.environ.get("LEX_KUBEEDGE_CONTROL_PLANE_URL", "http://127.0.0.1:18777").rstrip("/")
EDGE_CONTAINER = "edge-node-1"
EDGE_NODE = "edge-1"
EDGE_PY = "/opt/venv/bin/python"
WORK = Path(tempfile.gettempdir()) / "lex-edge-drill"
WORK.mkdir(exist_ok=True)
LOG: list[str] = []
_SENSITIVE = re.compile(r"(?i)(password|passwd|token|authorization|secret|request[_ -]?body|set-cookie)\s*[:=]\s*[^,\s}]+")
_ABSOLUTE_PATH = re.compile(r"(?<![A-Za-z0-9_])/(?:Users|home|private|tmp|var|opt|workspace)/[^\s,}]+")


def safe_text(value: object) -> str:
    text = _SENSITIVE.sub(lambda m: f"{m.group(1)}=<redacted>", str(value))
    return _ABSOLUTE_PATH.sub("<path>", text)[:240]


def log(step: str, detail: str = "") -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {step} :: {safe_text(detail)}"
    LOG.append(line)
    print(line)


def require_password() -> str:
    password = os.environ.get("LEX_KUBEEDGE_DRILL_PASSWORD", "")
    if not password:
        raise RuntimeError("LEX_KUBEEDGE_DRILL_PASSWORD is required")
    return password


def sh(cmd: list[str] | str, check: bool = True, timeout: int = 120) -> str:
    result = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f"command failed with exit {result.returncode}")
    return result.stdout.strip()


def edge_py(code: str) -> str:
    result = subprocess.run(["docker", "exec", "-i", EDGE_CONTAINER, EDGE_PY, "-c", code], capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError("edge process failed")
    return result.stdout.strip()


def source_commit(explicit: str | None) -> str:
    value = explicit or sh(["git", "rev-parse", "HEAD"])
    if not re.fullmatch(r"[0-9a-fA-F]{40}", value):
        raise RuntimeError("source commit must be a 40-character git sha")
    return value.lower()


def image_digests(explicit: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in explicit:
        if "=" not in item:
            raise RuntimeError("--image must use role=sha256:<digest>")
        role, digest = item.split("=", 1)
        if not role or not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
            raise RuntimeError("image digest must be sha256:<64 hex characters>")
        result[role] = digest.lower()
    if result:
        return result
    identity = sh(["docker", "inspect", "--format", "{{.Image}}", EDGE_CONTAINER], check=False)
    if re.fullmatch(r"sha256:[0-9a-fA-F]{64}", identity):
        return {"edge": identity.lower()}
    raise RuntimeError("image digest required via --image or a running edge container")


def build_report(args: argparse.Namespace, status: str, results: dict[str, bool], reason: str = "") -> dict[str, Any]:
    generated = datetime.now(timezone.utc).replace(microsecond=0)
    report: dict[str, Any] = {
        "schema_version": 1,
        "check_id": "k8s_conformance",
        "status": status,
        "source_commit": source_commit(args.source_commit),
        "image_digests": image_digests(args.image),
        "source_kind": "command_generated",
        "source_command": "python scripts/kubeedge_local_drill.py --report PATH --json-report PATH",
        "environment": {"cluster": "kind", "channel": "kubeedge", "synthetic_only": "true"},
        "generated_at": generated.isoformat().replace("+00:00", "Z"),
        "valid_until": (generated + timedelta(hours=24)).isoformat().replace("+00:00", "Z"),
        "redaction_profile": "synthetic-v1",
        "results": results,
    }
    if reason:
        report["results_reason"] = safe_text(reason)
    return report


def run(args: argparse.Namespace) -> dict[str, Any]:
    password = require_password()
    client = httpx.Client(base_url=CP, timeout=30)
    results = {key: False for key in ("registration", "delivery", "disconnect", "bundle_absent_while_disconnected", "reconnect", "bundle_synced", "revocation", "reconcile")}
    disconnected = False
    try:
        response = client.post("/api/v1/login", json={"password": password})
        response.raise_for_status()
        log("control-plane login", "ok")
        manifests = client.get("/api/v1/domain-package-manifests").json()
        m1 = next(item for item in manifests if item["id"] == "dpm:labor:2.0.0-draft.3")
        m2 = next(item for item in manifests if item["id"] == "dpm:labor:3.0.0-product-draft.1")
        node_response = client.post("/api/v1/edge-nodes", json={"edge_node_id": EDGE_NODE, "labels": {"kubeedge": "v1.20.0", "lexaegis.io/domain": "edge"}})
        node_response.raise_for_status()
        results["registration"] = True
        log("edge node registered", "ok")
        a1 = client.post("/api/v1/package-assignments", json={"manifest_id": m1["id"], "edge_node_id": EDGE_NODE}).json()
        bundle1 = client.post(f"/api/v1/package-assignments/{a1['id']}/deliver").json()
        (WORK / "bundle1.json").write_text(json.dumps(bundle1))
        sh(["docker", "cp", str(WORK / "bundle1.json"), f"{EDGE_CONTAINER}:/tmp/bundle1.json"])
        receipt = json.loads(edge_py("import json,sys; sys.path.insert(0,'/opt/lexaegis'); from lexaegis.storage import Store; from lexaegis import package_controller; bundle=json.load(open('/tmp/bundle1.json')); store=Store(__import__('pathlib').Path('/data/edge-app/app.sqlite')); t=store.transaction(); r=t.__enter__(); out=package_controller.edge_apply(r,bundle,'edge-1'); t.__exit__(None,None,None); print(json.dumps(out))").splitlines()[-1])
        client.post(f"/api/v1/package-assignments/{a1['id']}/receipts", json=receipt).raise_for_status()
        client.post(f"/api/v1/package-assignments/{a1['id']}/receipts", json={"kind": "activated", "edge_node_id": EDGE_NODE, "manifest_hash": receipt["manifest_hash"], "detail": {"packs_usable": True}}).raise_for_status()
        results["delivery"] = True
        log("assignment-1 verified and activated", "ok")

        sh(["docker", "network", "disconnect", "kind", EDGE_CONTAINER])
        disconnected = True
        deadline = time.time() + 90
        ready = "True"
        while time.time() < deadline:
            node_state = json.loads(sh(["kubectl", "get", "node", EDGE_NODE, "-o", "json"]))
            ready = next((condition["status"] for condition in node_state["status"]["conditions"] if condition["type"] == "Ready"), "Unknown")
            if ready != "True":
                break
            time.sleep(5)
        if ready == "True":
            raise RuntimeError("edge node did not become NotReady")
        results["disconnect"] = True
        log("edge disconnected and NotReady", "ok")
        a2 = client.post("/api/v1/package-assignments", json={"manifest_id": m2["id"], "edge_node_id": EDGE_NODE}).json()
        bundle2 = client.post(f"/api/v1/package-assignments/{a2['id']}/deliver").json()
        (WORK / "bundle2.json").write_text(json.dumps(bundle2))
        config_map = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "lexaegis-bundle-2", "namespace": "default"}, "data": {"bundle.json": json.dumps(bundle2)}}
        (WORK / "cm-bundle2.yaml").write_text(json.dumps(config_map))
        sh(["kubectl", "delete", "configmap", "lexaegis-bundle-2", "--ignore-not-found"])
        sh(["kubectl", "create", "-f", str(WORK / "cm-bundle2.yaml")])
        pod = {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "bundle-carrier", "namespace": "default"}, "spec": {"nodeName": EDGE_NODE, "hostNetwork": True, "containers": [{"name": "pause", "image": "kubeedge/pause:3.6", "volumeMounts": [{"name": "bundle", "mountPath": "/bundle"}]}], "volumes": [{"name": "bundle", "configMap": {"name": "lexaegis-bundle-2"}}]}}
        (WORK / "pod-carrier.yaml").write_text(json.dumps(pod))
        sh(["kubectl", "delete", "pod", "bundle-carrier", "--ignore-not-found"])
        sh(["kubectl", "create", "-f", str(WORK / "pod-carrier.yaml")])
        present = sh(["docker", "exec", EDGE_CONTAINER, "sh", "-c", "ls /var/lib/kubelet/pods/*/volumes/kubernetes.io~configmap/bundle/bundle.json 2>/dev/null || echo absent"])
        if present.strip() != "absent":
            raise RuntimeError("bundle reached edge while disconnected")
        results["bundle_absent_while_disconnected"] = True
        log("bundle absent during disconnect", "ok")

        sh(["docker", "network", "connect", "kind", EDGE_CONTAINER])
        disconnected = False
        deadline = time.time() + 90
        ready = "Unknown"
        while time.time() < deadline:
            node_state = json.loads(sh(["kubectl", "get", "node", EDGE_NODE, "-o", "json"]))
            ready = next((condition["status"] for condition in node_state["status"]["conditions"] if condition["type"] == "Ready"), "Unknown")
            if ready == "True":
                break
            time.sleep(5)
        if ready != "True":
            raise RuntimeError("edge node did not become Ready after reconnect")
        results["reconnect"] = True
        log("edge reconnected and Ready", "ok")
        deadline = time.time() + 120
        synced_path = ""
        while time.time() < deadline:
            found = sh(["docker", "exec", EDGE_CONTAINER, "sh", "-c", "ls /var/lib/kubelet/pods/*/volumes/kubernetes.io~configmap/bundle/bundle.json 2>/dev/null | head -1"], check=False)
            if "bundle.json" in found:
                synced_path = found.strip()
                break
            time.sleep(5)
        if not synced_path:
            raise RuntimeError("configmap bundle never synced to edge node")
        results["bundle_synced"] = True
        receipt2 = json.loads(edge_py("import json,sys,glob; sys.path.insert(0,'/opt/lexaegis'); from lexaegis.storage import Store; from lexaegis import package_controller; bundle=json.load(open(glob.glob('/var/lib/kubelet/pods/*/volumes/kubernetes.io~configmap/bundle/bundle.json')[0])); store=Store(__import__('pathlib').Path('/data/edge-app/app.sqlite')); t=store.transaction(); r=t.__enter__(); out=package_controller.edge_apply(r,bundle,'edge-1'); t.__exit__(None,None,None); print(json.dumps(out))").splitlines()[-1])
        if receipt2.get("manifest_hash") != bundle2.get("manifest_hash"):
            raise RuntimeError("synced bundle hash does not match assignment-2")
        client.post(f"/api/v1/package-assignments/{a2['id']}/receipts", json=receipt2).raise_for_status()
        client.post(f"/api/v1/package-assignments/{a2['id']}/receipts", json={"kind": "activated", "edge_node_id": EDGE_NODE, "manifest_hash": receipt2["manifest_hash"], "detail": {"channel": "kubeedge-configmap-sync"}}).raise_for_status()
        log("bundle synced and activated", "ok")
        client.post(f"/api/v1/package-assignments/{a1['id']}/revoke", json={"reason": "synthetic drill revocation"}).raise_for_status()
        rev = json.loads(edge_py("import json,sys; sys.path.insert(0,'/opt/lexaegis'); from lexaegis.storage import Store; from lexaegis import package_controller; store=Store(__import__('pathlib').Path('/data/edge-app/app.sqlite')); t=store.transaction(); r=t.__enter__(); out=package_controller.edge_revoke(r,""" + repr(m1["id"]) + ", 'edge-1'); t.__exit__(None,None,None); print(json.dumps(out))").splitlines()[-1])
        client.post(f"/api/v1/package-assignments/{a1['id']}/receipts", json=rev).raise_for_status()
        results["revocation"] = True
        reconcile = client.get("/api/v1/package-distribution/reconcile")
        reconcile.raise_for_status()
        if not all(not value for value in reconcile.json().values() if isinstance(value, list)):
            raise RuntimeError("reconcile reported outstanding assignments")
        results["reconcile"] = True
        log("revocation and reconcile clean", "ok")
        return build_report(args, "pass", results)
    finally:
        if disconnected:
            subprocess.run(["docker", "network", "connect", "kind", EDGE_CONTAINER], capture_output=True, text=True, timeout=60)
        client.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=Path("deploy/k8s/DRILL_EVIDENCE.md"))
    parser.add_argument("--json-report", type=Path)
    parser.add_argument("--source-commit")
    parser.add_argument("--image", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        report = run(args)
    except Exception as exc:
        print(f"drill failed: {type(exc).__name__}", file=sys.stderr)
        try:
            report = build_report(args, "fail", {key: False for key in ("registration", "delivery", "disconnect", "bundle_absent_while_disconnected", "reconnect", "bundle_synced", "revocation", "reconcile")}, type(exc).__name__)
        except Exception:
            return 1
        if args.json_report:
            args.json_report.parent.mkdir(parents=True, exist_ok=True)
            args.json_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text("# KubeEdge local drill evidence\n\nStatus: **FAILED**\n")
        return 1
    if args.json_report:
        args.json_report.parent.mkdir(parents=True, exist_ok=True)
        args.json_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text("# KubeEdge local drill evidence\n\n```text\n" + "\n".join(LOG) + "\n```\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
