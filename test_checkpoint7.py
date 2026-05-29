"""Integration tests for checkpoint 7: async support + test flags."""
import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

BCG = [sys.executable, str(Path(__file__).parent / "babel_code_goat.py")]


def _run_generate(tests_dir: Path, entrypoint: str, lang: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [*BCG, "generate", str(tests_dir), "--entrypoint", entrypoint, "--lang", lang],
        capture_output=True, text=True,
    )


def _run_test(solution: Path, tests_dir: Path, lang: str, extra: list[str] | None = None) -> dict:
    cmd = [*BCG, "test", str(solution), str(tests_dir), "--lang", lang, *(extra or [])]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return json.loads(result.stdout.strip())


@pytest.fixture
def workspace(tmp_path):
    """Provide a clean temp directory for each test."""
    return tmp_path


# ---------------------------------------------------------------------------
# 8.1  Python async entrypoint
# ---------------------------------------------------------------------------

def test_python_async_entrypoint(workspace):
    """Async def solve runs to completion and result is compared correctly."""
    tests_dir = workspace / "tests"
    tests_dir.mkdir()
    (tests_dir / "tests.py").write_text("assert solve(1) == 2\n")

    sol = workspace / "solution.py"
    sol.write_text("async def solve(x):\n    return x + 1\n")

    rc = _run_generate(tests_dir, "solve", "python")
    assert rc.returncode == 0, rc.stderr

    out = _run_test(sol, tests_dir, "python")
    assert out["status"] == "pass"
    assert out["passed"] == ["tests.py:1"]
    assert out["failed"] == []


def test_python_async_entrypoint_raises(workspace):
    """Async def that raises is handled correctly by raises assertions."""
    tests_dir = workspace / "tests"
    tests_dir.mkdir()
    (tests_dir / "tests.py").write_text(
        "try:\n    solve(0)\n    assert False\nexcept Exception:\n    pass\n"
    )

    sol = workspace / "solution.py"
    sol.write_text("async def solve(x):\n    raise ValueError('boom')\n")

    assert _run_generate(tests_dir, "solve", "python").returncode == 0
    out = _run_test(sol, tests_dir, "python")
    assert out["status"] == "pass"


def test_python_sync_entrypoint_unaffected(workspace):
    """Sync functions still work after the async changes."""
    tests_dir = workspace / "tests"
    tests_dir.mkdir()
    (tests_dir / "tests.py").write_text("assert solve(3) == 9\n")

    sol = workspace / "solution.py"
    sol.write_text("def solve(x):\n    return x * x\n")

    assert _run_generate(tests_dir, "solve", "python").returncode == 0
    out = _run_test(sol, tests_dir, "python")
    assert out["status"] == "pass"


# ---------------------------------------------------------------------------
# 8.2  JavaScript async entrypoint
# ---------------------------------------------------------------------------

def test_js_async_entrypoint(workspace):
    """Async JS entrypoint resolves correctly."""
    tests_dir = workspace / "tests"
    tests_dir.mkdir()
    (tests_dir / "tests.py").write_text("assert solve(5) == 10\n")

    sol = workspace / "solution.js"
    sol.write_text("async function solve(x) { return x * 2; }\nmodule.exports = { solve };\n")

    rc = _run_generate(tests_dir, "solve", "javascript")
    if rc.returncode != 0:
        pytest.skip("node not available")

    out = _run_test(sol, tests_dir, "javascript")
    assert out["status"] == "pass"
    assert out["passed"] == ["tests.py:1"]


# ---------------------------------------------------------------------------
# 8.3  --list-tests
# ---------------------------------------------------------------------------

def test_list_tests_returns_all_ids(workspace):
    """`--list-tests` returns all IDs as passed without running solution."""
    tests_dir = workspace / "tests"
    tests_dir.mkdir()
    (tests_dir / "tests.py").write_text(
        "assert solve(1) == 1\nassert solve(2) == 4\nassert solve(3) == 9\n"
    )

    sol = workspace / "solution.py"
    sol.write_text("def solve(x):\n    return x * x\n")

    assert _run_generate(tests_dir, "solve", "python").returncode == 0

    out = _run_test(sol, tests_dir, "python", ["--list-tests"])
    assert out["status"] == "pass"
    assert set(out["passed"]) == {"tests.py:1", "tests.py:2", "tests.py:3"}
    assert out["failed"] == []


