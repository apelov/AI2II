# Reading an evidence bundle

A bundle is the directory `wire run` writes for one cell. It is self-contained: everything a
reviewer needs to check an interop claim, without trusting the person or agent who ran it.
This walk-through uses a real one, CoAP multicast notifications cell N1:
[`runs/wire/oscore-n1/N1-20261103T200141Z/N1/`](../runs/wire/oscore-n1/N1-20261103T200141Z/N1/).

## Check it in 30 seconds

```sh
python3 -m wire verify-bundle runs/wire/oscore-n1/N1-20261103T200141Z/N1   # OK = no file changed, added or removed
cat runs/wire/oscore-n1/N1-20261103T200141Z/N1/verdict.json                # PASS, and why
```

Then open `capture.pcap` in Wireshark (filter `coap`) and read `checker-observes-n1.log`.

## Every file

| File | What it is | What to look for |
|---|---|---|
| `verdict.json` | Exactly one verdict (PASS, FAIL, BLOCKED or ENV) with its reason, each peer's exit status, commit, dirty flag and binary SHA-256, and each checker's exit status. | `verdict`, `reason`; `peers.*.dirty` should be `false`; `peers.*.binaries` are the exact executables that ran. |
| `capture.pcap` | Every packet the capture filter matched during the cell, from tcpdump. | Open it in Wireshark. This is the primary evidence: the claim is about these bytes. |
| `capture.log` | tcpdump's own output (interface, link type, packet counts). | `N packets captured` > 0. An empty capture is BLOCKED, never PASS. |
| `<peer>.log` | stdout and stderr of each peer (here `c-server.log`, `c-clients.log`). | What each implementation said it did. Compare with the capture. |
| `build/<peer>.log` | Output of each peer's build command. | The compile commands. Declared binaries are deleted first, so they cannot be stale; the build should force a clean build so intermediate objects are not stale either. |
| `env.json` | Provenance: the manifest's SHA-256; the experiment directory's commit and dirty flag (which pins the checker code); each peer's path, commit, dirty flag, build exit status and binary hashes; the SHA-256 of every checker input and negative; tool versions (Python, git, tcpdump, platform); interfaces; start and end time. | `experiment.dirty: false` (required for PASS). Re-build a peer at its commit and compare the binary hash. |
| `envcheck/<name>.log` | Output of each declared environment check (here: libcoap present, the multicast route via loopback, the implementation at the pinned commit). | All ran before anything was built. If one fails, the verdict is ENV and nothing else runs, so "it was the environment" can only be claimed when a declared check says so. |
| `checker-<name>.log` | Each checker's output on the capture, then on each of its negatives. | One line per check with the spec section it enforces. Under `--- negative:` every negative must end in a FAIL line: that proves the checker can fail, so its PASS means something. |
| `inputs/` | Copies of the checker inputs and negatives used in this run (test vectors, negative captures). | Hashed in `SHA256SUMS` and in `env.json`, so the negatives cannot be swapped after the fact. |
| `SHA256SUMS` | SHA-256 of every other file in the bundle. | `verify-bundle` checks it. It proves the bundle is intact, not that the verdict is right; the files above are how you judge that. |

Secured-protocol bundles (DESIGN.md 24.21) have three more:

| File | What it is |
|---|---|
| `capture-decrypted.pcapng` | The same capture with the peers' session keys embedded: Wireshark opens it decrypted, no setup. `capture.pcap` stays as it was on the wire. |
| `secrets/` | The session keys the peers exported (test keys only). `verdict.json` then says `contains_secrets: true`. |
| `decrypt.log` | Output of the experiment's decrypt command. |

See `runs/wire/dtls-openssl-gnutls/` for two such bundles (DTLS 1.2, OpenSSL and GnuTLS).

## What a PASS means, exactly

All of these held in one run:
- the experiment directory (manifest and checkers) was committed and clean;
- every peer was built fresh and exited 0 within its timeout (a client exits 0 only if its exchange completed);
- the capture is non-empty;
- every checker passed on the capture, and failed on every one of its declared negatives;
- no checker came from the same AI model family as an implementation under test (declared in the manifest).

A FAIL is a finding: read the reason, the peer logs and the checker log. BLOCKED means the
setup was not good enough to judge (dirty checker directory, build failure, empty capture).
ENV means a declared host prerequisite was missing.
