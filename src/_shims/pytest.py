"""Zero-dependency pure-Python pytest runner fallback.
Used automatically when pytest is not installed in the active Python environment.
Supports node IDs (`path.py::ClassName::test_method` or `path.py::test_func`), directory discovery,
and standard pytest exit codes:
  0 = all tests passed
  1 = tests collected and run, but some failed
  4 = command line usage error / file or node not found
  5 = no tests were collected
"""

import importlib.util
import inspect
import sys
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any


class Skipped(Exception):
    """Raised when pytest.skip is called."""


def skip(reason: str = "") -> None:
    raise Skipped(reason)


class _Mark:
    @staticmethod
    def skip(reason: str = "") -> Callable[[Any], Any]:
        def dec(fn: Any) -> Any:
            fn._pytest_skip = reason
            return fn

        return dec


mark = _Mark()


def _load_module_from_path(file_path: Path) -> Any:
    mod_name = f"_test_mod_{file_path.stem}_{abs(hash(str(file_path.resolve())))}"
    spec = importlib.util.spec_from_file_location(mod_name, str(file_path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load spec for {file_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


def _collect_from_file(
    file_path: Path,
    class_filter: str | None = None,
    func_filter: str | None = None,
) -> list[tuple[str, Callable[[], Any]]]:
    module = _load_module_from_path(file_path)
    collected: list[tuple[str, Callable[[], Any]]] = []

    for name, obj in inspect.getmembers(module):
        if class_filter:
            if name != class_filter or not inspect.isclass(obj):
                continue
            instance = obj()
            for m_name, m_obj in inspect.getmembers(
                instance, predicate=inspect.ismethod
            ):
                if not m_name.startswith("test_"):
                    continue
                if func_filter and m_name != func_filter:
                    continue
                collected.append((f"{file_path}::{name}::{m_name}", m_obj))
        else:
            if inspect.isfunction(obj) and name.startswith("test_"):
                if func_filter and name != func_filter:
                    continue
                collected.append((f"{file_path}::{name}", obj))
            elif inspect.isclass(obj) and name.startswith("Test"):
                if func_filter is not None and not hasattr(obj, func_filter):
                    continue
                instance = obj()
                for m_name, m_obj in inspect.getmembers(
                    instance, predicate=inspect.ismethod
                ):
                    if not m_name.startswith("test_"):
                        continue
                    if func_filter and m_name != func_filter:
                        continue
                    collected.append((f"{file_path}::{name}::{m_name}", m_obj))
    return collected


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    targets: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-p", "-k", "-m", "-c", "--basetemp", "--rootdir"):
            i += 2
            continue
        if a.startswith("-"):
            i += 1
            continue
        targets.append(a)
        i += 1

    if not targets:
        targets = ["tests"]

    repo_root = Path.cwd().resolve()
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    all_tests: list[tuple[str, Callable[[], Any]]] = []
    for target in targets:
        parts = target.split("::")
        file_part = parts[0]
        p = Path(file_part)
        if not p.exists():
            print(f"ERROR: file or directory not found: {target}", file=sys.stderr)
            return 4

        if p.is_dir():
            for tf in sorted(p.rglob("test_*.py")):
                all_tests.extend(_collect_from_file(tf))
        elif p.is_file():
            cls_f = parts[1] if len(parts) == 3 else None
            fn_f = (
                parts[2] if len(parts) == 3 else (parts[1] if len(parts) == 2 else None)
            )
            found = _collect_from_file(p, class_filter=cls_f, func_filter=fn_f)
            if not found:
                print(f"ERROR: test node not found: {target}", file=sys.stderr)
                return 4
            all_tests.extend(found)

    if not all_tests:
        print("no tests ran")
        return 5

    passed = 0
    failed = 0
    skipped = 0
    failures: list[tuple[str, str]] = []

    for node_id, fn in all_tests:
        if hasattr(fn, "_pytest_skip"):
            skipped += 1
            sys.stdout.write("s")
            continue
        try:
            fn()
            passed += 1
            sys.stdout.write(".")
        except Skipped:
            skipped += 1
            sys.stdout.write("s")
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            failed += 1
            sys.stdout.write("F")
            failures.append((node_id, traceback.format_exc()))
        sys.stdout.flush()

    print()
    for node_id, tb in failures:
        print(f"=== FAIL: {node_id} ===")
        print(tb)

    summary = []
    if failed:
        summary.append(f"{failed} failed")
    if passed:
        summary.append(f"{passed} passed")
    if skipped:
        summary.append(f"{skipped} skipped")
    print(", ".join(summary))

    return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
