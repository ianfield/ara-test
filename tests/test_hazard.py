# RAW hazard reproducer.

import struct

import pytest

from conftest import assert_ok, compile_snippet


def test_vfadd_hazard(sim):
    """Minimal filler + RAW hazard on known inputs."""
    va       = [1.0, 2.0, 3.0, 4.0]
    vb       = [-10.0, 20.0, -30.0, 40.0]
    expected = [1.0, 40.0, 3.0, 80.0]
    off_va   = 0x104000
    off_vb   = 0x106000
    off_dst  = 0x108000

    binary = compile_snippet('''
    int main() {
        asm volatile(

            // ── Scalar setup (all addresses + constants) ────────
            "li a1, 0x80104000\\n"         // &VA
            "li a2, 0x80106000\\n"         // &VB
            "li a3, 0x80108000\\n"         // &DST
            "fmv.w.x fa5, x0\\n"

            // ── Vector loads ────────────────────────────────────
            "vsetivli zero, 4, e32, m1, ta, mu\\n"
            "vle32.v v4, (a1)\\n"
            "vle32.v v6, (a2)\\n"

            // ── Fault injection ─────────────────────────────────
            "vfadd.vv v24, v24, v26\\n"

            // ── Critical sequence ───────────────────────────────
            "vmfge.vf v0, v6, fa5\\n"
            "vfadd.vv v4, v6, v6, v0.t\\n"

            // ── Store ───────────────────────────────────────────
            "vse32.v v4, (a3)\\n");
        return 0;
    }
    ''')
    sim.load(binary)
    sim.load(struct.pack('<4f', *va), sram_offset=off_va)
    sim.load(struct.pack('<4f', *vb), sram_offset=off_vb)
    sim.boot()
    result = sim.run(max_cycles=500000)
    assert_ok(result)

    raw = sim.peek_u32( off_dst, 4)
    got = [struct.unpack('<f', struct.pack('<I', raw[i]))[0] for i in range(4)]

    for i in range(4):
        assert got[i] == expected[i], (
            f"[{i}] expected {expected[i]}, got {got[i]}")



def test_vadd_hazard(sim):
    """Integer-only RAW hazard: filler + vmsgt → masked vadd."""
    #   vb (signed i32): [-10, 20, -30, 40]
    #   vmsgt.vi v0, v6, -1  →  v6 > -1  →  v6 >= 0  →  mask = [0,1,0,1]
    #   vadd.vv v4, v6, v6, v0.t  →  masked elements get vb+vb
    #   expected: [va[0], vb[1]+vb[1], va[2], vb[3]+vb[3]]
    #           = [0x10,  0x28,        0x30,  0x50]
    va       = [0x10, 0x20, 0x30, 0x40]
    vb       = [0xFFFFFFF6, 0x14, 0xFFFFFFE2, 0x28]
    expected = [0x10, 0x28, 0x30, 0x50]
    off_va   = 0x104000
    off_vb   = 0x106000
    off_dst  = 0x108000

    binary = compile_snippet('''
    int main() {
        asm volatile(
            "li a1, 0x80104000\\n"
            "li a2, 0x80106000\\n"
            "li a3, 0x80108000\\n"

            "vsetivli zero, 4, e32, m1, ta, mu\\n"
            "vle32.v v4, (a1)\\n"
            "vle32.v v6, (a2)\\n"

            "vle32.v v16, (a2)\\n"
            "vle32.v v18, (a2)\\n"
            "vadd.vv v24, v24, v26\\n"

            "vmsgt.vi v0, v6, -1\\n"
            "vadd.vv v4, v6, v6, v0.t\\n"

            "vse32.v v4, (a3)\\n");
        return 0;
    }
    ''')
    sim.load(binary)
    sim.load(struct.pack('<4I', *va), sram_offset=off_va)
    sim.load(struct.pack('<4I', *vb), sram_offset=off_vb)
    sim.boot()
    result = sim.run(max_cycles=500000)
    assert_ok(result)

    raw = sim.peek_u32( off_dst, 4)
    for i in range(4):
        assert raw[i] == expected[i], (
            f"[{i}] expected 0x{expected[i]:08x}, got 0x{raw[i]:08x}")


