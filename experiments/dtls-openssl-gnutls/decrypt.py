"""Decrypt step: inject every key log in the secrets dir into a self-decrypting pcapng.

Usage: python3 decrypt.py <editcap> <secrets dir> <capture> <decrypted>
Only the client peers export keys, so each cell's view is decryptable only with that cell's
client key log (a wrong-keys negative therefore really breaks decryption).
"""

import pathlib
import subprocess
import sys
import tempfile

editcap, secrets, capture, out = sys.argv[1:5]
logs = sorted(pathlib.Path(secrets).glob("*.keys"))
if not logs:
    sys.exit("no key logs in " + secrets)
with tempfile.NamedTemporaryFile("w", suffix=".keys", delete=False) as t:
    for f in logs:
        t.write(f.read_text())
r = subprocess.run([editcap, "-F", "pcapng", "--inject-secrets", f"tls,{t.name}", capture, out])
pathlib.Path(t.name).unlink()
sys.exit(r.returncode)
