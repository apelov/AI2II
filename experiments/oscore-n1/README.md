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

The peers are the C implementation from the CoAP multicast-notifications project. Check it
out (or symlink it) as `coap/` in this directory; `coap/` is git-ignored so the experiment
directory stays clean.

```sh
git clone https://github.com/apelov/coap-multicast-notifications coap
python3 -m wire run experiments/oscore-n1/interop.yaml --cell N1 --out /tmp/n1
```

The evidence in `runs/wire/oscore-n1/` was produced from a development commit of that
implementation (`288cd27`, recorded in the bundle's `env.json`) that is not yet in the
public repository, with the manifest of that time (client driver started by absolute path).
