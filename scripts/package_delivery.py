"""Assemble an offline delivery archive from already built, identified artifacts.

No build, pull, model download, evidence signing, or production activation occurs.
Docker-save configuration hashes are checked without loading or executing images.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile
import zipfile

from lexaegis.contracts import ReleaseBuildManifest
from lexaegis.release_build import build_manifest_identity_hash


ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return "sha256:" + result.hexdigest()


def image_ids(archive_path):
    """Read only manifest/config JSON; never extract untrusted archive paths."""
    with tarfile.open(archive_path, "r:*") as archive:
        def content(name):
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("Unsafe Docker archive member")
            item = archive.getmember(name)
            if not item.isfile() or item.size > 2 * 1024 * 1024:
                raise ValueError("Invalid Docker archive metadata")
            with archive.extractfile(item) as stream:
                return stream.read()

        manifest = json.loads(content("manifest.json"))
        if not isinstance(manifest, list) or not manifest:
            raise ValueError("An image archive must be produced by docker image save")
        return {"sha256:" + hashlib.sha256(content(item["Config"])).hexdigest() for item in manifest}


def package(*, root, profile, images, runtime_image, route_image, manifest_path, wheel,
            dependencies, output):
    root, images, wheel, output = map(Path, (root, images, wheel, output))
    if profile not in {"production", "demo", "integration"}:
        raise ValueError("Unknown runtime profile")
    if output.exists():
        raise ValueError("Refusing to overwrite an existing delivery archive")
    available = image_ids(images)
    if runtime_image not in available or route_image not in available:
        raise ValueError("Both fixed runtime and route image IDs must exist in the Docker archive")
    manifest = ReleaseBuildManifest.model_validate_json(Path(manifest_path).read_text(encoding="utf-8"))
    if profile == "production" and manifest.status != "verified":
        raise ValueError("Production delivery requires a verified build manifest")
    if manifest.wheel_hash != sha256(wheel):
        raise ValueError("Wheel does not match the frozen build manifest")
    for role in ("api", "worker", "gateway"):
        if manifest.container_image_digests.get(role) != runtime_image:
            raise ValueError(f"The fixed {role} image does not match the build manifest")
    for name in ("requirements.lock", "frontend/pnpm-lock.yaml"):
        if manifest.lockfile_hashes.get(name) != sha256(root / name):
            raise ValueError(f"Lockfile changed after build verification: {name}")
    inventory = json.loads(Path(dependencies).read_text(encoding="utf-8"))
    components = inventory.get("components")
    if not isinstance(components, list) or not components:
        raise ValueError("A dependency and license inventory is required")
    for component in components:
        if any(not str(component.get(key) or "").strip() for key in ("name", "version", "license")):
            raise ValueError("Every dependency needs a name, version and license")
    if inventory.get("runtime_image_id") != runtime_image:
        raise ValueError("Dependency inventory must describe the exact delivered image")
    files = {
        "images.tar": images, "release-build-manifest.json": Path(manifest_path),
        "dependencies.json": Path(dependencies), f"wheels/{wheel.name}": wheel,
    }
    fixed = ["compose.yaml", "compose.demo.yaml", "compose.integration.yaml", ".env.example",
             "requirements.lock", "frontend/pnpm-lock.yaml", "NOTICE",
             "scripts/windows/lexaegis.ps1", "docs/DUAL_TRACK_DEPLOY.md",
             "docs/DUAL_TRACK_ACCEPTANCE.md", "docs/PROVENANCE.md"]
    fixed.extend(path.relative_to(root).as_posix() for path in (root / "LICENSES").rglob("*") if path.is_file())
    for name in fixed:
        path = root / name
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"Missing delivery asset: {name}")
        files[name] = path
    if any(path.is_symlink() for path in files.values()):
        raise ValueError("Delivery inputs cannot be symbolic links")
    index = {
        "schema_version": 1, "runtime_profile": profile,
        "runtime_image_id": runtime_image, "route_image_id": route_image,
        "source_commit": manifest.source_commit,
        "build_manifest_hash": build_manifest_identity_hash(manifest),
        "build_status": manifest.status,
        "production_acceptance": "not_attested_by_packaging",
        "models": "not_included_register_versions_and_checksums_separately",
        "files": {name: sha256(path) for name, path in sorted(files.items())},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation protects existing deliverables if two jobs race.
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_STORED) as archive:
        for name, path in sorted(files.items()):
            archive.write(path, name)
        archive.writestr("delivery.json", json.dumps(index, ensure_ascii=False, indent=2) + "\n")
    return index


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, choices=["production", "demo", "integration"])
    parser.add_argument("--images", required=True, type=Path, help="docker image save archive containing both images")
    parser.add_argument("--runtime-image", required=True, help="immutable sha256 image configuration ID")
    parser.add_argument("--route-image", required=True, help="immutable sha256 route-isolation image configuration ID")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--dependencies", required=True, type=Path, help="image-bound components/name/version/license inventory")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = package(root=ROOT, profile=args.profile, images=args.images, runtime_image=args.runtime_image,
                     route_image=args.route_image, manifest_path=args.manifest, wheel=args.wheel,
                     dependencies=args.dependencies, output=args.output)
    print(json.dumps({"archive": str(args.output), "sha256": sha256(args.output),
                      "profile": args.profile, "build_status": result["build_status"],
                      "production_acceptance": result["production_acceptance"]}))


if __name__ == "__main__":
    main()
