# Hackathon result submission

Copy this file into your experiment directory as `RESULT.md`, fill it in, and commit it with
your bundles. One file per experiment; one row per cell run.

## Experiment

- **Name:**
- **Team / contact:**
- **Draft(s) and revision(s):** (e.g. draft-ietf-core-observe-multicast-notifications-15)
- **Experiment directory and commit:** (path in this repository, `git rev-parse HEAD`)

## Implementations (peers)

| Peer | Implementation and version | Repository and commit | Written by (model family or human) | Under test |
|---|---|---|---|---|
| | | | | yes / no |

## Checkers

| Checker | Written by (model family or human) | What it asserts (spec sections) | Negatives |
|---|---|---|---|
| | | | |

The family of every checker must differ from every implementation under test.

## Results

`python3 -m wire summarize <your runs directory>` prints these rows.

| Cell | Verdict | Bundle path | Reason (for FAIL / BLOCKED / ENV) |
|---|---|---|---|
| | | | |

Every bundle must pass `python3 -m wire verify-bundle <bundle>`.

## Findings

For each FAIL that is a real finding:

- **What failed** (cell, checker line or peer log):
- **Spec text involved** (section, quote):
- **Implementation bug or spec ambiguity?**
- **Reported to** (issue link, mailing-list post, draft authors):

## Feedback on the draft

Ambiguities, missing text, or test vectors you needed and did not have.

## Not verified

List what this experiment did not test (directions, profiles, error cases, hosts).
