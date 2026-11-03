"""Experiment manifest loading and validation (DESIGN.md 24.20). Errors exit 2 before anything runs."""

import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .bundle import DECRYPT_LOG, SECRETS_DIR, sha256_file
from .bundle import DECRYPTED as DECRYPTED_FILE

CAPTURE = "{capture}"
SECRETS = "{secrets}"
DECRYPTED = "{decrypted}"
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_SECRET = re.compile(r"[A-Za-z0-9._-]+")


def secret_name_ok(value: Any) -> bool:
    """A secret is a plain file name directly under secrets/."""
    return (
        isinstance(value, str)
        and _SECRET.fullmatch(value) is not None
        and value not in (".", "..")
    )


class ManifestError(Exception):
    """Usage or manifest error (exit 2)."""


@dataclass
class Manifest:
    path: Path
    root: Path  # the experiment directory: holds the manifest and the checkers
    sha256: str
    env_checks: list[dict[str, Any]]
    peers: dict[str, dict[str, Any]]
    capture: dict[str, Any]
    cells: dict[str, dict[str, Any]]
    checkers: dict[str, dict[str, Any]]
    decrypt: dict[str, Any] | None = None
    secured: bool = False  # secrets/ is created before the peers start


def substitute(
    text: str,
    bundle: Path,
    capture: Path,
    inputs: Path,
    secrets: Path | None = None,
    decrypted: Path | None = None,
) -> str:
    """Replace the placeholders in text. secrets and decrypted default to the bundle's own."""
    subs = {
        "{bundle}": str(bundle),
        CAPTURE: str(capture),
        "{inputs}": str(inputs),
        SECRETS: str(secrets or bundle / SECRETS_DIR),
        DECRYPTED: str(decrypted or bundle / DECRYPTED_FILE),
    }
    for key, val in subs.items():
        text = text.replace(key, val)
    return text


def expand(command: str, *args: Path | None) -> list[str]:
    """Split a manifest command into argv and substitute the placeholders (see substitute)."""
    return [substitute(tok, *args) for tok in shlex.split(command)]  # type: ignore[arg-type]


class _Check:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def err(self, msg: str) -> None:
        self.errors.append(msg)

    def string(self, d: dict[str, Any], key: str, where: str) -> str:
        v = d.get(key)
        if not isinstance(v, str) or not v.strip():
            self.err(f"{where}: '{key}' must be a non-empty string")
            return ""
        return v

    def command(self, d: dict[str, Any], key: str, where: str) -> str:
        v = self.string(d, key, where)
        try:
            if v and not shlex.split(v):
                raise ValueError("empty")
        except ValueError:
            self.err(f"{where}: '{key}' is not a valid command")
        return v

    def name(self, d: dict[str, Any], kind: str, seen: set[str]) -> str:
        v = d.get("name")
        if not isinstance(v, str) or not _NAME.match(v):
            self.err(f"{kind}: 'name' must match {_NAME.pattern}")
            return ""
        if v in seen:
            self.err(f"duplicate {kind} name: {v}")
        seen.add(v)
        return v

    def rel_file(self, root: Path, value: Any, where: str) -> str:
        if not isinstance(value, str) or not value:
            self.err(f"{where}: path must be a non-empty string")
            return ""
        norm = os.path.normpath(value)
        if os.path.isabs(norm) or norm == ".." or norm.startswith(".." + os.sep):
            self.err(f"{where}: path escapes the experiment directory: {value}")
        elif not (root / norm).is_file():
            self.err(f"{where}: file does not exist: {value}")
        return Path(norm).as_posix()


def _list(c: _Check, d: dict[str, Any], key: str, where: str) -> list[Any]:
    v = d.get(key)
    if not isinstance(v, list):
        c.err(f"{where}: '{key}' must be a list")
        return []
    return v


def _dicts(c: _Check, items: list[Any], kind: str) -> list[dict[str, Any]]:
    out = []
    for item in items:
        if isinstance(item, dict):
            out.append(item)
        else:
            c.err(f"{kind}: entries must be mappings")
    return out


