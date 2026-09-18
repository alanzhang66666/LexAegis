"""Read-only runtime and isolation diagnostics."""
import os
import platform
import socket
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .launcher import frontend_location
from .outbound_gate import product_dispatch_state
from .util import app_dir

NATIVE_REDTEAM_URL = "http://127.0.0.1:8767"
ISOLATED_REDTEAM_URL = "http://redteam:8767"
_UNVERIFIED_GAPS = (
    "未验收：未安装 Docker/Compose 或无法执行探测",
    "未验收：不是隔离拓扑",
    "未验收：出口仍开放",
    "未验收：卷或密钥隔离不正确",
)


def edge_json_probe(timeout=8) -> dict:
    """Synthetic-block JSON probe. Does not read case material. Edge remains optional."""
    model = os.getenv("LEX_EDGE_MODEL", "")
    url = os.getenv("LEX_EDGE_URL", "http://127.0.0.1:8080/v1")
    if not model:
        return {"ok": True, "status": "unconfigured", "detail": "边侧未配置，跳过 JSON 探测"}
    try:
        from .providers import EdgeClient
        client = EdgeClient(url, model)
        health = client.health()
        if health.get("status") != "available":
            return {"ok": True, "status": "unconfigured", "detail": health.get("detail") or "边侧服务未启动，跳过 JSON 探测"}
        facts = client.extract(
            [{"id": "probe:synth:b1", "text": "合成探测：劳动者甲主张工资。"}],
            timeout=timeout,
        )
        return {"ok": True, "status": "available", "detail": f"合成块 JSON 探测通过（{len(facts)} 条）"}
    except Exception:
        return {"ok": False, "status": "failed", "detail": "边侧 JSON 探测失败；边侧仍为可选能力"}


def _ocr_construct_probe(provider_id=None) -> None:
    """Engine construct after operator attestation. Does not recognize pages."""
    from .parsing import PaddleOCRProvider, RapidOCRProvider

    chosen = provider_id or os.getenv("LEX_OCR_PROVIDER", "rapidocr")
    if chosen == "paddle":
        PaddleOCRProvider()._create_engine()
        return
    RapidOCRProvider()._create_engine()


def whisper_probe() -> dict:
    """Optional transcription doctor. Unconfigured does not fail-close."""
    if os.getenv("LEX_WHISPER_ENABLED") != "1":
        return {
            "ok": True,
            "status": "unconfigured",
            "detail": "本机转写为可选能力；未启用时音视频进入人工校正",
        }
    from .transcribe import whisper_capability

    capability = whisper_capability()
    status = capability.get("status")
    if status == "available":
        return {
            "ok": True,
            "status": "available",
            "detail": "转写冒烟/资产声明通过，不代表转写准确率已验收",
        }
    if os.getenv("LEX_WHISPER_MODELS_READY") == "1" or status == "failed":
        return {
            "ok": False,
            "status": "failed",
            "detail": capability.get("detail") or "本机转写探测失败；转写仍为可选能力",
        }
    return {
        "ok": True,
        "status": "unconfigured",
        "detail": "本机转写为可选能力；模型资产未声明就绪，音视频进入人工校正",
    }


def ocr_probe() -> dict:
    """Optional OCR doctor. Unconfigured does not fail-close; attested-but-broken is failed."""
    enabled = os.getenv("LEX_OCR_ENABLED") == "1"
    attested = os.getenv("LEX_OCR_MODELS_READY") == "1"
    if not enabled:
        return {
            "ok": True,
            "status": "unconfigured",
            "detail": "本地 OCR 为可选能力；未启用时扫描页保留原图并进入人工转录",
        }
    from .parsing import ocr_capability

    capability = ocr_capability()
    status = capability.get("status")
    provider_id = capability.get("provider") or os.getenv("LEX_OCR_PROVIDER", "rapidocr")
    if status == "available":
        if attested and provider_id in ("paddle", "rapidocr"):
            try:
                _ocr_construct_probe(provider_id)
            except Exception:
                return {
                    "ok": False,
                    "status": "failed",
                    "detail": "本地 OCR 引擎构造失败；OCR 仍为可选能力。此检查不是精度验收",
                }
        return {
            "ok": True,
            "status": "available",
            "detail": "OCR 冒烟/资产声明通过，不代表识别精度已验收",
        }
    if attested or status == "failed":
        return {
            "ok": False,
            "status": "failed",
            "detail": capability.get("detail") or "本地 OCR 探测失败；OCR 仍为可选能力",
        }
    return {
        "ok": True,
        "status": "unconfigured",
        "detail": "本地 OCR 为可选能力；模型资产未声明就绪，扫描页保留原图并进入人工转录",
    }