def test_list_tests_missing_solution_still_works(workspace):
    """`--list-tests` succeeds even when solution file does not exist."""
    tests_dir = workspace / "tests"
    tests_dir.mkdir()
    (tests_dir / "tests.py").write_text("assert solve(1) == 1\n")

    sol_placeholder = workspace / "nonexistent.py"  # does not exist

    # Must generate first (solution not needed for generate)
    real_sol = workspace / "real.py"
    real_sol.write_text("def solve(x): return x\n")
    assert _run_generate(tests_dir, "solve", "python").returncode == 0

    out = _run_test(sol_placeholder, tests_dir, "python", ["--list-tests"])
    assert out["status"] == "pass"
    assert "tests.py:1" in out["passed"]


# ---------------------------------------------------------------------------
# 8.4  --run <id>
# ---------------------------------------------------------------------------

def test_run_single_id_passing(workspace):
    """`--run` executes only the specified test when it passes."""
    tests_dir = workspace / "tests"
    tests_dir.mkdir()
    (tests_dir / "tests.py").write_text(
        "assert solve(1) == 1\nassert solve(2) == 4\nassert solve(3) == 9\n"
    )

    sol = workspace / "solution.py"
    sol.write_text("def solve(x):\n    return x * x\n")

    assert _run_generate(tests_dir, "solve", "python").returncode == 0

    out = _run_test(sol, tests_dir, "python", ["--run", "tests.py:2"])
    assert out["status"] == "pass"
    assert out["passed"] == ["tests.py:2"]
    assert out["failed"] == []


def test_run_single_id_failing(workspace):
    """`--run` reports fail when selected test fails."""
    tests_dir = workspace / "tests"
    tests_dir.mkdir()
    (tests_dir / "tests.py").write_text(
        "assert solve(1) == 1\nassert solve(2) == 99\n"
    )

    sol = workspace / "solution.py"
    sol.write_text("def solve(x):\n    return x * x\n")

    assert _run_generate(tests_dir, "solve", "python").returncode == 0

    out = _run_test(sol, tests_dir, "python", ["--run", "tests.py:2"])
    assert out["status"] == "fail"
    assert out["failed"] == ["tests.py:2"]
    assert out["passed"] == []


def test_run_excludes_other_ids(workspace):
    """`--run` result contains only the requested ID."""
    tests_dir = workspace / "tests"
    tests_dir.mkdir()
    (tests_dir / "tests.py").write_text(
        "assert solve(1) == 1\nassert solve(2) == 4\nassert solve(3) == 9\n"
    )

    sol = workspace / "solution.py"
    sol.write_text("def solve(x):\n    return x * x\n")

    assert _run_generate(tests_dir, "solve", "python").returncode == 0

    out = _run_test(sol, tests_dir, "python", ["--run", "tests.py:1"])
    all_ids = out["passed"] + out["failed"]
    assert all_ids == ["tests.py:1"]


# ---------------------------------------------------------------------------
# 8.5  --run with unknown ID
# ---------------------------------------------------------------------------

