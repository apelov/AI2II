# Starting an AI2II project

Run one thing before any code, agent or checker exists:

```sh
python3 -m kickoff my-project          # asks what you want to achieve, then writes the rails
```

It asks these questions, and refuses answers that would break the rules (for example a checker
from the same model family as an implementation under test):

1. What do you want to achieve here?
2. If it works, what one-sentence result will you report?
3. What is explicitly out of scope?
4. Which document is the protocol authority?
5. Mode: interop of existing implementations, build one with agents, or both?
6. The implementations: name, directory, server or client, which model family wrote it, under test?
7. Which model family writes the checker?
8. Who reviews, with a tool that can run commands?
9. Will any result rest on recorded, simulated, mocked or partner-attested data?

It writes these files into the project directory:

| File | Read by | Purpose |
|---|---|---|
| `AGENTS.md` | Codex, Mistral Vibe, most agents; humans | the contract: rules, claim classes, commands |
| `CLAUDE.md`, `GEMINI.md` | Claude Code, Gemini CLI | one line: read `AGENTS.md` first |
| `PROJECT.md` | everyone | the answers, independence warnings, Open Issues, decision log |
| `interop.yaml` | `wire` | a skeleton; `wire` refuses it until the checker and negatives exist |
| `PROVENANCE.yaml` | reviewers, `wire` users | who wrote which artifact, with which model and prompt |
| `RESULTS.md` | everyone | results by claim class, not-run items, review triage |

Commit them. From then on every agent that opens the repository finds the rails without being
told.

## If you start in an agent session instead of a terminal

Paste this as the first message of the session:

```text
This project follows AI2II. Before anything else:
1. If AGENTS.md exists in this repository, read PROJECT.md and AGENTS.md, state the goal back to
   me in one sentence, and wait for my confirmation.
2. Otherwise run `python3 -m kickoff --questions`, ask me every question it lists, one message
   at a time, and do not guess any answer. Write my answers to answers.yaml, run
   `python3 -m kickoff . --answers answers.yaml`, show me the warnings, and stop.
Follow AGENTS.md for all later work: no interop claim without a wire bundle, a claim class on
every result, provenance for every artifact, and a list of what you could not verify.
```

`kickoff` and `wire` come from an AI2II checkout: run them from it, or put it on `PYTHONPATH`
(`PYTHONPATH=/path/to/AI2II python3 -m kickoff .`). `kickoff` only writes files; it is kept
separate from `wire`, which runs the evidence.
