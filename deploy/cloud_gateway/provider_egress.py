"""Fixed CONNECT relay: gateway TLS remains end-to-end with DeepSeek.

No HTTP payload parsing, persistence, redirects, or request replay. Deployment
must attach this service only to the gateway's private network and its uplink.
"""
import asyncio
import ipaddress
import socket

TARGET = "api.deepseek.com:443"


def allowed_connect(header):
    try:
        first = header.decode("ascii").split("\r\n", 1)[0]
    except UnicodeDecodeError:
        return False
    return first in {f"CONNECT {TARGET} HTTP/1.1", f"CONNECT {TARGET} HTTP/1.0"}


async def provider_address():
    addresses = await asyncio.get_running_loop().getaddrinfo("api.deepseek.com", 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise ValueError("Provider DNS did not resolve exclusively to public addresses")
    return addresses[0][4][0]


async def handle(reader, writer):
    upstream = None
    try:
        header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=10)
        if len(header) > 4096 or not allowed_connect(header):
            writer.write(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
            return
        address = await asyncio.wait_for(provider_address(), timeout=10)
        remote, upstream = await asyncio.wait_for(asyncio.open_connection(address, 443), timeout=10)
        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()
        async def copy(source, destination):
            while chunk := await source.read(65536):
                destination.write(chunk)
                await destination.drain()
        tasks = [asyncio.create_task(copy(reader, upstream)), asyncio.create_task(copy(remote, writer))]
        try:
            await asyncio.wait(tasks, timeout=180, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    except (OSError, ValueError, asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
        pass  # No provider/credential/header contents enter ordinary logs.
    finally:
        if upstream:
            upstream.close()
            await upstream.wait_closed()
        writer.close()
        await writer.wait_closed()


async def main():
    slots = asyncio.Semaphore(16)
    async def bounded(reader, writer):
        async with slots:
            await handle(reader, writer)
    server = await asyncio.start_server(bounded, "0.0.0.0", 3128, limit=4096)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
