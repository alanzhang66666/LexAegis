"""Remove default routes; permit a single route to the fixed Docker host model."""
import json
import ipaddress
import os
from pathlib import Path
import subprocess
import time

MODEL_HOST=os.getenv('LEX_MODEL_HOST_IP','192.168.65.254')
if not isinstance(ipaddress.ip_address(MODEL_HOST),ipaddress.IPv4Address) or not ipaddress.ip_address(MODEL_HOST).is_private:
    raise ValueError('Model route must target the configured private IPv4 host')
TARGET=MODEL_HOST+'/32'
def command(*args):return subprocess.run(['ip',*args],check=True,capture_output=True).stdout
def enforce():
    routes=json.loads(command('-j','-4','route','show','default'))
    if routes:
        route=routes[0]
        command('-4','route','replace',TARGET,'via',route['gateway'],'dev',route['dev'])
    for family in ('-4','-6'):
        while command(family,'route','show','default').strip():command(family,'route','del','default')
if __name__=='__main__':
    while True:
        enforce()
        path=Path('/run/route-guard/ready')
        if path.exists():path.chmod(0o600)
        path.write_text(Path('/proc/sys/kernel/random/boot_id').read_text().strip()+':'+os.readlink('/proc/self/ns/net'))
        path.chmod(0o444)
        time.sleep(.5)