def doctor_report() -> dict:
    root = app_dir()
    checks = {
        "python": {"ok": sys.version_info >= (3, 12), "detail": platform.python_version()},
        "platform": {"ok": sys.platform.startswith(("win", "linux", "darwin")), "detail": f"{platform.system()} {platform.machine()}"},
        "data_directory": {"ok": root.exists() and os.access(root, os.R_OK | os.W_OK), "detail": str(root)},
        "frontend": {"ok": frontend_location() is not None, "detail": str(frontend_location() or "未构建")},
        "deployment_mode": {"ok": os.getenv("LEX_DEPLOYMENT_MODE", "native") in ("native", "isolated"), "detail": os.getenv("LEX_DEPLOYMENT_MODE", "native")},
        "edge_model": {"ok": bool(os.getenv("LEX_EDGE_MODEL")), "detail": "已配置" if os.getenv("LEX_EDGE_MODEL") else "可选，未配置时人工录入事实"},
        "edge_json": edge_json_probe(),
        "isolation": native_isolation_note(),
        "host_publish": host_publish_capability(),
        "ocr": ocr_probe(),
        "whisper": whisper_probe(),
    }
    optional = {"edge_model", "edge_json", "isolation", "host_publish", "ocr", "whisper"}
    return {"ok": all(item["ok"] for key, item in checks.items() if key not in optional), "checks": checks}


def isolated_runtime() -> bool:
    return os.getenv("LEX_DEPLOYMENT_MODE") == "isolated" or os.getenv("LEX_ISOLATED") == "1"


def resolve_redteam_url() -> str:
    """Compose DNS on isolated runtimes; loopback on native when unset."""
    explicit = (os.getenv("LEX_REDTEAM_URL") or "").strip()
    if explicit:
        return explicit.rstrip("/")
    return ISOLATED_REDTEAM_URL if isolated_runtime() else NATIVE_REDTEAM_URL


def probe_redteam(timeout=0.4) -> dict:
    """HTTP reachability of the redteam host. Does not evaluate attacks or start the service."""
    url = resolve_redteam_url()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return {"ok": False, "status": "unconfigured", "detail": f"红队 URL 无效（{url}）", "url": url}
    try:
        response = httpx.get(url + "/health", timeout=timeout, trust_env=False)
        return {
            "ok": True,
            "status": "available",
            "detail": f"红队服务可达（{url}）",
            "url": url,
            "http_status": response.status_code,
        }
    except Exception:
        return {
            "ok": False,
            "status": "unconfigured",
            "detail": f"红队服务不可达（{url}）；native 需单独启动，不会自动拉起。未运行、错误和不确定均不算通过",
            "url": url,
        }


def native_isolation_note() -> dict:
    """Informational only: native is never formal isolation. Doctor must not fail-close."""
    if isolated_runtime():
        return {
            "ok": True,
            "status": "configured",
            "detail": "环境声明 isolated；正式验收仍须 check-isolation 探测全部通过后记录，native 不能自证",
        }
    return {
        "ok": True,
        "status": "unconfigured",
        "detail": "未验收：native 不是正式隔离，lexaegis start 不能自证 isolation_verified；正式外发保持阻断",
    }


def legal_capability(published: list[dict] | None = None) -> dict:
    """Published isolation packs are not a product legal endorsement."""
    packs = list(published or [])
    allowed = sum(1 for pack in packs if pack.get("dispatch_allowed"))
    state = product_dispatch_state()
    label = "阻断" if state == "blocked" else state
    closer = (
        "仓库劳动包仍为待审草稿。隔离库 publish 不等于法学验收，"
        f"产品 formal_dispatch 保持{label}。"
    )
    if not packs:
        return {"status": "unconfigured", "detail": f"尚无已发布 V2 案由包。{closer}"}
    extra = f"，其中 {allowed} 个 dispatch_allowed=true" if allowed else "，均未打开产品外发"
    return {"status": "available", "detail": f"已发布 V2 案由包 {len(packs)} 个{extra}。{closer}"}


def isolation_capability(settings: dict | None = None) -> dict:
    settings = settings or {}
    mode = settings.get("deployment_mode") or os.getenv("LEX_DEPLOYMENT_MODE", "native")
    verified = bool(settings.get("isolation_verified"))
    if verified and mode == "isolated":
        return {"status": "available", "detail": "已记录隔离验收"}
    if mode != "isolated":
        return {
            "status": "unconfigured",
            "detail": "未验收：native 不能自证隔离；正式隔离仅在 Compose 探测全部通过后记录，lexaegis start 不会翻转 isolation_verified",
        }
    return {"status": "unconfigured", "detail": "未验收：尚无通过的隔离验收记录"}


