"""Prepare a mountable, explicitly unverified manifest for CI isolation probes."""
from datetime import datetime, timezone
from pathlib import Path
import os

from lexaegis.contracts import ReleaseBuildManifest


def prepare(path: Path) -> ReleaseBuildManifest:
    manifest = ReleaseBuildManifest(
        id="ci-isolation-only", source_commit=os.getenv("GITHUB_SHA", ""),
        status="pending", worktree_clean=False,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    # Refuse to replace an actual release manifest or a directory Docker may
    # have created for a missing bind source.
    with path.open("x", encoding="utf-8") as stream:
        stream.write(manifest.model_dump_json(indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    prepare(Path("release-build-manifest.json"))
