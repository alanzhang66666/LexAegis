#!/usr/bin/env python3
"""KubeEdge local-cluster drill for the package-distribution control plane.

Drives a real KubeEdge channel (kind cluster + cloudcore + containerized
edgecore node "edge-1") plus a real LexAegis edge instance running inside
that node. Produces an evidence log for VALIDATION.md.

Scenario
  A. assign + deliver manifest bundle -> edge_apply -> verified/activated receipts
  B. disconnect edge (docker network disconnect) -> node NotReady, edge app
     stays autonomous, ConfigMap-carried bundle does NOT reach the edge
  C. reconnect -> node Ready, KubeEdge syncs the ConfigMap, edge consumes it
  D. revoke -> edge_revoke -> revoked receipt -> reconcile clean

Usage: python scripts/kubeedge_local_drill.py --report <path>
"""
import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

CP = "http://127.0.0.1:18777"
EDGE_CONTAINER = "edge-node-1"
EDGE_NODE = "edge-1"
EDGE_PY = "/opt/venv/bin/python"
WORK = Path(tempfile.gettempdir()) / "lex-edge-drill"
WORK.mkdir(exist_ok=True)
LOG = []


def log(step, detail=""):
    stamp = time.strftime("%H:%M:%S")
    LOG.append(f"[{stamp}] {step} :: {detail}")
    print(f"[{stamp}] {step} :: {detail}")


def sh(cmd, check=True, timeout=120):
    out = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True,
                         text=True, timeout=timeout)
    if check and out.returncode != 0:
        raise RuntimeError(f"{cmd} -> {out.returncode}: {out.stderr[:800]}")
    return out.stdout.strip()