def test_vmseq_hazard(sim):
    """vid → vmseq(vid,2) → vfmerge. Exercises VID stale-data path."""
    binary = compile_snippet('''
    int main() {
        asm volatile(
            "vsetivli zero, 4, e32, m1, ta, ma\\n"

            "li a0, 0x80100000\\n"
            "li a1, 0x80100200\\n"
            "li a2, 0x80100240\\n"
            "li a3, 0x80100280\\n"
            "lui a4, 0x42c60\\n"           // 99.0f = 0x42C60000
            "fmv.w.x fa5, a4\\n"

            "vle32.v v8, (a0)\\n"          // v8 = [1,2,3,4]
            "vid.v v9\\n"                  // v9 = [0,1,2,3]
            "vse32.v v9, (a1)\\n"          // dump vid
            "vmseq.vi v0, v9, 2\\n"        // v0 = (vid == 2)
            "vsm.v v0, (a2)\\n"            // dump mask
            "vfmerge.vfm v8, v8, fa5, v0\\n" // v8 = mask ? 99.0 : v8
            "vse32.v v8, (a3)\\n"          // dump result
            ::: "a0", "a1", "a2", "a3", "a4", "fa5", "memory");
        return 0;
    }
    ''')
    sim.load(binary)
    sim.load(struct.pack('<4f', 1, 2, 3, 4), sram_offset=0x100000)
    sim.boot()
    result = sim.run(max_cycles=50000)
    assert_ok(result)

    raw_vid  = sim.peek_u32(0x100200, 4)
    raw_mask = sim.peek_u32( 0x100240, 1)[0] & 0xFF
    raw_vr   = sim.peek_u32( 0x100280, 4)

    mask = [(raw_mask >> i) & 1 for i in range(4)]
    vr = [struct.unpack('<f', struct.pack('<I', raw_vr[i]))[0] for i in range(4)]

    expected_mask = [0, 0, 1, 0]
    expected_vr = [1.0, 2.0, 99.0, 4.0]

    for i in range(4):
        assert mask[i] == expected_mask[i], (
            f"[{i}] mask: expected {expected_mask[i]}, got {mask[i]}")
        assert vr[i] == expected_vr[i], (
            f"[{i}] vr: expected {expected_vr[i]}, got {vr[i]}")


def test_vmand_hazard(sim):
    """vmand → vmseq with RAW on mask register.
    Exercises non-comparison mask-unit ALU op through spill register."""
    # v2 = [1,0,1,0] as mask bits → v0 mask = 0b0101
    # v3 = [0,1,1,0] as mask bits → v1 mask = 0b0110
    # vmand.mm v0, v0, v1 → 0b0101 & 0b0110 = 0b0100
    # Then vmseq.vi v0, v4, 7 on v4=[5,6,7,8] → bit 2 set → v0 = 0b0100
    # Both produce 0b0100 — but the path through the mask unit is different.
    binary = compile_snippet('''
    int main() {
        asm volatile(
            "vsetivli zero, 4, e32, m1, ta, ma\\n"

            "li a0, 0x80100000\\n"         // &src
            "li a1, 0x80100100\\n"         // &mask_out
            "li a2, 0x80100200\\n"         // &result

            "vle32.v v4, (a0)\\n"          // v4 = [5,6,7,8]

            // Build mask v0 = 0b0101 (elements 0,2 set)
            "vmseq.vi v0, v4, 5\\n"        // v4[0]==5 → bit 0
            "vmseq.vi v1, v4, 7\\n"        // v4[2]==7 → bit 2
            "vmor.mm v0, v0, v1\\n"        // v0 = 0b0101

            // Build mask v1 = 0b0110 (elements 1,2 set)
            "vmseq.vi v1, v4, 6\\n"        // v4[1]==6 → bit 1
            "vmseq.vi v2, v4, 7\\n"        // v4[2]==7 → bit 2
            "vmor.mm v1, v1, v2\\n"        // v1 = 0b0110

            // vmand: mask-unit ALU op (not a comparison)
            "vmand.mm v0, v0, v1\\n"       // v0 = 0b0101 & 0b0110 = 0b0100

            // Store mask result
            "vsm.v v0, (a1)\\n"

            // Now a comparison that writes v0 — tests that vmand
            // didn't corrupt the operand path for the next comparison
            "vmseq.vi v0, v4, 7\\n"        // v0 = (v4 == 7) = 0b0100
            "vsm.v v0, (a2)\\n"

            ::: "a0", "a1", "a2", "memory");
        return 0;
    }
    ''')
    sim.load(binary)
    sim.load(struct.pack('<4I', 5, 6, 7, 8), sram_offset=0x100000)
    sim.boot()
    result = sim.run(max_cycles=50000)
    assert_ok(result)

    vmand_mask = sim.peek_u32(0x100100, 1)[0] & 0xF
    vmseq_mask = sim.peek_u32(0x100200, 1)[0] & 0xF

    assert vmand_mask == 0b0100, f"vmand: expected 0b0100, got 0b{vmand_mask:04b}"
    assert vmseq_mask == 0b0100, f"vmseq after vmand: expected 0b0100, got 0b{vmseq_mask:04b}"


