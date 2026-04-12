// Spike (riscv-isa-sim) bridge — implements sim.h C API.
//
// Golden ISA reference using Spike's processor_t library.
// Tests can run against this to distinguish RTL bugs from test bugs.

#include "sim.h"

#include <riscv/cfg.h>
#include <riscv/processor.h>
#include <riscv/simif.h>

#include <cstdlib>
#include <cstring>
#include <iostream>
#include <map>

// ── Memory geometry (must match test.ld) ─────────────────────────

static constexpr uint64_t RAM_BASE = 0x80000000ULL;
static constexpr uint32_t RAM_SIZE = 0x01000000;  // 16 MB
static constexpr uint32_t RAM_MASK = RAM_SIZE - 1;

// ── Done protocol (must match crt0.S) ───────────────────────────

static constexpr uint32_t DONE_OFFSET = 0xFFFFC0;
static constexpr uint32_t DONE_MAGIC  = 0x444F4E45;  // "DONE"

// ── Global SRAM buffer ──────────────────────────────────────────

static uint8_t *g_ram_buf = nullptr;

// ── Minimal simif_t — flat memory, no MMIO devices ─────────────

class spike_simif_t : public simif_t {
public:
    cfg_t                            cfg;
    processor_t                     *proc = nullptr;
    std::map<size_t, processor_t *>  hart_map;

    spike_simif_t() { debug_mmu = nullptr; }

    // Map physical address to host buffer. Only RAM region is backed.
    char *addr_to_mem(reg_t paddr) override {
        if (paddr >= RAM_BASE && paddr < RAM_BASE + RAM_SIZE)
            return g_ram_buf ? reinterpret_cast<char *>(g_ram_buf + (paddr - RAM_BASE))
                             : nullptr;
        return nullptr;
    }

    // No MMIO devices — reads return zero, writes are sinks.
    bool mmio_load(reg_t, size_t len, uint8_t *bytes) override {
        memset(bytes, 0, len);
        return true;
    }
    bool mmio_store(reg_t, size_t, const uint8_t *) override {
        return true;
    }

    void proc_reset(unsigned) override {}
    const cfg_t &get_cfg() const override { return cfg; }
    const std::map<size_t, processor_t *> &get_harts() const override {
        return hart_map;
    }
    const char *get_symbol(uint64_t) override { return nullptr; }
};

// ── C API (see api.h) ───────────────────────────────────────────

void sim_create(int *, char **) {}
void sim_destroy() {}

void *sim_init(const char *, const char *) {
    g_ram_buf = static_cast<uint8_t *>(malloc(RAM_SIZE));
    memset(g_ram_buf, 0xCC, RAM_SIZE);

    auto *s = new spike_simif_t;

    // ISA must match the cross-compiler target (rv64gcv).
    // Append _zvl4096b to increase VLEN (default 128, max 4096).
    s->cfg.isa  = "rv64gcv";
    s->cfg.priv = "MSU";
    s->cfg.endianness  = endianness_little;
    s->cfg.pmpregions  = 0;
    s->cfg.start_pc    = RAM_BASE;
    s->cfg.hartids     = {0};
    s->cfg.real_time_clint = false;
    s->cfg.trigger_count   = 0;

    s->proc = new processor_t(
        /*isa=*/  "rv64gcv",
        /*priv=*/ "MSU",
        &s->cfg, s, /*id=*/ 0, /*halt_on_reset=*/ false,
        /*log_file=*/ nullptr,
        /*sout=*/ std::cerr);

    s->hart_map[0] = s->proc;
    s->proc->reset();
    s->proc->get_state()->pc = RAM_BASE;

    return s;
}

void sim_done(void *top) {
    auto *s = static_cast<spike_simif_t *>(top);
    delete s->proc;
    delete s;

    free(g_ram_buf);
    g_ram_buf = nullptr;
}

void sim_tick(void *top) {
    auto *s = static_cast<spike_simif_t *>(top);
    s->proc->step(1);
}

void sim_idle(void *) {}

void sim_reset(void *top, int) {
    auto *s = static_cast<spike_simif_t *>(top);
    s->proc->reset();
    s->proc->get_state()->pc = RAM_BASE;
}

void sim_boot_core(void *top, int, uint64_t addr) {
    auto *s = static_cast<spike_simif_t *>(top);
    s->proc->get_state()->pc = addr;
}

SimRunResult sim_run(void *top, uint64_t max_cycles) {
    auto *s = static_cast<spike_simif_t *>(top);

    static constexpr int BATCH = 1000;

    for (uint64_t i = 0; i < max_cycles; ) {
        uint64_t n = max_cycles - i;
        if (n > BATCH) n = BATCH;
        s->proc->step(n);
        i += n;

        auto *done = reinterpret_cast<uint32_t *>(g_ram_buf + DONE_OFFSET);
        if (done[0] == DONE_MAGIC) {
            int      trapped = (done[4] == 1);
            uint32_t mcause  = trapped ? done[1] : 0;
            return SimRunResult{
                static_cast<int32_t>(done[1]),
                i,
                0,
                trapped,
                mcause,
                done[2],
                done[3],
            };
        }
    }

    return SimRunResult{0, max_cycles, 1, 0, 0, 0, 0};
}

uint8_t *sim_sram_buf(void) { return g_ram_buf; }
uint32_t sim_sram_size(void) { return RAM_SIZE; }

void sim_sram_peek(uint32_t addr, uint8_t *data, uint32_t len) {
    memcpy(data, g_ram_buf + addr, len);
}

void sim_sram_poke(uint32_t addr, const uint8_t *data, uint32_t len) {
    memcpy(g_ram_buf + addr, data, len);
}