def load(path: str | Path) -> Manifest:
    path = Path(path).resolve()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        sha = sha256_file(path)
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
        raise ManifestError(f"cannot read manifest {path}: {e}") from e
    if not isinstance(data, dict):
        raise ManifestError(f"{path}: manifest must be a mapping")
    root = path.parent
    c = _Check()

    env_checks = []
    seen: set[str] = set()
    for e in _dicts(c, _list(c, data, "env_checks", "manifest"), "env_checks"):
        name = c.name(e, "env check", seen)
        env_checks.append({"name": name, "command": c.command(e, "command", name)})

    peers: dict[str, dict[str, Any]] = {}
    all_secrets: set[str] = set()
    seen = set()
    for p in _dicts(c, _list(c, data, "peers", "manifest"), "peers"):
        name = c.name(p, "peer", seen)
        where = f"peer {name}"
        if not isinstance(p.get("under_test"), bool):
            c.err(f"{where}: 'under_test' must be a boolean")
        bins = p.get("binaries", [])
        if not isinstance(bins, list) or not all(
            isinstance(b, str) and b for b in bins
        ):
            c.err(f"{where}: 'binaries' must be a list of paths")
            bins = []
        ready = p.get("ready")
        if ready is not None:
            if not isinstance(ready, dict) or not isinstance(
                ready.get("timeout_s"), (int, float)
            ):
                c.err(f"{where}: 'ready' needs 'command' and a numeric 'timeout_s'")
            else:
                c.command(ready, "command", where)
        build = p.get("build")
        if build is not None:
            c.command(p, "build", where)
        env = p.get("env", {})
        if not isinstance(env, dict) or not all(
            isinstance(k, str)
            and k
            and "=" not in k
            and "\0" not in k
            and isinstance(v, str)
            and "\0" not in v
            for k, v in env.items()
        ):
            c.err(f"{where}: 'env' must be a mapping of strings")
            env = {}
        secrets = p.get("secrets", [])
        if not isinstance(secrets, list):
            c.err(f"{where}: 'secrets' must be a list of file names")
            secrets = []
        for sname in secrets:
            if not secret_name_ok(sname):
                c.err(f"{where}: invalid secret name: {sname!r}")
            elif sname in all_secrets:
                c.err(f"{where}: secret declared twice: {sname}")
            else:
                all_secrets.add(sname)
        peers[name] = {
            "name": name,
            "path": (root / c.string(p, "path", where)).resolve(),
            "family": c.string(p, "family", where),
            "under_test": p.get("under_test"),
            "build": build,
            "binaries": bins,
            "start": c.command(p, "start", where),
            "ready": ready,
            "env": env,
            "secrets": [x for x in secrets if secret_name_ok(x)],
        }

    cap = data.get("capture")
    if not isinstance(cap, dict):
        c.err("manifest: 'capture' must be a mapping")
        cap = {}
    capture = {
        "interface": c.string(cap, "interface", "capture"),
        "filter": cap.get("filter", ""),
    }
    if not isinstance(capture["filter"], str):
        c.err("capture: 'filter' must be a string")

    decrypt: dict[str, Any] | None = None
    if "decrypt" in data:
        d = data["decrypt"]
        if isinstance(d, dict):
            decrypt = {"command": c.command(d, "command", "decrypt")}
        else:
            c.err("manifest: 'decrypt' must be a mapping with a 'command'")
            decrypt = {"command": ""}

    checkers: dict[str, dict[str, Any]] = {}
    seen = set()
    for k in _dicts(c, _list(c, data, "checkers", "manifest"), "checkers"):
        name = c.name(k, "checker", seen)
        where = f"checker {name}"
        if not isinstance(k.get("observes_capture"), bool):
            c.err(f"{where}: 'observes_capture' must be a boolean")
        inputs = [
            c.rel_file(root, i, f"{where} input") for i in _list(c, k, "inputs", where)
        ]
        observes_dec = k.get("observes_decrypted", False)
        if not isinstance(observes_dec, bool):
            c.err(f"{where}: 'observes_decrypted' must be a boolean")
            observes_dec = False
        command = c.command(k, "command", where)
        uses_decrypted = DECRYPTED in command
        neg_secret = neg_decrypted = asserts_encrypted = False
        negatives = []
        raw_negs = _list(c, k, "negatives", where)
        if not raw_negs:
            c.err(f"{where}: needs at least one negative")
        for n in _dicts(c, raw_negs, f"{where} negatives"):
            neg_in = c.rel_file(root, n.get("input"), f"{where} negative input")
            repl = n.get("replaces")
            asserts = n.get("asserts")
            if asserts is not None and asserts != "encrypted":
                c.err(f"{where}: 'asserts' must be 'encrypted', got {asserts!r}")
                asserts = None
            if asserts == "encrypted":
                asserts_encrypted = True
                if repl != CAPTURE:
                    c.err(
                        f"{where}: an 'asserts: encrypted' negative replaces {CAPTURE}"
                    )
            if repl == DECRYPTED or (
                isinstance(repl, str) and repl.startswith(SECRETS + "/")
            ):
                if not observes_dec:
                    c.err(
                        f"{where}: only an observes_decrypted checker may replace {repl}"
                    )
                if repl == DECRYPTED:
                    neg_decrypted = uses_decrypted = True
                else:
                    sname = repl[len(SECRETS) + 1 :]
                    if not secret_name_ok(sname):
                        c.err(f"{where}: invalid secret name in negative: {repl}")
                    elif sname not in all_secrets:
                        c.err(f"{where}: negative replaces undeclared secret: {sname}")
                    else:
                        neg_secret = True
            elif repl != CAPTURE:
                repl = (
                    c.rel_file(root, repl, f"{where} negative replaces") if repl else ""
                )
                if repl not in inputs:
                    c.err(f"{where}: negative replaces neither an input nor {CAPTURE}")
            negatives.append({"input": neg_in, "replaces": repl, "asserts": asserts})
        n_cap = sum(1 for n in negatives if n["replaces"] == CAPTURE)
        if k.get("observes_capture") is True and n_cap < 2:
            c.err(f"{where}: an observes_capture checker needs >= 2 capture negatives")
        if observes_dec and not (neg_secret and neg_decrypted):
            c.err(
                f"{where}: an observes_decrypted checker needs a negative replacing "
                f"a {SECRETS}/<file> and one replacing {DECRYPTED}"
            )
        if (observes_dec or uses_decrypted) and decrypt is None:
            c.err(f"{where}: uses the decrypted view but the experiment has no decrypt")
        checkers[name] = {
            "name": name,
            "family": c.string(k, "family", where),
            "observes_capture": k.get("observes_capture"),
            "observes_decrypted": observes_dec,
            "asserts_encrypted": asserts_encrypted,
            "command": command,
            "inputs": inputs,
            "negatives": negatives,
        }

    for k in checkers.values():
        for p in peers.values():
            if p["under_test"] is True and k["family"] and k["family"] == p["family"]:
                c.err(
                    f"checker {k['name']}: family equals under_test peer {p['name']}'s family"
                )

    cells: dict[str, dict[str, Any]] = {}
    seen = set()
    for cell in _dicts(c, _list(c, data, "cells", "manifest"), "cells"):
        name = c.name(cell, "cell", seen)
        where = f"cell {name}"
        server = cell.get("server")
        clients = cell.get("clients")
        names = cell.get("checkers")
        if not isinstance(server, str) or not server:
            c.err(f"{where}: needs a server")
        if not isinstance(clients, list) or not clients:
            c.err(f"{where}: needs at least one client")
            clients = []
        if not isinstance(names, list):
            c.err(f"{where}: 'checkers' must be a list")
            names = []
        if len(set(map(str, clients))) != len(clients):
            c.err(f"{where}: names the same client twice")
        if server in clients:
            c.err(f"{where}: client equals its server")
        for p in [server, *clients]:
            if isinstance(server, str) and p not in peers:
                c.err(f"{where}: undefined peer {p}")
        for k in names:
            if k not in checkers:
                c.err(f"{where}: undefined checker {k}")
        if not any(checkers.get(k, {}).get("observes_capture") is True for k in names):
            c.err(f"{where}: no observes_capture checker among its checkers")
        if decrypt is not None:
            if not any(checkers.get(k, {}).get("observes_decrypted") for k in names):
                c.err(f"{where}: no observes_decrypted checker among its checkers")
            for k in names:
                chk = checkers.get(k, {})
                if chk.get("observes_capture") is True and not chk["asserts_encrypted"]:
                    c.err(
                        f"{where}: checker {k} has no negative marked 'asserts: encrypted'"
                    )
        timeout = cell.get("timeout_s")
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or timeout <= 0
        ):
            c.err(f"{where}: 'timeout_s' must be a positive number")
        cells[name] = {
            "name": name,
            "server": server,
            "clients": clients,
            "checkers": names,
            "timeout_s": timeout,
        }

    produced: set[str] = {DECRYPT_LOG} if decrypt is not None else set()
    for p in peers:
        for fname in (f"{p}.log",):
            if fname in produced:
                c.err(f"bundle file name collision: {fname}")
            produced.add(fname)
    for k in checkers:
        fname = f"checker-{k}.log"
        if fname in produced:
            c.err(f"bundle file name collision: {fname}")
        produced.add(fname)
    if "capture" in peers:
        c.err("peer name 'capture' is reserved")

    if c.errors:
        raise ManifestError("\n".join(c.errors))
    commands = [k["command"] for k in checkers.values()]
    for p in peers.values():
        commands += [
            p["start"],
            p["build"] or "",
            (p["ready"] or {}).get("command", ""),
        ]
    secured = (
        decrypt is not None
        or any(p["env"] or p["secrets"] for p in peers.values())
        or any(SECRETS in cmd for cmd in commands)
    )
    return Manifest(
        path, root, sha, env_checks, peers, capture, cells, checkers, decrypt, secured
    )
