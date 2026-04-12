# ara-test

Standalone test harness for validating RTL patches to the [Ara](https://github.com/pulp-platform/ara) RISC-V vector unit.

Three simulation backends run the same tests:

| Backend | Purpose                   |
|---------|---------------------------|
| spike   | ISA golden reference      |
| base    | Upstream Ara RTL (bugs)  |
| fork    | Patched Ara RTL (fixes)   |

## Prerequisites

- LLVM with RISC-V target support (clang, ld.lld, llvm-objcopy)
- Verilator
- Python 3 with pytest

Set `LLVM_RISCV` to your LLVM bin directory:

```bash
export LLVM_RISCV=/opt/homebrew/Cellar/llvm/21.1.7/bin
```

## Quick start

```bash
./run.sh
```

## Tests

| File              | What it tests                                           |
|-------------------|---------------------------------------------------------|
| `test_smoke.py`   | Basic: return value, add, store/load                    |
| `test_hazard.py`  | RAW hazards: vfadd, vadd, vmseq, vmand, viota, vmsbf, vcpop |
| `test_vlen.py`    | VL trim: vcpop, vfirst, viota, vmsbf with vmset/vmclr   |

## Configuration

Default: `DLEN=128` (NrLanes=2, VLEN=2048). Override with:

```bash
./sh/build.sh --dlen=256   # NrLanes=4, VLEN=4096
```
