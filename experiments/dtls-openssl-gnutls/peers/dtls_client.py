"""Client adapter: send one payload over DTLS 1.2 with OpenSSL s_client or GnuTLS gnutls-cli.

Exit 0 only if the payload comes back unchanged (the exchange completed). Session keys go to
the file in SSLKEYLOGFILE (OpenSSL: passed as -keylogfile; GnuTLS reads the variable itself).
"""

import argparse
import os
import subprocess
import sys
import time

ap = argparse.ArgumentParser()
ap.add_argument("--stack", choices=["openssl", "gnutls"], required=True)
ap.add_argument("--bin", required=True)
ap.add_argument("--port", type=int, required=True)
ap.add_argument("--payload-file", required=True)
a = ap.parse_args()
payload = open(a.payload_file, "rb").read().strip()
keylog = os.environ["SSLKEYLOGFILE"]
if a.stack == "openssl":
    argv = [a.bin, "s_client", "-dtls1_2", "-connect", f"127.0.0.1:{a.port}",
            "-keylogfile", keylog, "-quiet", "-ign_eof"]
else:
    argv = [a.bin, "--udp", "--insecure", "-p", str(a.port), "127.0.0.1"]
p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
time.sleep(1.5)  # handshake
p.stdin.write(payload + b"\n")
p.stdin.flush()
time.sleep(2.0)
p.terminate()
out, err = p.communicate(timeout=10)
sys.stdout.write(out.decode(errors="replace"))
sys.stderr.write(err.decode(errors="replace"))
ok = any(line.strip() == payload for line in out.splitlines())
print(f"[adapter] echo {'received' if ok else 'NOT received'}", flush=True)
sys.exit(0 if ok else 1)
