// sim API — backend-agnostic C interface to ara_system simulation.
//
// Lifecycle:
//   sim_create  -> sim_init  -> load/boot/run/peek -> sim_done -> sim_destroy

#pragma once
#include <cstdint>

#ifdef __cplusplus
extern "C" {
#endif

void sim_create(int *argc, char **argv);
void sim_destroy();

void *sim_init(const char *test_name, const char *output_dir);
void  sim_done(void *top);

void sim_tick(void *top);
void sim_idle(void *top);
void sim_reset(void *top, int cycles);
void sim_boot_core(void *top, int core, uint64_t addr);

typedef struct {
    int32_t  retval;
    uint64_t cycles;
    int      timed_out;
    int      trapped;
    uint32_t mcause;
    uint32_t mepc;
    uint32_t mtval;
} SimRunResult;

SimRunResult sim_run(void *top, uint64_t max_cycles);

uint8_t *sim_sram_buf(void);
uint32_t sim_sram_size(void);
void sim_sram_peek(uint32_t addr, uint8_t *data, uint32_t len);
void sim_sram_poke(uint32_t addr, const uint8_t *data, uint32_t len);

#ifdef __cplusplus
}
#endif
