# Design review 07

Scope: DESIGN.md 24.20, “Portability and summaries,” after commit `60892e2`. I did not write the design. This review is of the proposal; it is not evidence of a successful wire run.

The design-06 first-run concern is resolved. “First run” now means `./demo.sh` for the UDP-echo example on macOS or Linux with Python 3.11+, PyYAML, git, and tcpdump with capture permission. Missing prerequisites must be named and cannot yield PASS. The alias addresses the interface difference; the prerequisite boundary makes the claim testable.

The summary-trust concern is resolved. Bundle discovery is defined at any depth by `verdict.json` or `SHA256SUMS`. A failed `verify-bundle` result is visibly `UNVERIFIED(...)` in text, while JSON places untrusted fields under `claimed` and sets `verified: false`. Missing or malformed `verdict.json` has a null verdict and an error. Tampering with a PASS bundle is an early falsification test.

The loopback alias, checker continuation after a peer failure, and read-only summary each serve the first-run, explanatory FAIL, and comparison goals respectively. None adds protocol-specific behavior to generic `wire/` code. There is no unnecessary abstraction, premature generalisation, or unnecessary dependency in this addition. No stated M10 goal lacks a component, and no proposed component lacks a goal. The clean-build rule remains author guidance rather than an enforced capability, as the design states.

**Self-challenge.** The riskiest assumption is that the UDP example actually runs unchanged on both supported hosts with those prerequisites. Run it from a fresh checkout on macOS and Linux, inspect the resolved interface and verdict, then remove a prerequisite and verify that the message names it. A separate tampered-bundle test should confirm that unverified PASS never occupies the verified PASS column without a visible trust marker.

Outcome: APPROVED
