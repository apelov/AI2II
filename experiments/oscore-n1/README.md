# Experiment oscore-n1

Cell N1 of the CoAP multicast-notifications interop matrix
(draft-ietf-core-observe-multicast-notifications): nosec profile, one C server, three C
clients run one after another (only one nosec C client can hold the multicast port).

- `interop.yaml`: the wire manifest.
- `clients_seq.py`: client-side peer that runs the three clients in order.
- `check_route.py`: env check; the group 224.0.1.187 must route via `lo0`
  (`sudo route add -host 224.0.1.187 -interface lo0` on macOS).
- `checkers/`: the independent checker `observes_n1.py` and its five capture negatives,
  written by a different model family than the implementation, from the draft and the wire
  only (see `checkers/README.md`).

## Running it

The peers are the C implementation from the public CoAP multicast-notifications project,
pinned at commit `9b7d288` (an env check refuses any other commit). Clone it as `coap/` in this
directory; `coap/` is git-ignored so the experiment directory stays clean.

```sh
git clone https://github.com/apelov/coap-multicast-notifications experiments/oscore-n1/coap
git -C experiments/oscore-n1/coap checkout 9b7d288
python3 -m wire run experiments/oscore-n1/interop.yaml --cell N1 --out /tmp/n1
```

Peers build with `make -B -f Makefile.vienna`, so every object is recompiled from the pinned
sources. A clean build gives `coap_server` sha256 `8c1732a8…` and `coap_client` `64b821d8…`;
compare with `env.json` of the bundle.

## Evidence

- `runs/wire/oscore-n1/N1-20261103T200141Z/`: **current PASS bundle**. Peers at public commit
  `9b7d288`, clean, binaries rebuilt from source (hashes above).
- `runs/wire/oscore-n1/N1-20261103T124304Z/`: first PASS bundle, kept as a lesson. Its binaries
  were linked from stale object files in a development checkout (`make` reused `src/*.o` from July
  and October), so its binary hashes (`50054f53…`, `dc12c36b…`) do not correspond to a clean build of
  any commit. The wire runner deletes declared binaries, not intermediate build products: build
  commands must force a clean build.
- `runs/wire/oscore-n1/N1-20261103T120828Z-no-route/`: ENV bundle. The multicast route env check
  failed; nothing was built or started.
