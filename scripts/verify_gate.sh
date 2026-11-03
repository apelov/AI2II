#!/usr/bin/env bash
# Layer-1 Mechanical Verification Gate for AI2II (ported from agentwork/scripts/verify_gate.sh)
# Runs lint, format, safe YAML syntax check, AST test-weakening inspection, DAG validation, and unit tests.

set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${HOME}/.local/bin:${PATH:-}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
export PYTHONPATH="${REPO_ROOT}:${REPO_ROOT}/src:${REPO_ROOT}/src/_shims:${PYTHONPATH:-}"

PYTHON_BIN="${PYTHON_BIN:-}"
if [ -z "$PYTHON_BIN" ]; then
    for cand in "/opt/anaconda3/bin/python3" "/opt/homebrew/bin/python3" "/usr/local/bin/python3" "/usr/bin/python3" "$(command -v python3 2>/dev/null || true)"; do
        if [ -n "$cand" ] && [ -x "$cand" ] && "$cand" -c "import sys" >/dev/null 2>&1; then
            PYTHON_BIN="$cand"
            break
        fi
    done
fi

echo "=== AI2II Mechanical Verification Gate ==="
echo ""

FAILED=0

# 1. Lint (Python)
echo "1. Running Python lint (ruff)..."
if command -v ruff >/dev/null 2>&1; then
    ruff check --no-cache orchestrator.py tests acceptance || FAILED=1
else
    echo "  FAIL: ruff not installed"
    FAILED=1
fi

# 2. Format check
echo "2. Checking format (ruff format)..."
if command -v ruff >/dev/null 2>&1; then
    ruff format --check orchestrator.py tests acceptance || FAILED=1
else
    echo "  FAIL: ruff not installed"
    FAILED=1
fi

# 3. Safe YAML syntax check (no shell interpolation, no subshell variable loss)
echo "3. Checking YAML syntax..."
if ! "$PYTHON_BIN" - "$REPO_ROOT" <<'EOF'
import sys
from pathlib import Path
import yaml

root = Path(sys.argv[1])
failed = False
for p in sorted(root.rglob("*")):
    if not p.is_file() or p.suffix not in (".yaml", ".yml"):
        continue
    rel_parts = p.relative_to(root).parts
    if any(part in (".git", ".worktrees", "__pycache__", ".ruff_cache") for part in rel_parts):
        continue
    try:
        with open(p, "r", encoding="utf-8") as f:
            yaml.safe_load(f)
    except Exception as exc:
        print(f"  YAML syntax error in {p.relative_to(root)}: {exc}", file=sys.stderr)
        failed = True

sys.exit(1 if failed else 0)
EOF
then
    FAILED=1
fi

# 4. AST Test-Weakening & Syntax Check (ported from agentwork verify_gate.sh)
echo "4. Inspecting test ASTs for stubs, skips, or syntax errors..."
if ! "$PYTHON_BIN" - "$REPO_ROOT" <<'EOF'
import ast
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
failed = False
for folder in ("tests", "acceptance"):
    base = root / folder
    if not base.is_dir():
        continue
    for tf in sorted(base.rglob("*.py")):
        rel = str(tf.relative_to(root))
        try:
            source = tf.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=rel)
        except Exception as e:
            print(f"  GATE FAIL: Failed to parse Python test file '{rel}': {e}", file=sys.stderr)
            failed = True
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func_str = ast.unparse(node.func) if hasattr(ast, "unparse") else ""
                if func_str in ("pytest.skip", "unittest.skip"):
                    print(f"  GATE FAIL: Test file '{rel}' calls {func_str}().", file=sys.stderr)
                    failed = True
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                stmts = [
                    s for s in node.body
                    if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
                ]
                if not stmts or (len(stmts) == 1 and isinstance(stmts[0], ast.Pass)):
                    print(f"  GATE FAIL: Test function '{node.name}' in '{rel}' is an empty stub.", file=sys.stderr)
                    failed = True
                for dec in node.decorator_list:
                    dec_target = dec.func if isinstance(dec, ast.Call) else dec
                    dec_str = ast.unparse(dec_target) if hasattr(ast, "unparse") else ""
                    if re.search(r"\b(skip|skipif|xfail)\b", dec_str):
                        print(f"  GATE FAIL: Test function '{node.name}' in '{rel}' uses skip/xfail ({dec_str}).", file=sys.stderr)
                        failed = True

sys.exit(1 if failed else 0)
EOF
then
    FAILED=1
fi

# 5. Milestone DAG & Ownership Self-Check
echo "5. Checking Milestone DAG and ownership enforcement..."
"$PYTHON_BIN" "$REPO_ROOT/orchestrator.py" validate || FAILED=1
"$PYTHON_BIN" "$REPO_ROOT/orchestrator.py" check-ownership builder M01 1 --files src/example.py >/dev/null || FAILED=1
if "$PYTHON_BIN" "$REPO_ROOT/orchestrator.py" check-ownership builder M01 1 --files acceptance/M01/test_m01.py >/dev/null 2>&1; then
    echo "  GATE FAIL: Builder ownership failed to reject acceptance/**"
    FAILED=1
fi

# 6. Required reports check for active milestones
echo "6. Checking required reports for active milestones..."
for milestone_dir in milestones/M*/; do
    milestone=$(basename "$milestone_dir")
    state_file="$milestone_dir/state.yaml"
    if [ -f "$state_file" ]; then
        status=$(grep "^status:" "$state_file" | awk '{print $2}' | tr -d '"'"'" || true)
        attempt=$(grep "^attempt:" "$state_file" | awk '{print $2}' | tr -d '"'"'" || echo "0")
        if [ "$status" = "BUILT" ] || [ "$status" = "VERIFYING" ] || [ "$status" = "VERIFIED" ]; then
            build_md="$milestone_dir/attempts/$(printf "%02d" "$attempt")/build.md"
            if [ ! -f "$build_md" ]; then
                echo "  MISSING: $build_md"
                FAILED=1
            fi
        fi
        if [ "$status" = "VERIFYING" ] || [ "$status" = "VERIFIED" ]; then
            verification_yaml="$milestone_dir/attempts/$(printf "%02d" "$attempt")/verification.yaml"
            if [ ! -f "$verification_yaml" ]; then
                echo "  MISSING: $verification_yaml"
                FAILED=1
            fi
        fi
    fi
done

# 7. Run unit tests
echo "7. Running unit tests..."
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 "$PYTHON_BIN" -m pytest -q -p no:cacheprovider tests/ || FAILED=1

echo ""
if [ "$FAILED" -eq 0 ]; then
    echo "=== GATE PASSED ==="
    exit 0
else
    echo "=== GATE FAILED ==="
    exit 1
fi