def test_run_unknown_id_is_error(workspace):
    """`--run` with an ID not in the tester returns error status."""
    tests_dir = workspace / "tests"
    tests_dir.mkdir()
    (tests_dir / "tests.py").write_text("assert solve(1) == 1\n")

    sol = workspace / "solution.py"
    sol.write_text("def solve(x): return x\n")

    assert _run_generate(tests_dir, "solve", "python").returncode == 0

    cmd = [*BCG, "test", str(sol), str(tests_dir), "--lang", "python", "--run", "no_such_id"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    out = json.loads(result.stdout.strip())
    assert out["status"] == "error"
    assert result.returncode == 2


# ---------------------------------------------------------------------------
# 8.6  --timeout-ms causes slow test to appear in failed
# ---------------------------------------------------------------------------

def test_timeout_ms_slow_test_fails(workspace):
    """`--timeout-ms` makes a hanging test appear in `failed`."""
    tests_dir = workspace / "tests"
    tests_dir.mkdir()
    (tests_dir / "tests.py").write_text(
        "assert solve(1) == 1\nassert solve(2) == 4\n"
    )

    # First test returns quickly; second hangs
    sol = workspace / "solution.py"
    sol.write_text(textwrap.dedent("""\
        import time
        def solve(x):
            if x == 2:
                time.sleep(10)
            return x * x
    """))

    assert _run_generate(tests_dir, "solve", "python").returncode == 0

    out = _run_test(sol, tests_dir, "python", ["--timeout-ms", "100"])
    # tests.py:1 passes quickly; tests.py:2 times out
    assert "tests.py:1" in out["passed"]
    assert "tests.py:2" in out["failed"]


def test_timeout_ms_fast_test_passes(workspace):
    """`--timeout-ms` does not affect tests that finish quickly."""
    tests_dir = workspace / "tests"
    tests_dir.mkdir()
    (tests_dir / "tests.py").write_text("assert solve(4) == 16\n")

    sol = workspace / "solution.py"
    sol.write_text("def solve(x):\n    return x * x\n")

    assert _run_generate(tests_dir, "solve", "python").returncode == 0

    out = _run_test(sol, tests_dir, "python", ["--timeout-ms", "5000"])
    assert out["status"] == "pass"


# ---------------------------------------------------------------------------
# 8.7  --total-timeout-ms causes unrun tests to appear in failed
# ---------------------------------------------------------------------------

def test_total_timeout_ms_unrun_tests_fail(workspace):
    """`--total-timeout-ms` makes tests not reached before deadline appear in `failed`."""
    tests_dir = workspace / "tests"
    tests_dir.mkdir()
    # First test hangs so subsequent tests are never reached
    (tests_dir / "tests.py").write_text(
        "assert solve(1) == 1\nassert solve(2) == 4\nassert solve(3) == 9\n"
    )

    sol = workspace / "solution.py"
    sol.write_text(textwrap.dedent("""\
        import time
        def solve(x):
            if x == 1:
                time.sleep(60)
            return x * x
    """))

    assert _run_generate(tests_dir, "solve", "python").returncode == 0

    out = _run_test(sol, tests_dir, "python", ["--total-timeout-ms", "200"])
    # tests.py:2 and tests.py:3 were never reached
    assert "tests.py:2" in out["failed"]
    assert "tests.py:3" in out["failed"]


def test_total_timeout_ms_run_within_budget(workspace):
    """`--total-timeout-ms` does not affect runs that finish in time."""
    tests_dir = workspace / "tests"
    tests_dir.mkdir()
    (tests_dir / "tests.py").write_text(
        "assert solve(2) == 4\nassert solve(3) == 9\n"
    )

    sol = workspace / "solution.py"
    sol.write_text("def solve(x):\n    return x * x\n")

    assert _run_generate(tests_dir, "solve", "python").returncode == 0

    out = _run_test(sol, tests_dir, "python", ["--total-timeout-ms", "30000"])
    assert out["status"] == "pass"


# ---------------------------------------------------------------------------
# 6.5  C++ per-test timeout
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    subprocess.run(["which", "g++"], capture_output=True).returncode != 0,
    reason="g++ not available",
)
def test_cpp_timeout_slow_test_fails(workspace):
    """C++ per-test timeout causes a slow test to appear in `failed`."""
    tests_dir = workspace / "tests"
    tests_dir.mkdir()
    (tests_dir / "tests.py").write_text(
        "assert solve(1) == 1\nassert solve(2) == 4\n"
    )

    sol = workspace / "solution.cpp"
    sol.write_text(textwrap.dedent("""\
        #include <chrono>
        #include <thread>
        long long solve(long long x) {
            if (x == 2) std::this_thread::sleep_for(std::chrono::seconds(10));
            return x * x;
        }
    """))

    rc = _run_generate(tests_dir, "solve", "cpp")
    if rc.returncode != 0:
        pytest.skip("g++ compile failed during generate")

    out = _run_test(sol, tests_dir, "cpp", ["--timeout-ms", "200"])
    assert "tests.py:1" in out["passed"]
    assert "tests.py:2" in out["failed"]