_COMPOSE_PORT_CMD = ["docker", "compose", "port", "api", "8765"]
_REPO_ROOT = Path(__file__).resolve().parent.parent


def parse_compose_host_bind(text: str) -> str:
    """Return 127.0.0.1:<port> when published. `invalid IP:0` is unpublished."""
    line = ""
    for raw in reversed((text or "").splitlines()):
        candidate = raw.strip()
        if candidate:
            line = candidate
            break
    if not line or "invalid ip" in line.lower():
        return ""
    host, sep, port = line.rpartition(":")
    if sep != ":" or host != "127.0.0.1" or not port.isdigit() or int(port) <= 0:
        return ""
    return f"127.0.0.1:{int(port)}"


def compose_host_port_line(timeout=3) -> str:
    """Exact `docker compose port api 8765` line. Isolation probe is unrelated."""
    try:
        result = subprocess.run(
            _COMPOSE_PORT_CMD,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=_REPO_ROOT,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return str(error)
    line = (result.stdout or "").strip() or (result.stderr or "").strip()
    if not line:
        return f"exit {result.returncode}"
    return line.splitlines()[-1].strip()


def host_publish_capability(timeout=0.8, port_line: str | None = None) -> dict:
    """Host publish is not isolation. Does not fail-close. Never implies the login page opened."""
    if port_line is None and isolated_runtime() and os.getenv("LEX_RUNTIME_ROLE") == "api":
        return {
            "ok": True,
            "status": "unconfigured",
            "bind": "",
            "detail": (
                "未验收：隔离 API 容器不能证明宿主机发布；"
                "请在宿主机执行 docker compose port api 8765 与健康检查。"
                "隔离探测通过不等于浏览器已通"
            ),
        }
    raw = compose_host_port_line() if port_line is None else port_line
    bind = parse_compose_host_bind(raw)
    if not bind:
        return {
            "ok": True,
            "status": "unconfigured",
            "bind": raw,
            "detail": (
                f"未验收：宿主机口未发布（{raw or 'empty'}）；"
                "隔离探测通过不等于浏览器已通"
            ),
        }
    try:
        response = httpx.get(f"http://{bind}/api/v1/health", timeout=timeout, trust_env=False)
        if response.status_code == 200:
            return {
                "ok": True,
                "status": "available",
                "bind": bind,
                "detail": f"宿主机口已发布 {bind}，健康检查 200；打开登录页才算浏览器可达",
            }
        return {
            "ok": True,
            "status": "unconfigured",
            "bind": bind,
            "detail": (
                f"未验收：已解析绑定 {bind}，健康检查 HTTP {response.status_code}；"
                "不主张浏览器已通"
            ),
        }
    except Exception:
        return {
            "ok": True,
            "status": "unconfigured",
            "bind": bind,
            "detail": f"未验收：已解析绑定 {bind}，健康检查未通；不主张浏览器已通",
        }


def redteam_capability(protocols, probe=None) -> dict:
    """Available only with ≥4 frozen protocols *and* a reachable redteam host."""
    probe = probe if probe is not None else probe_redteam()
    frozen = len([item for item in protocols if item.get("status") == "frozen"])
    baseline = "当前为工程基线执行器，不是正式攻击结论"
    if not probe.get("ok"):
        return {"status": "unconfigured", "detail": f"{probe.get('detail') or '红队服务不可达'}。{baseline}"}
    if frozen < 4:
        return {
            "status": "unconfigured",
            "detail": f"冻结协议 {frozen}/4；未运行、错误和不确定均不算通过。{baseline}",
        }
    return {"status": "available", "detail": f"未运行、错误和不确定均不算通过。{baseline}"}


def isolation_report(timeout=.4) -> dict:
    mode = os.getenv("LEX_DEPLOYMENT_MODE", "native")
    role = os.getenv("LEX_RUNTIME_ROLE", "")
    isolated_flag = os.getenv("LEX_ISOLATED") == "1"
    outbound_blocked = False
    try:
        with socket.create_connection(("1.1.1.1", 443), timeout=timeout):
            outbound_blocked = False
    except OSError:
        outbound_blocked = True
    checks = {
        "isolated_mode": mode == "isolated" and isolated_flag,
        "api_or_worker_role": role in ("api", "worker"),
        "outbound_probe_blocked": outbound_blocked,
        "gateway_secret_not_reported": True,
    }
    return {"ok": all(checks.values()), "checks": checks, "detail": "单次探测只形成部署自检记录，不能替代防火墙审计。"}


def _unverified_isolation(details, reason):
    checklist = {
        "docker_compose": {"ok": False, "detail": _UNVERIFIED_GAPS[0]},
        "isolated_topology": {"ok": False, "detail": _UNVERIFIED_GAPS[1]},
        "egress_closed": {"ok": False, "detail": _UNVERIFIED_GAPS[2]},
        "volumes_secrets": {"ok": False, "detail": _UNVERIFIED_GAPS[3]},
    }
    return {
        "ok": False,
        "checks": {},
        "details": details,
        "checklist": checklist,
        "gaps": list(_UNVERIFIED_GAPS),
        "detail": f"未验收。{reason} 未记录 isolation_verified。",
    }


def _service_absent(text: str) -> bool:
    lowered = (text or "").lower()
    return any(token in lowered for token in (
        "not running", "no such service", "no container", "not found",
        "doesn't exist", "does not exist", "no such container",
    ))


def compose_isolation_report() -> dict:
    probes = {
        "api_no_egress": ["docker", "compose", "exec", "-T", "api", "python", "-c", "import socket; s=socket.socket(); s.settimeout(3); assert s.connect_ex(('1.1.1.1',443)) != 0"],
        "worker_no_egress": ["docker", "compose", "exec", "-T", "worker", "python", "-c", "import socket; s=socket.socket(); s.settimeout(3); assert s.connect_ex(('1.1.1.1',443)) != 0"],
        "gateway_no_case_volume": ["docker", "compose", "exec", "-T", "gateway", "python", "-c", "from pathlib import Path; assert not Path('/data/app.sqlite').exists(); assert not Path('/data/files').exists()"],
        "redteam_no_secrets": ["docker", "compose", "run", "--rm", "--no-deps", "--entrypoint", "python", "redteam", "-c", "import os; from pathlib import Path; assert not os.getenv('LEX_GATEWAY_SECRET'); assert not Path('/data/app.sqlite').exists()"],
        "benchmark_no_secrets": ["docker", "compose", "run", "--rm", "--no-deps", "--entrypoint", "python", "benchmark", "-c", "import os; from pathlib import Path; assert not os.getenv('LEX_GATEWAY_SECRET'); assert not Path('/data/app.sqlite').exists()"],
    }
    try:
        version = subprocess.run(["docker", "compose", "version"], capture_output=True, text=True)
    except OSError as error:
        return _unverified_isolation({"runtime": str(error)}, "Docker Compose 不可用")
    if version.returncode != 0:
        return _unverified_isolation(
            {"runtime": (version.stderr or version.stdout).strip()[-500:]},
            "Docker Compose 不可用",
        )
    checks = {}
    details = {}
    for name, command in probes.items():
        try:
            result = subprocess.run(command, capture_output=True, text=True)
        except OSError as error:
            return _unverified_isolation({"runtime": str(error), **details}, "Docker Compose 探测中断")
        checks[name] = result.returncode == 0
        details[name] = (result.stderr or result.stdout).strip()[-500:]
    topology_ok = (
        (checks.get("api_no_egress") or not _service_absent(details.get("api_no_egress", "")))
        and (checks.get("worker_no_egress") or not _service_absent(details.get("worker_no_egress", "")))
    )
    egress_ok = bool(checks.get("api_no_egress") and checks.get("worker_no_egress"))
    volumes_ok = bool(
        checks.get("gateway_no_case_volume")
        and checks.get("redteam_no_secrets")
        and checks.get("benchmark_no_secrets")
    )
    checklist = {
        "docker_compose": {"ok": True, "detail": "Docker Compose 可执行"},
        "isolated_topology": {
            "ok": topology_ok,
            "detail": "隔离拓扑已探测" if topology_ok else _UNVERIFIED_GAPS[1],
        },
        "egress_closed": {
            "ok": egress_ok,
            "detail": "api/worker 出口探测被阻断" if egress_ok else _UNVERIFIED_GAPS[2],
        },
        "volumes_secrets": {
            "ok": volumes_ok,
            "detail": "卷与密钥隔离探测通过" if volumes_ok else _UNVERIFIED_GAPS[3],
        },
    }
    ok = all(checks.values())
    gaps = [item["detail"] for item in checklist.values() if not item["ok"]]
    return {
        "ok": ok,
        "checks": checks,
        "details": details,
        "checklist": checklist,
        "gaps": gaps,
        "detail": (
            "运行态探测不能替代宿主机防火墙、卷权限和镜像供应链审计。"
            if ok else
            "未验收。Compose 探测未全部通过，未记录 isolation_verified。"
        ),
    }