def test_viota_hazard(sim):
    """viota → vmseq. Exercises viota (non-comparison mask ALU op)."""
    # v0 mask = 0b1010 (elements 1,3 set)
    # viota.m v2, v0 → v2 = [0, 0, 1, 1] (prefix popcount of mask)
    # vmseq.vi v0, v2, 1 → v0 = (v2 == 1) = bits where v2[i]==1 → 0b1100
    binary = compile_snippet('''
    int main() {
        asm volatile(
            "vsetivli zero, 4, e32, m1, ta, ma\\n"

            "li a0, 0x80100000\\n"         // &src (for building mask)
            "li a1, 0x80100100\\n"         // &viota_out
            "li a2, 0x80100200\\n"         // &mask_out

            "vle32.v v4, (a0)\\n"          // v4 = [10,20,10,20]

            // Build mask v0: elements where v4==20 → bits 1,3 → 0b1010
            "li a3, 20\\n"
            "vmseq.vx v0, v4, a3\\n"       // v0 = 0b1010

            // viota: mask-unit ALU op
            "viota.m v2, v0\\n"            // v2 = [0, 0, 1, 1]
            "vse32.v v2, (a1)\\n"          // dump viota result

            // Comparison on viota output — tests operand path after viota
            "vmseq.vi v0, v2, 1\\n"        // v0 = (v2 == 1) = 0b1100
            "vsm.v v0, (a2)\\n"

            ::: "a0", "a1", "a2", "a3", "memory");
        return 0;
    }
    ''')
    sim.load(binary)
    sim.load(struct.pack('<4I', 10, 20, 10, 20), sram_offset=0x100000)
    sim.boot()
    result = sim.run(max_cycles=50000)
    assert_ok(result)

    viota = sim.peek_u32(0x100100, 4)
    assert list(viota[:4]) == [0, 0, 1, 1], f"viota: expected [0,0,1,1], got {list(viota[:4])}"

    mask = sim.peek_u32(0x100200, 1)[0] & 0xF
    assert mask == 0b1100, f"vmseq after viota: expected 0b1100, got 0b{mask:04b}"


