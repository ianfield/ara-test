# Verilated ara_cva6 core with AXI4 slave memory model.
#
# Wraps the verilated core shared library and implements an AXI4 slave
# memory model in Python.  The core's AXI master port connects to a
# backing bytearray.  All AXI protocol handling is internal — callers
# interact via load/peek/poke/tick/run.
#
# API matches sim.Sim so tests can switch backends via --sim ara.
#
# Configuration: NrLanes=4, VLEN=4096 (DLEN=256, AxiDataWidth=128).

import ctypes
import dataclasses
import os
import struct
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]

_LIB_PATHS = {
    "base": ROOT_DIR / "install" / "sim" / "base" / "libAra.so",
    "fork": ROOT_DIR / "install" / "sim" / "fork" / "libAra.so",
}

AXI_RESP_OKAY = 0
MEM_SIZE = 16 * 1024 * 1024  # 16 MB
MEM_MASK = MEM_SIZE - 1

DONE_OFFSET = 0xFFFFC0
DONE_MAGIC  = 0x444F4E45     # "DONE" ASCII

RAM_BASE = 0x80000000


@dataclasses.dataclass
class RunResult:
    retval:    int
    cycles:    int
    timed_out: bool
    trapped:   bool = False
    mcause:    int  = 0
    mepc:      int  = 0
    mtval:     int  = 0


def _bind(lib):
    """Declare ctypes signatures for the C bridge."""
    lib.core_get_axi_data_bits.argtypes = []
    lib.core_get_axi_data_bits.restype = ctypes.c_int

    lib.core_init.argtypes = [ctypes.c_char_p]
    lib.core_init.restype = ctypes.c_void_p
    lib.core_done.argtypes = [ctypes.c_void_p]
    lib.core_done.restype = None
    lib.core_tick.argtypes = [ctypes.c_void_p]
    lib.core_tick.restype = None
    lib.core_eval.argtypes = [ctypes.c_void_p]
    lib.core_eval.restype = None
    lib.core_set_rst.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.core_set_rst.restype = None
    lib.core_set_boot_addr.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
    lib.core_set_boot_addr.restype = None
    lib.core_set_hart_id.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.core_set_hart_id.restype = None

    for name in ("aw_valid", "aw_id", "aw_len", "aw_size", "aw_burst",
                 "w_valid", "w_last",
                 "ar_valid", "ar_id", "ar_len", "ar_size", "ar_burst",
                 "b_ready", "r_ready"):
        fn = getattr(lib, f"core_get_{name}")
        fn.argtypes = [ctypes.c_void_p]
        fn.restype = ctypes.c_int

    lib.core_get_w_strb.argtypes = [ctypes.c_void_p]
    lib.core_get_w_strb.restype = ctypes.c_uint64

    for name in ("aw_addr", "ar_addr"):
        fn = getattr(lib, f"core_get_{name}")
        fn.argtypes = [ctypes.c_void_p]
        fn.restype = ctypes.c_uint64

    lib.core_get_w_data.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    lib.core_get_w_data.restype = None

    lib.core_set_ar_ready.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.core_set_ar_ready.restype = None
    lib.core_set_aw_ready.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.core_set_aw_ready.restype = None
    lib.core_set_w_ready.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.core_set_w_ready.restype = None
    lib.core_set_b.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int]
    lib.core_set_b.restype = None
    lib.core_set_r.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
    lib.core_set_r.restype = None
    return lib


