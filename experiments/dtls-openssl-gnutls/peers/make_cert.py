"""Build step: a throwaway self-signed P-256 certificate for localhost (test key, never reused)."""

import pathlib
import subprocess
import sys

out = pathlib.Path("certs")
out.mkdir(exist_ok=True)
subprocess.run(
    [sys.argv[1], "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
     "-nodes", "-keyout", str(out / "key.pem"), "-out", str(out / "cert.pem"),
     "-days", "2", "-subj", "/CN=localhost"],
    check=True, capture_output=True,
)
