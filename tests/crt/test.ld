/* Linker script for ara-test bare-metal tests.
 *
 * RAM at 0x80000000, 16 MB.
 *
 * Layout:
 *   0x80000000  .text.init (entry point)
 *               .text
 *               .rodata
 *               .data
 *               .bss
 *   ...
 *   0x80FFFF80  __stack_top  (grows down)
 *   0x80FFFFC0  __done       (16 words, peek offset 0xFFFFC0)
 *               [0] DONE magic     [1] retval/mcause
 *               [2] mepc           [3] mtval
 *               [4] trapped flag
 *   0x01000000  end of RAM
 */

ENTRY(_start)

MEMORY
{
    RAM (rwx) : ORIGIN = 0x80000000, LENGTH = 0x01000000
}

SECTIONS
{
    .text : {
        *(.text.init)
        *(.text .text.*)
    } > RAM

    .rodata : {
        *(.rodata .rodata.*)
    } > RAM

    .data : {
        *(.data .data.*)
    } > RAM

    .bss : {
        __bss_start = .;
        *(.bss .bss.* .sbss .sbss.*)
        *(COMMON)
        __bss_end = .;
    } > RAM

    __stack_top = ORIGIN(RAM) + LENGTH(RAM) - 128;
    __done      = ORIGIN(RAM) + LENGTH(RAM) - 64;
}
