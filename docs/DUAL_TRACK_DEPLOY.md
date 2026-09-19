# Production and demonstration runtime profiles

LexAegis uses one application core with three startup profiles. The profile is
selected by `LEX_RUN_PROFILE` before the API, worker, or gateway starts. The
default is `production`; a running process does not offer a UI switch. Capture
the value at service startup and pass it to every runtime boundary.

| Profile | Host API port | Data origin and transport |
| --- | ---: | --- |
| `production` | 38765 | Real case data; no demo/mock scope |
| `demo` | 48765 | Bundled synthetic cases; local/mock only; gateway has no egress |
| `integration` | 58765 | Registered synthetic cases; local/cloud integration |

The native launcher uses `.data/profiles/<profile>/{app,gateway}` by default.
Override the base with `LEX_PROFILE_ROOT`. Each data root gets a
`.lexaegis-runtime.json` marker containing its profile and storage role. API and
worker share the `app` marker; gateway uses a separate `gateway` marker. A
symlink path, mismatched marker, or populated unmarked directory stops startup.
Legacy data must be reviewed and explicitly marked before use:

```powershell
python -m lexaegis.cli migrate-runtime --root <path> --role app --profile production --declared-legacy-profile production --confirm-existing-data-is-this-profile
```

Do not label legacy data as demo or integration. This command only records the
operator's declared existing profile; it does not convert real data to
synthetic data.

## Compose profiles

Copy `.env.example` to a separate local environment file for each profile and
set unique `LEX_COMPOSE_PROJECT`, data paths, and loopback API port. Use
`compose.yaml` for production and integration. Use `compose.demo.yaml` by itself
for the offline demo profile. Its internal processing network is separate from a
loopback-published API bridge; an API-side route-isolation helper removes the
API network namespace default route, while the gateway is attached only to the
internal network and receives no cloud credentials. Compose project names and
bind-mounted data paths keep volumes separate. The host-published API path and
network isolation must be verified in the target Docker Desktop environment. Never share profile secrets
or data directories.

Demo seed endpoints and scenarios must remain bundled synthetic inputs. The
integration profile is for registered synthetic inputs and can use a real model
endpoint; it is not a production release path. A request must bind its runtime
profile, data origin, and synthetic manifest hash in request dependencies.

## Windows customer host

Install Docker Desktop with its WSL2 backend and a supported x64/Arm64 architecture.
All maintenance Python runs inside the already loaded fixed image with networking
disabled; the host does not need a separate Python installation. From PowerShell, run
`scripts/windows/lexaegis.ps1` with one of
`init`, `start`, `stop`, `doctor`, `backup`, `restore`, `upgrade`, or `rollback`.
Production `start` and `upgrade` require `-ReleaseImage`, `-RouteImage`, and
`-DeliveryIndex` from the extracted reviewed bundle, plus a valid
`release-build-manifest.json`. The script checks Docker image configuration IDs
against the delivery index and checks API, worker, and gateway image IDs against
the manifest before activation; it stores immutable image IDs in the profile. The
manifest is copied into the profile data and mounted read-only into API, worker,
and gateway. API, worker, and gateway must all report the same verified build
identity before production acceptance. The route-isolation helper image must also be loaded from the bundle and selected
by exact ID; there is no default route-image tag. Compose has `pull_policy: never`
for both images.
The script stores independent state under
`%LOCALAPPDATA%\LexAegis\<profile>`, applies a user-only ACL, checks Docker
availability, and keeps generated credentials out of console output. The API
binds to loopback only. It does not download model weights; install and verify
an optional local model separately.

Prepare a Windows delivery directory from already-built and hash-verified
release inputs with [package_delivery.py](../scripts/package_delivery.py). The
packager does not build or fetch images. The resulting bundle must include the
release manifest, fixed application and route-isolation images, wheel, and
dependency/license inventory before it is moved to a customer machine. Extract
`delivery.json` beside the manifest and pass its path with `-DeliveryIndex`;
select the image configuration IDs recorded in it for `-ReleaseImage` and
`-RouteImage` (or local names resolving to those IDs).

Backup and restore require stopped services. Upgrade creates a pre-upgrade
backup with the currently selected image and release manifest before activating
the new release. Rollback restores that full backup and selects the exact image
reference recorded in the archive; it refuses if that image is not already
loaded. Rollback restores to a fresh data
directory and preserves the post-upgrade directory beside it. If an outbound
dispatch is sending or its outcome is uncertain, maintenance refuses to
continue until the request is reconciled. Restore rejects older unmarked backup
archives and profile mismatches.

Every restore revokes unconsumed grants, approvals, and queued sends, including
when restoring to the same build. Human review history and consumed gateway
records remain intact; restored sending/unknown requests require reconciliation.
Both data roots carry a durable `.lexaegis-restore-in-progress` marker until
copying and authorization invalidation succeed in both databases. API, worker,
and gateway refuse startup while that marker remains. Windows maintenance rolls
back the original directories after a caught restore error. For an interrupted
standalone CLI restore, preserve the backup and restore again into new empty
directories; never remove the marker to start a partially restored database.

Native mode does not attest network isolation. Use Compose for an offline demo
whose gateway has no egress. Production dispatch still depends on the separate
formal release and approval gates; the profile is only an additional scope
boundary.

The Python suite includes static PowerShell contract checks for restore argument
construction, manifest/image ID matching, and offline maintenance invocation.
These checks do not execute PowerShell. Windows syntax and end-to-end install,
upgrade, restore, and rollback remain unverified until run on a Windows host with
Docker Desktop and the fixed delivery images.