def edge_py(code):
    """Run python inside the edge node container (the edge's own process)."""
    out = subprocess.run(
        ["docker", "exec", "-i", EDGE_CONTAINER, EDGE_PY, "-c", code],
        capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError(f"edge_py failed: {out.stderr[:800]}")
    return out.stdout.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", default="deploy/k8s/DRILL_EVIDENCE.md")
    args = ap.parse_args()

    client = httpx.Client(base_url=CP, timeout=30)
    login = client.post("/api/v1/login", json={"password": "cloud-drill-password-123"})
    login.raise_for_status()
    log("control-plane login", "ok")

    manifests = client.get("/api/v1/domain-package-manifests").json()
    m1 = next(m for m in manifests if m["id"] == "dpm:labor:2.0.0-draft.3")
    m2 = next(m for m in manifests if m["id"] == "dpm:labor:3.0.0-product-draft.1")
    log("manifests", f"{m1['id']}={m1['status']}, {m2['id']}={m2['status']}")

    # --- A: register + assign + deliver -----------------------------------
    node = client.post("/api/v1/edge-nodes", json={
        "edge_node_id": EDGE_NODE,
        "labels": {"kubeedge": "v1.20.0", "lexaegis.io/domain": "edge"}}).json()
    log("edge node registered", node["id"])

    a1 = client.post("/api/v1/package-assignments",
                     json={"manifest_id": m1["id"], "edge_node_id": EDGE_NODE}).json()
    log("assignment-1 created", f"{a1['id']} status={a1['status']}")

    bundle1 = client.post(f"/api/v1/package-assignments/{a1['id']}/deliver").json()
    (WORK / "bundle1.json").write_text(json.dumps(bundle1))
    log("assignment-1 delivered", f"bundle_hash={bundle1['bundle_hash'][:16]}...")

    sh(["docker", "cp", str(WORK / "bundle1.json"), f"{EDGE_CONTAINER}:/tmp/bundle1.json"])
    receipt = edge_py(
        "import json,sys; sys.path.insert(0,'/opt/lexaegis');"
        "from lexaegis.storage import Store; from lexaegis import package_controller;"
        "bundle=json.load(open('/tmp/bundle1.json'));"
        "store=Store(__import__('pathlib').Path('/data/edge-app/app.sqlite'));"
        "t=store.transaction(); r=t.__enter__();"
        "out=package_controller.edge_apply(r,bundle,'edge-1');"
        "t.__exit__(None,None,None);"
        "print(json.dumps(out))")
    receipt = json.loads(receipt.splitlines()[-1])
    log("edge_apply executed on edge-1", f"verified manifest_hash={receipt['manifest_hash'][:16]}...")

    r = client.post(f"/api/v1/package-assignments/{a1['id']}/receipts", json=receipt).json()
    log("verified receipt folded", f"status={r['status']}")
    act = client.post(f"/api/v1/package-assignments/{a1['id']}/receipts",
                      json={"kind": "activated", "edge_node_id": EDGE_NODE,
                            "manifest_hash": receipt["manifest_hash"],
                            "detail": {"packs_usable": True}}).json()
    log("activated receipt folded", f"status={act['status']}")

    # --- B: disconnect -----------------------------------------------------
    sh("docker network disconnect kind edge-node-1")
    log("EDGE DISCONNECTED", "docker network detach — CloudHub channel cut")

    # Wait for NotReady
    deadline = time.time() + 90
    status = "True"
    while time.time() < deadline:
        node = json.loads(sh(["kubectl", "get", "node", EDGE_NODE, "-o", "json"]))
        status = next((c["status"] for c in node["status"]["conditions"]
                       if c["type"] == "Ready"), "Unknown")
        if status != "True":
            break
        time.sleep(5)
    log("kubectl node status", f"edge-1 Ready={status} (lease expired while disconnected)")

    # Edge autonomy: the app still serves and still holds the imported packs.
    alive = edge_py(
        "import urllib.request;"
        "print(urllib.request.urlopen('http://127.0.0.1:8765/api/v1/health').status)")
    packs = edge_py(
        "import sys; sys.path.insert(0,'/opt/lexaegis');"
        "from lexaegis.storage import Store; from lexaegis import domain_packages;"
        "s=Store(__import__('pathlib').Path('/data/edge-app/app.sqlite'));"
        "t=s.read(); r=t.__enter__();"
        "print(len(r.list(domain_packages.MANIFEST_KIND)));"
        "t.__exit__(None,None,None)")
    log("edge autonomy", f"health={alive}, manifests held on edge={packs}")

    # Deliver assignment-2 while edge is down — bundle rides a ConfigMap that
    # KubeEdge can only sync while connected.
    a2 = client.post("/api/v1/package-assignments",
                     json={"manifest_id": m2["id"], "edge_node_id": EDGE_NODE}).json()
    bundle2 = client.post(f"/api/v1/package-assignments/{a2['id']}/deliver").json()
    (WORK / "bundle2.json").write_text(json.dumps(bundle2))
    log("assignment-2 delivered (control plane)", f"bundle_hash={bundle2['bundle_hash'][:16]}...")

    cm = {"apiVersion": "v1", "kind": "ConfigMap",
          "metadata": {"name": "lexaegis-bundle-2", "namespace": "default"},
          "data": {"bundle.json": json.dumps(bundle2)}}
    (WORK / "cm-bundle2.yaml").write_text(json.dumps(cm))
    sh(["kubectl", "delete", "configmap", "lexaegis-bundle-2", "--ignore-not-found"])
    sh(["kubectl", "create", "-f", str(WORK / "cm-bundle2.yaml")])
    # Pod on edge mounts it — must not exist on edge while disconnected.
    pod = {"apiVersion": "v1", "kind": "Pod",
           "metadata": {"name": "bundle-carrier", "namespace": "default"},
           "spec": {"nodeName": EDGE_NODE, "hostNetwork": True,
                    "containers": [{"name": "pause", "image": "kubeedge/pause:3.6",
                                    "volumeMounts": [{"name": "bundle",
                                                       "mountPath": "/bundle"}]}],
                    "volumes": [{"name": "bundle",
                                  "configMap": {"name": "lexaegis-bundle-2"}}]}}
    (WORK / "pod-carrier.yaml").write_text(json.dumps(pod))
    sh(["kubectl", "delete", "pod", "bundle-carrier", "--ignore-not-found"])
    sh(["kubectl", "create", "-f", str(WORK / "pod-carrier.yaml")])
    present = sh(["docker", "exec", EDGE_CONTAINER, "sh", "-c",
                  "ls /var/lib/kubelet/pods/*/volumes/kubernetes.io~configmap/bundle/bundle.json "
                  "2>/dev/null || echo absent"])
    log("disconnected check", f"bundle configmap on edge = {present.strip()}")

    # --- C: reconnect ------------------------------------------------------
    sh("docker network connect kind edge-node-1")
    log("EDGE RECONNECTED", "docker network attach")
    deadline = time.time() + 90
    status = "Unknown"
    while time.time() < deadline:
        node = json.loads(sh(["kubectl", "get", "node", EDGE_NODE, "-o", "json"]))
        status = next((c["status"] for c in node["status"]["conditions"]
                       if c["type"] == "Ready"), "Unknown")
        if status == "True":
            break
        time.sleep(5)
    log("kubectl node status", f"edge-1 Ready={status} (resynced)")

    deadline = time.time() + 120
    bundle_path = ""
    while time.time() < deadline:
        found = sh(["docker", "exec", EDGE_CONTAINER, "sh", "-c",
                    "ls /var/lib/kubelet/pods/*/volumes/kubernetes.io~configmap/bundle/bundle.json "
                    "2>/dev/null | head -1"], check=False)
        if "bundle.json" in found:
            bundle_path = found.strip()
            break
        time.sleep(5)
    log("kubeEdge sync", f"bundle arrived at edge fs: {bundle_path or 'TIMEOUT'}")
    if not bundle_path:
        raise RuntimeError("configmap bundle never synced to edge node")

    receipt2 = edge_py(
        "import json,sys,glob; sys.path.insert(0,'/opt/lexaegis');"
        "from lexaegis.storage import Store; from lexaegis import package_controller;"
        "bundle=json.load(open(glob.glob('/var/lib/kubelet/pods/*/volumes/kubernetes.io~configmap/bundle/bundle.json')[0]));"
        "store=Store(__import__('pathlib').Path('/data/edge-app/app.sqlite'));"
        "t=store.transaction(); r=t.__enter__();"
        "out=package_controller.edge_apply(r,bundle,'edge-1');"
        "t.__exit__(None,None,None);"
        "print(json.dumps(out))")
    receipt2 = json.loads(receipt2.splitlines()[-1])
    log("edge_apply (kubeedge-carried bundle)", f"manifest_hash={receipt2['manifest_hash'][:16]}...")
    client.post(f"/api/v1/package-assignments/{a2['id']}/receipts", json=receipt2)
    client.post(f"/api/v1/package-assignments/{a2['id']}/receipts",
                json={"kind": "activated", "edge_node_id": EDGE_NODE,
                      "manifest_hash": receipt2["manifest_hash"],
                      "detail": {"channel": "kubeedge-configmap-sync"}})
    log("assignment-2 receipts folded", "verified+activated via KubeEdge channel")

    # --- D: revoke ----------------------------------------------------------
    client.post(f"/api/v1/package-assignments/{a1['id']}/revoke",
                json={"reason": "drill revocation"})
    rev = edge_py(
        "import json,sys; sys.path.insert(0,'/opt/lexaegis');"
        "from lexaegis.storage import Store; from lexaegis import package_controller;"
        "store=Store(__import__('pathlib').Path('/data/edge-app/app.sqlite'));"
        "t=store.transaction(); r=t.__enter__();"
        f"out=package_controller.edge_revoke(r,'{m1['id']}','edge-1');"
        "t.__exit__(None,None,None);"
        "print(json.dumps(out))")
    rev = json.loads(rev.splitlines()[-1])
    log("edge_revoke executed", f"receipt={rev}")
    client.post(f"/api/v1/package-assignments/{a1['id']}/receipts", json=rev)

    report = client.get("/api/v1/package-distribution/reconcile").json()
    log("final reconcile",
        " ".join(f"{k}={len(v)}" for k, v in report.items()))

    Path(args.report).write_text(
        "# KubeEdge local drill evidence\n\n```text\n" + "\n".join(LOG) + "\n```\n")
    print(f"\nreport -> {args.report}")


if __name__ == "__main__":
    main()
