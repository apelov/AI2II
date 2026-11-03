# Design review 05

Scope: DESIGN.md 24.21, compared with review design-04 and architect commit e15f96c. I did not write the design. This is a design review, not evidence of a successful M09 run; no new orchestrator run log was produced.

The three design-04 findings are resolved. The decrypted checker must now reject a substituted decrypted view while the real secrets remain in place, so a key-file-only checker cannot satisfy the required negatives. The decrypt executable's resolved absolute path and SHA-256 are recorded in `env.json`, and scripts in the clean experiment directory are identified by its commit. Secret declarations are restricted to unique plain filenames, and the resulting files must be non-empty, regular and free of symlinks. A traversal name fails validation before peers start.

The peer environment, optional decrypt command, two retained capture views and checker negatives each serve the goal of reviewable secured exchanges. I found no goal without a component and no component without a goal. The design adds no unnecessary generic framework or protocol-specific decoding to `wire/`; editcap and TLS remain example choices rather than package dependencies. A decrypt command can invoke helpers outside the experiment directory, so its executable hash is not a complete transitive provenance record. The stated provenance claim now names exactly the executable and experiment scripts it identifies; this residual limit does not by itself let the TLS example satisfy the stated end-to-end capability without a readable decrypted view.

The riskiest assumption remains that the decrypted view reflects the captured exchange. The earliest useful falsification is to run the TLS example with altered keys and, separately, an unrelated decrypted view, then confirm that the canonical output is readable by tshark and both negatives fail. The test-keys-only rule is still a declared policy, as the design says.

Outcome: APPROVED
