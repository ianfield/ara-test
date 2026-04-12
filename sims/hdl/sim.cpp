// Core-level sim bridge — lifecycle and signal access for Verilated ara_cva6.
//
// Python loads this shared library via ctypes.  All AXI bus behavior
// (memory model, protocol sequencing) lives in Python — this bridge
// only exposes model lifecycle and per-cycle signal access.
//
// AXI data width is set by AXI_DATA_BITS (compile-time define from build.sh).
// NrLanes=2 → 64-bit, NrLanes=4 → 128-bit.

#include "Vara_cva6.h"
#include "verilated.h"
#if VM_TRACE
#include "verilated_fst_c.h"
#endif

#include <cstdlib>
#include <cstring>
#include <string>
#include <sys/stat.h>

#ifndef AXI_DATA_BITS
#error "AXI_DATA_BITS must be defined
#endif

#if VM_TRACE
static VerilatedFstC *g_tfp = nullptr;
#endif

double sc_time_stamp() { return 0; }

static void mkdirs(const std::string &path) {
    for (size_t pos = 1; (pos = path.find('/', pos)) != std::string::npos; ++pos)
        mkdir(path.substr(0, pos).c_str(), 0755);
    mkdir(path.c_str(), 0755);
}

extern "C" {

// Expose config so Python can query at runtime.
int core_get_axi_data_bits(void) { return AXI_DATA_BITS; }

void *core_init(const char *output_dir) {
    VerilatedContext *ctx = new VerilatedContext;

    std::string dasm_arg;
    if (output_dir && *output_dir) {
        mkdirs(std::string(output_dir));
        dasm_arg = "+trace_file=" + std::string(output_dir) + "/hart_0.dasm";
    }
    const char *args[] = {"core_sim", dasm_arg.empty() ? nullptr : dasm_arg.c_str()};
    ctx->commandArgs(dasm_arg.empty() ? 1 : 2, args);

#if VM_TRACE
    ctx->traceEverOn(true);
#endif

    Vara_cva6 *top = new Vara_cva6(ctx);

#if VM_TRACE
    if (output_dir && *output_dir) {
        mkdirs(std::string(output_dir));
        std::string path = std::string(output_dir) + "/core.fst";
        g_tfp = new VerilatedFstC;
        top->trace(g_tfp, 99);
        g_tfp->open(path.c_str());
    }
#endif

    top->scan_enable_i = 0;
    top->scan_data_i = 0;
    top->hart_id_i = 0;
    top->boot_addr_i = 0;
    top->rst_ni = 0;
    top->clk_i = 0;

    top->axi_aw_ready_i = 0;
    top->axi_w_ready_i  = 0;
    top->axi_ar_ready_i = 0;
    top->axi_b_valid_i  = 0;
    top->axi_b_id_i     = 0;
    top->axi_b_resp_i   = 0;
    top->axi_b_user_i   = 0;
    top->axi_r_valid_i  = 0;
    top->axi_r_id_i     = 0;
    memset(&top->axi_r_data_i, 0, sizeof(top->axi_r_data_i));
    top->axi_r_resp_i   = 0;
    top->axi_r_last_i   = 0;
    top->axi_r_user_i   = 0;

    return top;
}

void core_done(void *handle) {
    Vara_cva6 *top = static_cast<Vara_cva6 *>(handle);
#if VM_TRACE
    if (g_tfp) {
        g_tfp->close();
        delete g_tfp;
        g_tfp = nullptr;
    }
#endif
    VerilatedContext *ctx = top->contextp();
    top->final();
    delete top;
    delete ctx;
}

void core_eval(void *handle) {
    Vara_cva6 *top = static_cast<Vara_cva6 *>(handle);
    top->eval();
#if VM_TRACE
    if (g_tfp) g_tfp->dump(top->contextp()->time());
#endif
}

void core_tick(void *handle) {
    Vara_cva6 *top = static_cast<Vara_cva6 *>(handle);
    VerilatedContext *ctx = top->contextp();

    top->clk_i = 0;
    top->eval();
    ctx->timeInc(5);
#if VM_TRACE
    if (g_tfp) g_tfp->dump(ctx->time());
#endif

    top->clk_i = 1;
    top->eval();
    ctx->timeInc(5);
#if VM_TRACE
    if (g_tfp) g_tfp->dump(ctx->time());
#endif
}

// --- Control signals ---

void core_set_rst(void *handle, int v) {
    static_cast<Vara_cva6 *>(handle)->rst_ni = v;
}

void core_set_boot_addr(void *handle, uint64_t v) {
    static_cast<Vara_cva6 *>(handle)->boot_addr_i = v;
}

void core_set_hart_id(void *handle, int v) {
    static_cast<Vara_cva6 *>(handle)->hart_id_i = v;
}

// --- AXI slave inputs ---

void core_set_aw_ready(void *handle, int v) {
    static_cast<Vara_cva6 *>(handle)->axi_aw_ready_i = v;
}

void core_set_w_ready(void *handle, int v) {
    static_cast<Vara_cva6 *>(handle)->axi_w_ready_i = v;
}

void core_set_ar_ready(void *handle, int v) {
    static_cast<Vara_cva6 *>(handle)->axi_ar_ready_i = v;
}

void core_set_b(void *handle, int valid, int id, int resp) {
    Vara_cva6 *top = static_cast<Vara_cva6 *>(handle);
    top->axi_b_valid_i = valid;
    top->axi_b_id_i    = id;
    top->axi_b_resp_i  = resp;
    top->axi_b_user_i  = 0;
}

// AXI read data — passed as raw bytes (AXI_DATA_BITS/8 bytes, little-endian).
void core_set_r(void *handle, int valid, int id, const uint8_t *data,
                int resp, int last) {
    Vara_cva6 *top = static_cast<Vara_cva6 *>(handle);
    top->axi_r_valid_i = valid;
    top->axi_r_id_i    = id;
    if (data)
        memcpy(&top->axi_r_data_i, data, AXI_DATA_BITS / 8);
    else
        memset(&top->axi_r_data_i, 0, AXI_DATA_BITS / 8);
    top->axi_r_resp_i  = resp;
    top->axi_r_last_i  = last;
    top->axi_r_user_i  = 0;
}

// --- AXI master outputs ---

int      core_get_aw_valid(void *handle)  { return static_cast<Vara_cva6 *>(handle)->axi_aw_valid_o; }
int      core_get_aw_id(void *handle)     { return static_cast<Vara_cva6 *>(handle)->axi_aw_id_o; }
uint64_t core_get_aw_addr(void *handle)   { return static_cast<Vara_cva6 *>(handle)->axi_aw_addr_o; }
int      core_get_aw_len(void *handle)    { return static_cast<Vara_cva6 *>(handle)->axi_aw_len_o; }
int      core_get_aw_size(void *handle)   { return static_cast<Vara_cva6 *>(handle)->axi_aw_size_o; }
int      core_get_aw_burst(void *handle)  { return static_cast<Vara_cva6 *>(handle)->axi_aw_burst_o; }

int      core_get_w_valid(void *handle)   { return static_cast<Vara_cva6 *>(handle)->axi_w_valid_o; }

// Copy write data into caller-provided buffer (AXI_DATA_BITS/8 bytes).
void core_get_w_data(void *handle, uint8_t *out) {
    memcpy(out, &static_cast<Vara_cva6 *>(handle)->axi_w_data_o, AXI_DATA_BITS / 8);
}

uint64_t core_get_w_strb(void *handle)    { return static_cast<Vara_cva6 *>(handle)->axi_w_strb_o; }
int      core_get_w_last(void *handle)    { return static_cast<Vara_cva6 *>(handle)->axi_w_last_o; }

int      core_get_ar_valid(void *handle)  { return static_cast<Vara_cva6 *>(handle)->axi_ar_valid_o; }
int      core_get_ar_id(void *handle)     { return static_cast<Vara_cva6 *>(handle)->axi_ar_id_o; }
uint64_t core_get_ar_addr(void *handle)   { return static_cast<Vara_cva6 *>(handle)->axi_ar_addr_o; }
int      core_get_ar_len(void *handle)    { return static_cast<Vara_cva6 *>(handle)->axi_ar_len_o; }
int      core_get_ar_size(void *handle)   { return static_cast<Vara_cva6 *>(handle)->axi_ar_size_o; }
int      core_get_ar_burst(void *handle)  { return static_cast<Vara_cva6 *>(handle)->axi_ar_burst_o; }

int      core_get_b_ready(void *handle)   { return static_cast<Vara_cva6 *>(handle)->axi_b_ready_o; }
int      core_get_r_ready(void *handle)   { return static_cast<Vara_cva6 *>(handle)->axi_r_ready_o; }

} // extern "C"