def test_vmsbf_hazard(sim):
    """vmsbf → vmseq. Exercises set-before-first (mask-to-mask ALU op).
    vmsbf.m was in the blocked opcode range before the gating fix."""
    # vid → vmseq to build v0 = 0b0100 (bit 2)
    # vmsbf.m v0, v0 → v0 = 0b0011 (bits before first set)
    # Then vmseq on fresh data to test operand path isn't corrupted
    binary = compile_snippet('''
    int main() {
        asm volatile(
            "vsetivli zero, 4, e32, m1, ta, ma\\n"

            "li a0, 0x80100000\\n"
            "li a1, 0x80100100\\n"         // &vmsbf_out
            "li a2, 0x80100200\\n"         // &vmseq_out

            // v0 = 0b0100 (bit 2 set)
            "vid.v v3\\n"                  // v3 = [0,1,2,3]
            "li a3, 2\\n"
            "vmseq.vx v0, v3, a3\\n"       // v0 = (v3==2) = 0b0100

            // vmsbf: sets bits strictly before first set bit
            "vmsbf.m v2, v0\\n"            // v2 = 0b0011
            "vsm.v v2, (a1)\\n"

            // Now a fresh comparison — validates the operand path
            // is clean after vmsbf
            "vle32.v v4, (a0)\\n"          // v4 = [10,20,30,40]
            "li a3, 30\\n"
            "vmseq.vx v0, v4, a3\\n"       // v0 = (v4==30) = 0b0100
            "vsm.v v0, (a2)\\n"

            ::: "a0", "a1", "a2", "a3", "memory");
        return 0;
    }
    ''')
    sim.load(binary)
    sim.load(struct.pack('<4I', 10, 20, 30, 40), sram_offset=0x100000)
    sim.boot()
    result = sim.run(max_cycles=50000)
    assert_ok(result)

    vmsbf_mask = sim.peek_u32(0x100100, 1)[0] & 0xF
    vmseq_mask = sim.peek_u32(0x100200, 1)[0] & 0xF

    assert vmsbf_mask == 0b0011, f"vmsbf: expected 0b0011, got 0b{vmsbf_mask:04b}"
    assert vmseq_mask == 0b0100, f"vmseq after vmsbf: expected 0b0100, got 0b{vmseq_mask:04b}"


def test_vcpop_hazard(sim):
    """vcpop → vmseq. Exercises vcpop (mask-to-scalar) through mask unit."""
    # Build v0 = 0b1010 via comparisons, then vcpop should return 2.
    # Use the scalar result in vmseq.vx to verify it propagated correctly.
    binary = compile_snippet('''
    int main() {
        asm volatile(
            "vsetivli zero, 4, e32, m1, ta, ma\\n"

            "li a0, 0x80100000\\n"
            "li a1, 0x80100100\\n"         // &cpop_scalar
            "li a2, 0x80100200\\n"         // &mask_out

            "vle32.v v4, (a0)\\n"          // v4 = [1,2,3,4]

            // Build mask v0 = 0b1010
            "li a3, 2\\n"
            "vmseq.vx v0, v4, a3\\n"       // bit 1 (v4[1]==2)
            "li a3, 4\\n"
            "vmseq.vx v1, v4, a3\\n"       // bit 3 (v4[3]==4)
            "vmor.mm v0, v0, v1\\n"        // v0 = 0b1010

            // vcpop: mask-to-scalar, goes through mask unit ALU
            "vcpop.m a4, v0\\n"            // a4 = popcount(0b1010) = 2

            // Store scalar and use in comparison
            "sw a4, 0(a1)\\n"
            "vmseq.vx v0, v4, a4\\n"       // v0 = (v4 == a4)
            "vsm.v v0, (a2)\\n"

            ::: "a0", "a1", "a2", "a3", "a4", "memory");
        return 0;
    }
    ''')
    sim.load(binary)
    sim.load(struct.pack('<4I', 1, 2, 3, 4), sram_offset=0x100000)
    sim.boot()
    result = sim.run(max_cycles=50000)
    assert_ok(result)

    cpop = sim.peek_u32(0x100100, 1)[0]
    mask = sim.peek_u32(0x100200, 1)[0] & 0xF

    assert cpop == 2, f"vcpop: expected 2, got {cpop}"
    assert mask == 0b0010, f"vmseq after vcpop: expected 0b0010, got 0b{mask:04b}"
