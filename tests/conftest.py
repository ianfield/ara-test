# pytest fixtures for ara-test.
#
# Backend selection:
#   --sim base    upstream ara (repo/ara-base)
#   --sim fork    patched ara (repo/ara-fork) [default]

import inspect
import os
import struct
import subprocess
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
CRT_DIR  = ROOT_DIR / "tests" / "crt"
BUILD_DIR = ROOT_DIR / "run"

# Import sim backends
import importlib.util  # noqa: E402

def _load_sim(subdir):
    spec = importlib.util.spec_from_file_location(
        f"sim_{subdir}", ROOT_DIR / "sims" / subdir / "sim.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

_hdl_sim = _load_sim("hdl")
_spike_sim = _load_sim("spike")
CoreSim = _hdl_sim.Sim
SpikeSim = _spike_sim.Sim

# ── Cross-compilation ─────────────────────────────────────────────

# RISC-V capable LLVM toolchain — set LLVM_RISCV to the bin/ directory
_LLVM_BIN = Path(os.environ.get("LLVM_RISCV", ""))
if not _LLVM_BIN.is_dir():
    raise RuntimeError("LLVM_RISCV not set or not a directory. "
                       "export LLVM_RISCV=/path/to/llvm/bin")
CLANG   = str(_LLVM_BIN / "clang")
OBJCOPY = str(_LLVM_BIN / "llvm-objcopy")

CLANG_FLAGS = [
    "--target=riscv64",
    "-march=rv64gcv",
    "-mabi=lp64d",
    "-mno-relax",
    "-O1",
    "-nostdlib",
    "-ffreestanding",
]


def compile_snippet(code: str) -> bytes:
    """Cross-compile a C snippet to a bare-metal RISC-V flat binary."""
    caller = inspect.stack()[1].function
    if caller.startswith('_'):
        caller = inspect.stack()[2].function
    # Derive module name from caller's file (test_smoke.py → test_smoke)
    caller_file = Path(inspect.stack()[1].filename).stem
    out = BUILD_DIR / caller_file / caller
    out.mkdir(parents=True, exist_ok=True)

    # Assemble CRT
    crt_o = out / "crt0.o"
    subprocess.run(
        [CLANG] + CLANG_FLAGS + ["-c", "-o", str(crt_o), str(CRT_DIR / "crt0.S")],
        check=True,
    )

    # Compile snippet
    test_c = out / "test.c"
    test_c.write_text(code)
    test_o = out / "test.o"
    subprocess.run(
        [CLANG] + CLANG_FLAGS + ["-c", "-o", str(test_o), str(test_c)],
        check=True,
    )

    # Link
    elf = out / "test.elf"
    subprocess.run(
        ["ld.lld", "-T", str(CRT_DIR / "test.ld"), "--gc-sections",
         str(crt_o), str(test_o), "-o", str(elf)],
        check=True,
    )

    # Extract flat binary
    binary = out / "test.bin"
    subprocess.run(
        [OBJCOPY, "-O", "binary", str(elf), str(binary)],
        check=True,
    )

    return binary.read_bytes()


def assert_ok(result):
    """Assert run completed without timeout or trap."""
    assert not result.timed_out, f"timed out after {result.cycles} cycles"
    assert not result.trapped, (
        f"trap: mcause={result.mcause:#x} mepc={result.mepc:#x} "
        f"mtval={result.mtval:#x}"
    )


# ── pytest hooks ──────────────────────────────────────────────────

def pytest_addoption(parser):
    parser.addoption(
        "--sim", default="fork",
        choices=["base", "fork", "spike"],
        help="Simulation backend (default: fork)",
    )


@pytest.fixture
def sim(request):
    """Per-test Sim instance."""
    backend = request.config.getoption("--sim")
    module = Path(request.node.module.__file__).stem
    name = request.node.name
    out_dir = BUILD_DIR / module / name
    out_dir.mkdir(parents=True, exist_ok=True)
    if backend == "spike":
        s = SpikeSim(name, str(out_dir), backend="spike")
    else:
        s = CoreSim(name, str(out_dir), backend=backend)
    yield s
    s.close()
