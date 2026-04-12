#!/bin/bash
# Common setup for all scripts. Source this, don't execute it.
ROOT_DIR="$(git rev-parse --show-toplevel)"

# ── LLVM toolchain check ─────────────────────────────────────────
# LLVM_RISCV must point to an LLVM bin/ directory with RISC-V support.
# e.g. export LLVM_RISCV=$HOME/install/llvm/bin

if [ -z "${LLVM_RISCV:-}" ]; then
    echo "error: LLVM_RISCV not set." >&2
    echo "  Set it to an LLVM bin/ directory with RISC-V target support." >&2
    echo "  e.g. export LLVM_RISCV=\$HOME/install/llvm/bin" >&2
    exit 1
fi

if [ ! -x "${LLVM_RISCV}/clang" ]; then
    echo "error: ${LLVM_RISCV}/clang not found or not executable." >&2
    exit 1
fi

# Verify RISC-V support (check clang and llvm-objdump)
if ! "${LLVM_RISCV}/clang" --print-targets 2>/dev/null | grep -q riscv; then
    echo "error: ${LLVM_RISCV}/clang does not support RISC-V target." >&2
    echo "  Check: \${LLVM_RISCV}/clang --print-targets | grep riscv" >&2
    echo "  Homebrew example: export LLVM_RISCV=/opt/homebrew/Cellar/llvm/21.1.7/bin" >&2
    exit 1
fi
if ! "${LLVM_RISCV}/llvm-objdump" --version 2>/dev/null | grep -q -i riscv; then
    echo "error: ${LLVM_RISCV}/llvm-objdump does not support RISC-V." >&2
    echo "  Check: \${LLVM_RISCV}/llvm-objdump --version | grep riscv" >&2
    exit 1
fi
