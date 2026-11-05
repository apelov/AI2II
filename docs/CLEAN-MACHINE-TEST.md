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
| git identity (some tests commit) | `git config --global user.name "You"` and `user.email` | same |
| ruff 0.16.0 (only for `verify_gate.sh`) | `python3 -m pip install ruff==0.16.0` | same (newer ruff adds rules the code does not follow yet) |
| pytest (only for step 4) | `python3 -m pip install pytest` | same |
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
export PYTHONDONTWRITEBYTECODE=1             # leftover .pyc under wire/ trips one M09 test (known, fix after IETF 127)
python3 -m pytest -q -p no:cacheprovider tests acceptance/M00 acceptance/M01 acceptance/M02 acceptance/M08 acceptance/M09
                                             # real pytest; expected: all passed
```

Not expected to pass everywhere (known, fix after IETF 127): `acceptance/M10` is the
milestone's own platform evidence. Its AC1 test runs only on macOS, and its AC2 test needs
Docker and a prebuilt image `debian-wire-test`. `./demo.sh` (step 2) is the cross-platform
check for the same behaviour. On Linux, `acceptance/M02/test_m02.py::test_ac8_seatbelt_profile_and_confinement`
also fails: agent dispatch confines agents with macOS Seatbelt, so it is macOS-only.


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
