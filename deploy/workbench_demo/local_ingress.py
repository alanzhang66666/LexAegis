"""Fixed workbench TCP ingress for Docker Desktop loopback port publishing."""
import asyncio
import os
from pathlib import Path


async def handle(reader,writer):
    upstream=None
    try:
        remote,upstream=await asyncio.wait_for(asyncio.open_connection('public-origin',59767),timeout=5)
        async def copy(source,destination):
            while data:=await source.read(65536):
                destination.write(data)
                await destination.drain()
        tasks=[asyncio.create_task(copy(reader,upstream)),asyncio.create_task(copy(remote,writer))]
        try:
            await asyncio.wait(tasks,timeout=180,return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks: task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
    except (OSError,asyncio.TimeoutError):
        pass
    finally:
        if upstream: upstream.close()
        writer.close()


async def main():
    expected=Path('/proc/sys/kernel/random/boot_id').read_text().strip()+':'+os.readlink('/proc/self/ns/net')
    # A stale guard receipt from a previous Docker network namespace never opens
    # ingress. Recreating/restarting without the guard therefore fails closed.
    while True:
        try:
            if Path('/run/route-guard/ready').read_text()==expected: break
        except FileNotFoundError:
            pass
        await asyncio.sleep(.25)
    server=await asyncio.start_server(handle,'0.0.0.0',59767,limit=65536)
    async with server: await server.serve_forever()


if __name__=='__main__': asyncio.run(main())