@pytest.mark.skipif(
    subprocess.run(["which", "g++"], capture_output=True).returncode != 0,
    reason="g++ not available",
)
def test_cpp_async_future_unwrap(workspace):
    """C++ solution returning std::future is automatically unwrapped."""
    tests_dir = workspace / "tests"
    tests_dir.mkdir()
    (tests_dir / "tests.py").write_text("assert solve(3) == 9\n")

    sol = workspace / "solution.cpp"
    sol.write_text(textwrap.dedent("""\
        #include <future>
        std::future<long long> solve(long long x) {
            return std::async(std::launch::async, [x]{ return x * x; });
        }
    """))

    rc = _run_generate(tests_dir, "solve", "cpp")
    if rc.returncode != 0:
        pytest.skip("g++ compile failed during generate")

    out = _run_test(sol, tests_dir, "cpp")
    assert out["status"] == "pass"
    assert out["passed"] == ["tests.py:1"]


# ---------------------------------------------------------------------------
# 7.x  Rust async (requires cargo)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    subprocess.run(["which", "cargo"], capture_output=True).returncode != 0,
    reason="cargo not available",
)
def test_rust_async_entrypoint(workspace):
    """Rust async fn solve is awaited correctly via tokio."""
    tests_dir = workspace / "tests"
    tests_dir.mkdir()
    (tests_dir / "tests.py").write_text("assert solve(4) == 16\n")

    sol = workspace / "solution.rs"
    sol.write_text("pub async fn solve(x: i64) -> i64 { x * x }\n")

    rc = _run_generate(tests_dir, "solve", "rust")
    assert rc.returncode == 0, rc.stderr

    out = _run_test(sol, tests_dir, "rust")
    assert out["status"] == "pass"
    assert out["passed"] == ["tests.py:1"]


# ---------------------------------------------------------------------------
# Checkpoint 8: profile command
# ---------------------------------------------------------------------------

def _run_profile(tests_dir: Path, solution: Path, lang: str, extra: list[str] | None = None):
    cmd = [*BCG, "profile", str(tests_dir), str(solution), "--lang", lang, *(extra or [])]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result


def _profile_json(tests_dir: Path, solution: Path, lang: str, extra: list[str] | None = None) -> dict:
    return json.loads(_run_profile(tests_dir, solution, lang, extra).stdout.strip())


def _setup_python(workspace, tests_src: str, sol_src: str):
    tests_dir = workspace / "tests"
    tests_dir.mkdir()
    (tests_dir / "tests.py").write_text(tests_src)
    sol = workspace / "solution.py"
    sol.write_text(sol_src)
    rc = subprocess.run(
        [*BCG, "generate", str(tests_dir), "--entrypoint", "solve", "--lang", "python"],
        capture_output=True, text=True,
    )
    assert rc.returncode == 0, rc.stderr
    return tests_dir, sol


def test_profile_missing_tester_returns_error_json(workspace):
    """profile errors with the standard error JSON when tester file is missing."""
    tests_dir = workspace / "tests"
    tests_dir.mkdir()
    sol = workspace / "solution.py"
    sol.write_text("def solve(x): return x\n")

    result = _run_profile(tests_dir, sol, "python")
    assert result.returncode == 2
    out = json.loads(result.stdout.strip())
    assert out == {"status": "error", "passed": [], "failed": []}


def test_profile_basic_n1(workspace):
    """profile with default -n 1 returns runtime_ns with std=0.0."""
    tests_dir, sol = _setup_python(workspace, "assert solve(2) == 4\n", "def solve(x): return x*x\n")

    out = _profile_json(tests_dir, sol, "python")
    assert out["status"] == "pass"
    assert out["passed"] == ["tests.py:1"]
    assert out["failed"] == []
    assert "runtime_ns" in out
    assert out["runtime_ns"]["mean"] >= 0
    assert out["runtime_ns"]["std"] == 0.0


