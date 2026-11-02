"""Authenticated loopback liveness probe for the isolated gateway process.

A healthy response proves the gateway endpoint can be reached and authenticated;
its `unconfigured` provider status does not authorize a cloud dispatch.
"""
import os
from urllib.request import ProxyHandler, Request, build_opener

from .util import sign


def probe(port: int, secret: str) -> None:
    if not secret:
        raise ValueError("gateway health probe requires a signing secret")
    request = Request(
        f"http://127.0.0.1:{port}/health",
        headers={"X-Gateway-Signature": sign({"op": "health"}, secret)},
    )
    with build_opener(ProxyHandler({})).open(request, timeout=2) as response:
        if response.status != 200:
            raise RuntimeError("gateway health probe did not return HTTP 200")


def main() -> None:
    probe(int(os.getenv("LEX_GATEWAY_PORT", "8766")), os.getenv("LEX_GATEWAY_SECRET", ""))


if __name__ == "__main__":
    main()
