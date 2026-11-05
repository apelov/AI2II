# Clean-machine test (before IETF 127)

Goal: confirm that a participant with a fresh machine gets a first PASS in minutes, and find
every undocumented dependency. Please run on **one fresh macOS and one fresh Linux** machine
(a VM or a new user account is fine; a container is acceptable for Linux) and send back the
report at the end.

Record the time from step 1 to the first PASS.

## 1. Prerequisites (note everything you had to install)

| | macOS | Debian/Ubuntu |
|---|---|---|
| Python 3.11+ | preinstalled or `brew install python` | `sudo apt install python3 python3-pip` |
| PyYAML | `python3 -m pip install pyyaml` | `sudo apt install python3-yaml` |
| git | Xcode command line tools | `sudo apt install git` |
| tcpdump with capture permission | preinstalled; permission: install Wireshark and its ChmodBPF, or `sudo` | `sudo apt install tcpdump`; run as root, or `sudo setcap cap_net_raw,cap_net_admin=eip $(which tcpdump)` |
| Wireshark (only for the TLS example and opening captures) | `brew install --cask wireshark` | `sudo apt install tshark` |

## 2. One-command demo

```sh
git clone https://github.com/apelov/AI2II && cd AI2II
./demo.sh
```

Expected: `exit 0 = PASS` for cell `echo`, `OK` from the bundle check, and, once the broken
example exists, `exit 1 = FAIL, as it must` for cell `echo-broken`. The checkout stays
unchanged (`git status` is empty afterwards).

## 3. Open the evidence

Open the `capture.pcap` printed by the demo in Wireshark (or `tshark -r <file>`), and read
`docs/BUNDLE.md` next to the bundle. Note anything unclear.

## 4. Repository checks

```sh
./scripts/verify_gate.sh                     # expected: GATE PASSED
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider tests acceptance   # real pytest; expected: all passed
# (without PYTHONDONTWRITEBYTECODE, leftover .pyc files under wire/ trip one M09 test; known, fix after IETF 127)
```

## 5. Secured protocol example (if Wireshark is installed)

```sh
python3 -m wire run wire/example/tls_echo/interop.yaml --cell echo --out /tmp/tls
python3 -m wire verify-bundle /tmp/tls/echo
```

Open `/tmp/tls/echo/capture-decrypted.pcapng` in Wireshark: the TLS application data should
appear decrypted with no configuration.

## Report

```
OS and version:
Python version:
Time to first PASS:
Installed by hand (not in the table above):
Step that failed (command, full output, verdict.json reason):
Unclear in the docs:
```
