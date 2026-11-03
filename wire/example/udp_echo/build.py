"""Build: copy the sources into bin/ (the declared binaries)."""

import shutil
from pathlib import Path

root = Path(__file__).resolve().parent
(root / "bin").mkdir(exist_ok=True)
for name in ("udp_echo_server.py", "udp_echo_client.py"):
    shutil.copyfile(root / "src" / name, root / "bin" / name)
