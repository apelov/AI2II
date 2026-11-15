# Adversarial tests (exploratory, no wire bundle)

Tools that misbehave on purpose, to see how the peers handle error paths of
draft-ietf-core-observe-multicast-notifications-15. Written with Claude (family anthropic).

These runs are **exploratory**: they are not wire cells, so they have no bundle and no
independent checker. Every peer they exercise (C and Python) is from family anthropic, so a
checker for them must come from another family before any of this can become a bundle
(`docs/HACKATHON.md`, section 2: "peer behaviour, not a checker negative").

| Tool | What it does |
|---|---|
| `no_ack_client.py` | Registers, never ACKs the CON 5.03, and times its retransmissions (RFC 7252 4.2). Exit 0 if the server retransmits with the same Message ID. |
| `bad_server.py --variant V` | Answers one registration with a broken informative response (or a stray cancellation), then sends notifications to the group anyway. |
| `run_matrix.py --client c\|py --logs DIR` | Runs every `bad_server.py` variant against the C or the Python client and counts the notifications the client accepted. A correct client accepts them only for `good`. |

## Reproduce

From `experiments/oscore-n1`, with the C peers built (`make -B -f Makefile.vienna` in `coap/`)
and the multicast route on `lo0`:

```sh
(cd coap && ./coap_server -r mult) &  python3 adversarial/no_ack_client.py; kill %1
python3 py-server/mn_server.py &      python3 adversarial/no_ack_client.py; kill %1
python3 adversarial/run_matrix.py --client c  --logs /tmp/adv
python3 adversarial/run_matrix.py --client py --logs /tmp/adv
```

Each variant takes about 14 s; a full matrix about 3.5 minutes. Results are in `../RESULT.md`,
section "Exploratory adversarial tests".
