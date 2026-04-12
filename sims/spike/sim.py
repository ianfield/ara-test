# Python ctypes wrapper for bare-metal simulation backends.
#
# Loads a shared library implementing the sim_* C API and exposes
# it as a Sim class for pytest.  Opaque top pointer passed as
# c_void_p.  Tight simulation loop lives in C++ (sim_run); Python
# only peeks/pokes when the sim is stopped (before boot, after run).
#
# Backends:
#   verilator  libSim.so  — RTL simulation via Verilator model
#   spike      libSim.so  — ISA reference via riscv-isa-sim

import ctypes
import dataclasses
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]

_BACKENDS = {
    "spike": ROOT_DIR / "install" / "sim" / "spike" / "libIss.so",
}

# SRAM geometry
RAM_BASE = 0x80000000   # core AXI view



class _SimRunResult(ctypes.Structure):
    _fields_ = [
        ("retval",    ctypes.c_int32),
        ("cycles",    ctypes.c_uint64),
        ("timed_out", ctypes.c_int),
        ("trapped",   ctypes.c_int),
        ("mcause",    ctypes.c_uint32),
        ("mepc",      ctypes.c_uint32),
        ("mtval",     ctypes.c_uint32),
    ]


@dataclasses.dataclass
class RunResult:
    retval:    int
    cycles:    int
    timed_out: bool
    trapped:   bool  = False
    mcause:    int   = 0
    mepc:      int   = 0
    mtval:     int   = 0


def _load_lib(backend: str = "spike") -> ctypes.CDLL:
    path = _BACKENDS[backend]
    if not path.exists():
        raise FileNotFoundError(
            f"{path.name} not found at {path}.\nBuild with: ./sh/build.sh"
        )
    lib = ctypes.CDLL(str(path))

    # sim_create(int *argc, char **argv)
    lib.sim_create.argtypes = [ctypes.POINTER(ctypes.c_int),
                                  ctypes.POINTER(ctypes.c_char_p)]
    lib.sim_create.restype  = None

    # sim_destroy()
    lib.sim_destroy.argtypes = []
    lib.sim_destroy.restype  = None

    # sim_init(const char *test_name, const char *output_dir) -> void*
    lib.sim_init.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    lib.sim_init.restype  = ctypes.c_void_p

    # sim_done(void *top)
    lib.sim_done.argtypes = [ctypes.c_void_p]
    lib.sim_done.restype  = None

    # sim_tick(void *top)
    lib.sim_tick.argtypes = [ctypes.c_void_p]
    lib.sim_tick.restype  = None

    # sim_idle(void *top)
    lib.sim_idle.argtypes = [ctypes.c_void_p]
    lib.sim_idle.restype  = None

    # sim_reset(void *top, int cycles)
    lib.sim_reset.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.sim_reset.restype  = None

    # sim_boot_core(void *top, int core, uint64_t addr)
    lib.sim_boot_core.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                     ctypes.c_uint64]
    lib.sim_boot_core.restype  = None

    # sim_run(void *top, uint64_t max_cycles) -> BridgeRunResult
    lib.sim_run.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
    lib.sim_run.restype  = _SimRunResult

    # sim_sram_buf() -> uint8_t*
    lib.sim_sram_buf.argtypes = []
    lib.sim_sram_buf.restype  = ctypes.c_void_p

    # sim_sram_size() -> uint32_t
    lib.sim_sram_size.argtypes = []
    lib.sim_sram_size.restype  = ctypes.c_uint32

    # sim_sram_peek(uint32_t addr, uint8_t *data, uint32_t len)
    lib.sim_sram_peek.argtypes = [ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32]
    lib.sim_sram_peek.restype  = None

    # sim_sram_poke(uint32_t addr, const uint8_t *data, uint32_t len)
    lib.sim_sram_poke.argtypes = [ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32]
    lib.sim_sram_poke.restype  = None

    return lib


_libs: dict[str, ctypes.CDLL] = {}

def _get_lib(backend: str = "verilator") -> ctypes.CDLL:
    if backend not in _libs:
        lib = _load_lib(backend)
        argc = ctypes.c_int(1)
        argv = (ctypes.c_char_p * 2)(b"sim_top", None)
        lib.sim_create(ctypes.byref(argc), argv)
        _libs[backend] = lib
    return _libs[backend]


class Sim:
    """Per-test simulation instance."""

    def __init__(self, test_name: str, output_dir: str = "",
                 backend: str = "verilator"):
        self._lib = _get_lib(backend)
        self._top = self._lib.sim_init(test_name.encode(),
                                          output_dir.encode())
        self._lib.sim_idle(self._top)
        self._lib.sim_reset(self._top, 2)

    def poke_u8(self, sram_addr: int, data: bytes):
        """Write bytes to SRAM at offset."""
        buf = self._lib.sim_sram_buf()
        ctypes.memmove(buf + sram_addr, data, len(data))

    def load(self, binary: bytes, sram_offset: int = 0):
        """Load raw binary into SRAM."""
        self.poke_u8(sram_offset, binary)

    def boot(self, boot_addr: int = RAM_BASE, core: int = 0):
        """Set boot address and release core from reset."""
        self._lib.sim_boot_core(self._top, core, boot_addr)

    def tick(self, n: int = 1):
        """Advance N clock cycles."""
        for _ in range(n):
            self._lib.sim_tick(self._top)

    def _peek(self, sram_addr: int, length: int) -> bytes:
        buf = ctypes.create_string_buffer(length)
        self._lib.sim_sram_peek(ctypes.c_uint32(sram_addr), buf, length)
        return buf.raw

    def peek_u8(self, sram_addr: int, n: int) -> bytes:
        """Read n bytes from SRAM at offset."""
        return self._peek(sram_addr, n)

    def peek_u32(self, sram_addr: int, n: int) -> list[int]:
        """Read n uint32 values from SRAM at offset."""
        import struct
        return list(struct.unpack_from(f"<{n}I", self._peek(sram_addr, n * 4)))

    def run(self, max_cycles: int = 10000, tail: int = 100) -> RunResult:
        """Run sim in C++ until DONE magic or cycle limit.

        After completion, clock `tail` extra cycles so the trace captures
        post-done activity (store buffer drain, etc.).
        """
        raw = self._lib.sim_run(self._top, max_cycles)
        self.tick(tail)
        return RunResult(
            retval=raw.retval,
            cycles=raw.cycles,
            timed_out=bool(raw.timed_out),
            trapped=bool(raw.trapped),
            mcause=raw.mcause,
            mepc=raw.mepc,
            mtval=raw.mtval,
        )

    def close(self):
        if self._top is not None:
            self._lib.sim_done(self._top)
            self._top = None

    def __del__(self):
        self.close()
