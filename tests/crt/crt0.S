// Bare-metal CRT for ara-test.
//
// Sets mtvec, stack pointer, calls main(), stores result at __done,
// then enters WFI loop.  bridge_run polls __done via the SRAM buffer to
// detect completion.
//
// __done layout (16 words / 64 bytes at top of SRAM):
//
//   Word | Normal exit         | Trap
//   -----|---------------------|----------------------
//   0    | "DONE" (0x444F4E45) | "DONE" (0x444F4E45)
//   1    | main() retval       | mcause
//   2    | 0                   | mepc  (faulting PC)
//   3    | 0                   | mtval (fault detail)
//   4    | 0                   | 1     (trapped flag)
//
// Magic at word 0 (base) so it never moves as fields are appended.
// The trapped flag at word 4 distinguishes the two paths.
// DONE magic is written last with fence w,w before and after so the
// host never sees a partial result.

.section .text.init
.globl _start
_start:
    la   t0, _trap_handler
    csrw mtvec, t0
    li   t0, 0x2200
    csrs mstatus, t0       // mstatus.FS + VS = Initial (enable float + vector)
    la   sp, __stack_top
    call main

    // Normal exit — write retval, then DONE magic last.
    la   t0, __done
    sw   a0, 4(t0)         // word 1 = main() retval
    li   t1, 0x444F4E45
    sw   t1, 0(t0)         // word 0 = DONE magic (commit)
    fence w, w
1:  wfi
    j    1b

.balign 4
_trap_handler:
    la   t0, __done
    csrr t1, mcause
    sw   t1, 4(t0)         // word 1 = mcause
    csrr t1, mepc
    sw   t1, 8(t0)         // word 2 = mepc
    csrr t1, mtval
    sw   t1, 12(t0)        // word 3 = mtval
    li   t1, 1
    sw   t1, 16(t0)        // word 4 = trapped flag
    li   t1, 0x444F4E45
    sw   t1, 0(t0)         // word 0 = DONE magic (commit)
    fence w, w
1:  wfi
    j    1b
