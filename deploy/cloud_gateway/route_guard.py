"""Cloud ingress namespace guard; contains no credentials or application data."""
import os
from pathlib import Path
import subprocess
import time


def block_default_routes():
    for family in ('-4','-6'):
        while subprocess.run(['ip',family,'route','show','default'],capture_output=True,check=True).stdout.strip():
            subprocess.run(['ip',family,'route','del','default'],capture_output=True,check=True)


def namespace():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()+':'+os.readlink('/proc/self/ns/net')


if __name__=='__main__':
    ready=Path('/run/route-guard/ready')
    while True:
        block_default_routes()
        if ready.exists(): ready.chmod(0o600)
        ready.write_text(namespace())
        ready.chmod(0o444)
        time.sleep(.5)