class Sim:
    """Verilated ara_cva6 with AXI4 memory model.

    Backends: "base" (upstream), "fork" (patched).
    """

    def __init__(self, test_name: str, output_dir: str = "",
                 backend: str = "fork"):
        lib_path = _LIB_PATHS[backend]
        if not lib_path.exists():
            raise FileNotFoundError(f"{lib_path} not found — run ./sh/build.sh")
        self._lib = _bind(ctypes.CDLL(str(lib_path)))
        self._handle = self._lib.core_init(
            output_dir.encode() if output_dir else b"")

        # Query AXI bus width from the compiled model.
        axi_bits = self._lib.core_get_axi_data_bits()
        self._axi_data_bytes = axi_bits // 8
        self._axi_bus_mask = self._axi_data_bytes - 1

        self._mem = bytearray(MEM_SIZE)
        self._cycle = 0

        # Response latency (cycles between data-ready and response driven).
        # ARA_READ_LATENCY: cycles between AR accept and first R beat.
        # ARA_WRITE_LATENCY: cycles between last W beat and B response.
        self.read_latency = int(os.environ.get("ARA_READ_LATENCY", "0"))
        self.write_latency = int(os.environ.get("ARA_WRITE_LATENCY", "0"))

        # AXI read channel state
        self._ar_ready = 0
        self._r_valid = 0
        self._r_queue: list = []      # pending bursts: (addr, len, size, id)
        self._r_wait: list = []       # latency countdown: (cycle_ready, addr, len, size, id)
        self._r_addr = 0
        self._r_rem = 0
        self._r_size = 0
        self._r_id = 0

        # AXI write channel state
        self._aw_ready = 0
        self._w_ready = 0
        self._b_valid = 0
        self._aw_queue: list = []
        self._w_addr = 0
        self._w_size = 0
        self._w_id = 0
        self._w_active = False
        self._b_queue: list = []      # pending B responses: id
        self._b_wait: list = []       # latency countdown: (cycle_ready, id)
        self._b_id = 0

    # -- Public API (matches sim.Sim) ---------------------------------

    def poke_u8(self, sram_addr: int, data: bytes):
        """Write bytes to SRAM at offset."""
        end = sram_addr + len(data)
        if end > MEM_SIZE:
            raise ValueError(
                f"poke exceeds memory: {sram_addr:#x}+{len(data):#x}"
                f" > {MEM_SIZE:#x}")
        self._mem[sram_addr:end] = data

    def load(self, binary: bytes, sram_offset: int = 0):
        """Load raw binary into SRAM."""
        self.poke_u8(sram_offset, binary)

    def boot(self, boot_addr: int = RAM_BASE, core: int = 0):
        """Set boot address and release core from reset."""
        self._lib.core_set_boot_addr(self._handle, boot_addr)
        self._lib.core_set_rst(self._handle, 0)
        for _ in range(5):
            self._lib.core_tick(self._handle)
            self._cycle += 1
        self._lib.core_set_rst(self._handle, 1)
        self._lib.core_tick(self._handle)
        self._cycle += 1

    def tick(self, n: int = 1):
        """Advance *n* clock cycles, servicing AXI transactions."""
        for _ in range(n):
            self._tick_axi()
            self._cycle += 1

    def _peek(self, sram_addr: int, length: int) -> bytes:
        a = sram_addr & MEM_MASK
        return bytes(self._mem[a:a + length])

    def peek_u8(self, sram_addr: int, n: int) -> bytes:
        """Read n bytes from SRAM at offset."""
        return self._peek(sram_addr, n)

    def peek_u32(self, sram_addr: int, n: int) -> list[int]:
        """Read n uint32 values from SRAM at offset."""
        return list(struct.unpack_from(f"<{n}I", self._peek(sram_addr, n * 4)))

    def run(self, max_cycles: int = 10000, tail: int = 100) -> RunResult:
        """Run until DONE magic or cycle limit.

        After completion, ticks *tail* extra cycles so the trace captures
        post-done activity.
        """
        check_interval = 100
        cycles_run = 0

        while cycles_run < max_cycles:
            batch = min(check_interval, max_cycles - cycles_run)
            self.tick(batch)
            cycles_run += batch

            magic = struct.unpack_from("<I", self._mem, DONE_OFFSET)[0]
            if magic == DONE_MAGIC:
                self.tick(tail)
                vals = struct.unpack_from("<5I", self._mem, DONE_OFFSET)
                # [0]=magic [1]=retval [2]=mepc [3]=mtval [4]=trapped
                retval = ctypes.c_int32(vals[1]).value
                trapped = vals[4] == 1
                return RunResult(
                    retval=retval,
                    cycles=cycles_run,
                    timed_out=False,
                    trapped=trapped,
                    mcause=vals[1] if trapped else 0,
                    mepc=vals[2],
                    mtval=vals[3],
                )

        return RunResult(retval=0, cycles=max_cycles, timed_out=True)

    def close(self):
        if self._handle is not None:
            self._lib.core_done(self._handle)
            self._handle = None

    def __del__(self):
        self.close()

    # -- AXI memory model (internal) ----------------------------------

    def _mem_read(self, addr: int, size: int) -> int:
        """Read full bus width from bus-aligned address."""
        base = (addr & ~self._axi_bus_mask) & MEM_MASK
        return int.from_bytes(
            self._mem[base:base + self._axi_data_bytes], "little")

    def _mem_write(self, addr: int, size: int, data: int, strb: int):
        """Write with byte strobes across full bus width."""
        base = (addr & ~self._axi_bus_mask) & MEM_MASK
        for i in range(self._axi_data_bytes):
            if strb & (1 << i):
                self._mem[base + i] = (data >> (i * 8)) & 0xFF

    def _tick_axi(self):
        lib = self._lib
        h = self._handle

        # -- 1. Sample core outputs (pre-posedge values) --------------

        ar_v = lib.core_get_ar_valid(h)
        ar_addr = lib.core_get_ar_addr(h)
        ar_len = lib.core_get_ar_len(h)
        ar_size = lib.core_get_ar_size(h)
        ar_id = lib.core_get_ar_id(h)

        aw_v = lib.core_get_aw_valid(h)
        aw_addr = lib.core_get_aw_addr(h)
        aw_size = lib.core_get_aw_size(h)
        aw_id = lib.core_get_aw_id(h)

        w_v = lib.core_get_w_valid(h)
        w_buf = ctypes.create_string_buffer(self._axi_data_bytes)
        lib.core_get_w_data(h, w_buf)
        w_data = int.from_bytes(w_buf.raw, "little")
        w_strb = lib.core_get_w_strb(h)
        w_last = lib.core_get_w_last(h)

        r_rdy = lib.core_get_r_ready(h)
        b_rdy = lib.core_get_b_ready(h)

        # -- 2. Process completed handshakes --------------------------

        if ar_v and self._ar_ready:
            if self.read_latency > 0:
                self._r_wait.append((self._cycle + self.read_latency,
                                     ar_addr, ar_len, ar_size, ar_id))
            else:
                self._r_queue.append((ar_addr, ar_len, ar_size, ar_id))

        if aw_v and self._aw_ready:
            self._aw_queue.append((aw_addr, aw_size, aw_id))

        if w_v and self._w_ready:
            if not self._w_active and self._aw_queue:
                addr, sz, wid = self._aw_queue.pop(0)
                self._w_addr = addr
                self._w_size = sz
                self._w_id = wid
                self._w_active = True
            if self._w_active:
                self._mem_write(self._w_addr, self._w_size, w_data, w_strb)
                self._w_addr += 1 << self._w_size
                if w_last:
                    if self.write_latency > 0:
                        self._b_wait.append((self._cycle + self.write_latency,
                                             self._w_id))
                    else:
                        self._b_queue.append(self._w_id)
                    self._w_active = False

        if self._r_valid and r_rdy:
            self._r_rem -= 1
            self._r_addr += 1 << self._r_size
            if self._r_rem <= 0:
                self._r_valid = 0

        if self._b_valid and b_rdy:
            self._b_valid = 0

        # -- 3. Promote latency-expired entries -----------------------

        while self._r_wait and self._r_wait[0][0] <= self._cycle:
            _, addr, rlen, rsize, rid = self._r_wait.pop(0)
            self._r_queue.append((addr, rlen, rsize, rid))

        while self._b_wait and self._b_wait[0][0] <= self._cycle:
            _, bid = self._b_wait.pop(0)
            self._b_queue.append(bid)

        # -- 4. Prepare next-cycle responses --------------------------

        if not self._r_valid and self._r_queue:
            addr, rlen, rsize, rid = self._r_queue.pop(0)
            self._r_addr = addr
            self._r_rem = rlen + 1
            self._r_size = rsize
            self._r_id = rid
            self._r_valid = 1

        if not self._b_valid and self._b_queue:
            self._b_id = self._b_queue.pop(0)
            self._b_valid = 1

        # -- 4. Drive inputs ------------------------------------------

        self._ar_ready = 1
        self._aw_ready = 1
        self._w_ready = 1

        lib.core_set_ar_ready(h, 1)
        lib.core_set_aw_ready(h, 1)
        lib.core_set_w_ready(h, 1)

        if self._r_valid:
            rdata = self._mem_read(self._r_addr, self._r_size)
            rdata_bytes = rdata.to_bytes(self._axi_data_bytes, "little")
            last = 1 if self._r_rem == 1 else 0
            lib.core_set_r(h, 1, self._r_id, rdata_bytes,
                           AXI_RESP_OKAY, last)
        else:
            lib.core_set_r(h, 0, 0, None, 0, 0)

        if self._b_valid:
            lib.core_set_b(h, 1, self._b_id, AXI_RESP_OKAY)
        else:
            lib.core_set_b(h, 0, 0, 0)

        # -- 5. Tick --------------------------------------------------

        lib.core_tick(h)