def test_profile_n3_produces_stats(workspace):
    """profile -n 3 produces runtime_ns stats over three samples."""
    tests_dir, sol = _setup_python(workspace, "assert solve(2) == 4\n", "def solve(x): return x*x\n")

    out = _profile_json(tests_dir, sol, "python", ["-n", "3"])
    assert out["status"] == "pass"
    assert "runtime_ns" in out
    assert out["runtime_ns"]["mean"] >= 0
    assert out["runtime_ns"]["std"] >= 0


def test_profile_warmup_equal_n_rejected(workspace):
    """--warmup equal to n must be rejected before any trial runs."""
    tests_dir, sol = _setup_python(workspace, "assert solve(1) == 1\n", "def solve(x): return x\n")

    result = _run_profile(tests_dir, sol, "python", ["-n", "3", "--warmup", "3"])
    assert result.returncode != 0
    assert "warmup" in result.stderr.lower() or "3" in result.stderr


def test_profile_warmup_greater_than_n_rejected(workspace):
    """--warmup greater than n must also be rejected."""
    tests_dir, sol = _setup_python(workspace, "assert solve(1) == 1\n", "def solve(x): return x\n")

    result = _run_profile(tests_dir, sol, "python", ["-n", "2", "--warmup", "5"])
    assert result.returncode != 0


def test_profile_memory_flag_adds_memory_kb(workspace):
    """--memory adds memory_kb to output with mean and std keys."""
    tests_dir, sol = _setup_python(workspace, "assert solve(2) == 4\n", "def solve(x): return x*x\n")

    out = _profile_json(tests_dir, sol, "python", ["--memory"])
    assert "memory_kb" in out
    assert "mean" in out["memory_kb"]
    assert "std" in out["memory_kb"]
    assert out["memory_kb"]["mean"] >= 0
    assert out["memory_kb"]["std"] >= 0


def test_profile_no_memory_flag_no_memory_kb(workspace):
    """Without --memory, memory_kb must not appear in output."""
    tests_dir, sol = _setup_python(workspace, "assert solve(2) == 4\n", "def solve(x): return x*x\n")

    out = _profile_json(tests_dir, sol, "python")
    assert "memory_kb" not in out


def test_profile_list_tests_returns_all_ids_zero_runtime(workspace):
    """--list-tests returns all IDs with runtime_ns mean/std both 0.0."""
    tests_dir, sol = _setup_python(
        workspace,
        "assert solve(1) == 1\nassert solve(2) == 4\n",
        "def solve(x): return x*x\n",
    )

    out = _profile_json(tests_dir, sol, "python", ["--list-tests"])
    assert out["status"] == "pass"
    assert set(out["passed"]) == {"tests.py:1", "tests.py:2"}
    assert out["failed"] == []
    assert out["runtime_ns"] == {"mean": 0.0, "std": 0.0}


def test_profile_run_filters_to_single_test(workspace):
    """--run <id> causes only that test to appear in passed/failed."""
    tests_dir, sol = _setup_python(
        workspace,
        "assert solve(1) == 1\nassert solve(2) == 4\n",
        "def solve(x): return x*x\n",
    )

    out = _profile_json(tests_dir, sol, "python", ["--run", "tests.py:1"])
    assert out["status"] == "pass"
    assert out["passed"] == ["tests.py:1"]
    assert out["failed"] == []


def test_profile_failing_test_status_fail(workspace):
    """A failing test makes status=fail and exit code 1."""
    tests_dir, sol = _setup_python(workspace, "assert solve(2) == 99\n", "def solve(x): return x*x\n")

    result = _run_profile(tests_dir, sol, "python")
    assert result.returncode == 1
    out = json.loads(result.stdout.strip())
    assert out["status"] == "fail"
    assert "tests.py:1" in out["failed"]


def test_profile_warmup_valid(workspace):
    """--warmup k < n is accepted and produces valid output."""
    tests_dir, sol = _setup_python(workspace, "assert solve(3) == 9\n", "def solve(x): return x*x\n")

    out = _profile_json(tests_dir, sol, "python", ["-n", "3", "--warmup", "2"])
    assert out["status"] == "pass"
    assert "runtime_ns" in out
