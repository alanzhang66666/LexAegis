"""Run AFTER docker compose up. Real runtime assertions, not a config-only claim."""
import subprocess

def inside(service, code):
    subprocess.run(["docker","compose","exec","-T",service,"python","-c",code],check=True)

for name in ("api", "worker"):
    inside(name, "import socket,os; assert not os.getenv('LEX_CLOUD_API_KEY'); s=socket.socket(); s.settimeout(3); assert s.connect_ex(('1.1.1.1',443)) != 0, 'Unexpected external network access'")
inside("gateway", "from pathlib import Path; import os; assert not Path('/data/files').exists(); assert not Path('/data/app.sqlite').exists(); assert not os.getenv('LEX_LOCAL_PASSWORD')")
print("PASS: API/worker egress blocked; gateway raw-data mounts absent.")
