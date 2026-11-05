#!/usr/bin/env bash
# One-command demo of AI2II wire evidence: run the UDP-echo example, verify the bundle, explain it.
# Runs in a temporary copy, so the checkout is left untouched. Usage: ./demo.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PY="${PYTHON:-python3}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/ai2ii-demo.XXXXXX")"
EXP="$WORK/udp_echo"
OUT="$WORK/runs"

step() { printf '\n== %s\n' "$*"; }
die() { printf '\nDEMO STOPPED: %s\n' "$*" >&2; exit 1; }

step "Checking prerequisites"
command -v "$PY" >/dev/null || die "python3 not found"
"$PY" -c 'import yaml' 2>/dev/null || die "PyYAML missing: $PY -m pip install pyyaml"
command -v tcpdump >/dev/null || die "tcpdump not found (Linux: apt install tcpdump)"
command -v git >/dev/null || die "git not found"
echo "python3, PyYAML, tcpdump, git: OK"

step "Copying the example to $EXP (a fresh git repository, as wire requires a clean experiment directory)"
cp -R "$ROOT/wire/example/udp_echo" "$EXP"
rm -rf "$EXP/bin"
git -C "$EXP" init -q
git -C "$EXP" add -A
git -C "$EXP" -c user.name=demo -c user.email=demo@example.invalid commit -q -m demo

run_cell() {
  local cell="$1"
  set +e
  (cd "$ROOT" && "$PY" -m wire run "$EXP/interop.yaml" --cell "$cell" --out "$OUT/$cell")
  local rc=$?
  set -e
  return $rc
}

step "Running cell 'echo': a UDP echo server and a client, under packet capture"
if run_cell echo; then
  echo "exit 0 = PASS"
else
  rc=$?
  reason="$("$PY" -c "import json;print(json.load(open('$OUT/echo/echo/verdict.json'))['reason'])" 2>/dev/null || true)"
  [ $rc -eq 3 ] && die "BLOCKED: $reason
  If the capture was not permitted: macOS: join group access_bpf (Wireshark's ChmodBPF); Linux: run as root or give tcpdump CAP_NET_RAW.
  Details: $OUT/echo/echo/capture.log"
  die "unexpected exit $rc; see $OUT/echo/echo/verdict.json"
fi
B="$OUT/echo/echo"

step "Verifying the bundle's checksums"
(cd "$ROOT" && "$PY" -m wire verify-bundle "$B")

step "What is in the bundle ($B)"
cat <<EOF
  verdict.json         $("$PY" -c "import json,sys;v=json.load(open('$B/verdict.json'));print(v['verdict'],'-',v['reason'])")
  capture.pcap         the packets on the wire (open in Wireshark)
  echo-*.log           what each peer printed
  checker-*.log        the independent checkers' findings, then their run on each negative input
  env.json             commits, binary SHA-256, tool versions: what exactly ran
  SHA256SUMS           integrity of every file above (checked just now)
EOF

if grep -q 'name: echo-broken' "$EXP/interop.yaml"; then
  step "Running cell 'echo-broken': the server corrupts one byte of the echo"
  if run_cell echo-broken; then
    die "echo-broken gave PASS: the checkers missed a broken implementation"
  else
    rc=$?
    [ $rc -eq 1 ] || die "echo-broken: expected FAIL (exit 1), got exit $rc"
    echo "exit 1 = FAIL, as it must:"
    "$PY" -c "import json;v=json.load(open('$OUT/echo-broken/echo-broken/verdict.json'));print('  reason:',v['reason'])"
  fi
fi

step "Done"
echo "Bundles are in $OUT. Read docs/BUNDLE.md for every file, docs/HACKATHON.md to run your own experiment."
