// Top-level wrapper for ara_system (CVA6 + Ara vector unit).
// Resolves all parameterized types to concrete values so that
// any misconfiguration produces a compile-time width mismatch.

module ara_cva6 import axi_pkg::*; import ara_pkg::*; #(
    // ---------------------------------------------------------------
    // Vector configuration
    // ---------------------------------------------------------------

    // Number of parallel vector lanes (powers of 2: 2,4,8,16)
    // Each lane processes one element per cycle.
    // More lanes = more throughput, more area.
    parameter int unsigned NrLanes = 16,

    // VLEN: vector register length in bits (RVV architectural register size).
    // Each vector register holds VLEN bits; with 16 lanes each lane stores
    // VLEN/NrLanes = 1024 bits per register.
    // TODO: evaluate whether we can shrink VLEN (affects register file area)
    parameter int unsigned VLEN = 16384,

    // ---------------------------------------------------------------
    // OS / MMU support
    // ---------------------------------------------------------------

    // When 1, Ara sends virtual addresses to CVA6's MMU for translation.
    // When 0, Ara bypasses the MMU and uses physical addresses directly.
    // We need virtual address translation for both scalar and vector
    // load/stores, so this must be 1.
    parameter int unsigned OSSupport = 1,

    // ---------------------------------------------------------------
    // Floating-point support
    // ---------------------------------------------------------------

    // FPU format enable bitmask — 6 bits: {RVVD, RVVF, RVVH, RVVHA, RVVB, RVVBA}
    //
    //   Bit 5 (RVVD)  — FP64  IEEE binary64        (11-bit exp, 52-bit man)
    //   Bit 4 (RVVF)  — FP32  IEEE binary32        ( 8-bit exp, 23-bit man)
    //   Bit 3 (RVVH)  — FP16  IEEE binary16        ( 5-bit exp, 10-bit man)
    //   Bit 2 (RVVHA) — BF16  bfloat16 / FP16ALT   ( 8-bit exp,  7-bit man)
    //   Bit 1 (RVVB)  — FP8   custom binary8       ( 5-bit exp,  2-bit man)
    //   Bit 0 (RVVBA) — FP8A  custom binary8alt    ( 4-bit exp,  3-bit man)
    //
    // Named enums from ara_pkg (ara_dispatcher uses `unique case` on these —
    // non-enum values fall through all cases and mark instructions illegal):
    //   FPUSupportNone             = 6'b000000
    //   FPUSupportHalf             = 6'b001000  — FP16
    //   FPUSupportSingle           = 6'b010000  — FP32
    //   FPUSupportHalfSingle       = 6'b011000  — FP16 + FP32
    //   FPUSupportDouble           = 6'b100000  — FP64
    //   FPUSupportSingleDouble     = 6'b110000  — FP32 + FP64
    //   FPUSupportHalfSingleDouble = 6'b111000  — FP16 + FP32 + FP64
    //   FPUSupportAll              = 6'b111111  — all formats
    //
    // All formats: FP64 + FP32 + FP16 + BF16 + FP8 + FP8ALT
    // Must use a named enum — ara_dispatcher's `unique case(FPUSupport)`
    // falls through to `illegal_insn` for non-enum values.
    parameter fpu_support_e FPUSupport = FPUSupportAll,

    // External FPU support for vfrec7, vfrsqrt7 approximation instructions
    // and round-toward-odd mode. Enable unless saving area.
    //   FPExtSupportDisable = 1'b0
    //   FPExtSupportEnable  = 1'b1
    parameter fpext_support_e FPExtSupport = FPExtSupportEnable,

    // ---------------------------------------------------------------
    // Fixed-point support
    // ---------------------------------------------------------------

    // RVV fixed-point instructions: saturating add/sub (vsadd, vssub),
    // averaging add/sub (vaadd, vasub), scaling shifts (vssra, vssrl),
    // narrowing clip (vnclip). Disabled — not needed for our workloads.
    //   FixedPointDisable = 1'b0
    //   FixedPointEnable  = 1'b1
    parameter fixpt_support_e FixPtSupport = FixedPointDisable,

    // ---------------------------------------------------------------
    // Segment load/store support
    // ---------------------------------------------------------------

    // Enables vlseg/vsseg instructions for structured data access
    // (e.g., loading interleaved RGB pixel data or multi-field structs).
    //   SegSupportDisable = 1'b0
    //   SegSupportEnable  = 1'b1
    parameter seg_support_e SegSupport = SegSupportEnable,

    // ---------------------------------------------------------------
    // AXI parameters
    // ---------------------------------------------------------------

    parameter int unsigned AxiAddrWidth = 64,
    parameter int unsigned AxiUserWidth = 1,
    parameter int unsigned AxiIdWidth   = 6,
    // Data width = 32 * NrLanes = 512 bits (64 bytes per beat)
    parameter int unsigned AxiDataWidth = 32 * NrLanes
  ) (
    input  logic        clk_i,
    input  logic        rst_ni,
    input  logic [63:0] boot_addr_i,
    input        [2:0]  hart_id_i,
    // Scan chain
    input  logic        scan_enable_i,
    input  logic        scan_data_i,
    output logic        scan_data_o,

    // -----------------------------------------------------------------
    // AXI4 master interface
    //
    // With default params: id=6, addr=64, data=512, strb=64, user=1
    // -----------------------------------------------------------------

    // AW — Write address channel
    output logic [AxiIdWidth-1:0]       axi_aw_id_o,
    output logic [AxiAddrWidth-1:0]     axi_aw_addr_o,
    output axi_pkg::len_t               axi_aw_len_o,
    output axi_pkg::size_t              axi_aw_size_o,
    output axi_pkg::burst_t             axi_aw_burst_o,
    output logic                        axi_aw_lock_o,
    output axi_pkg::cache_t             axi_aw_cache_o,
    output axi_pkg::prot_t              axi_aw_prot_o,
    output axi_pkg::qos_t               axi_aw_qos_o,
    output axi_pkg::region_t            axi_aw_region_o,
    output axi_pkg::atop_t              axi_aw_atop_o,
    output logic [AxiUserWidth-1:0]     axi_aw_user_o,
    output logic                        axi_aw_valid_o,
    input  logic                        axi_aw_ready_i,

    // W — Write data channel
    output logic [AxiDataWidth-1:0]     axi_w_data_o,
    output logic [AxiDataWidth/8-1:0]   axi_w_strb_o,
    output logic                        axi_w_last_o,
    output logic [AxiUserWidth-1:0]     axi_w_user_o,
    output logic                        axi_w_valid_o,
    input  logic                        axi_w_ready_i,

    // B — Write response channel
    input  logic [AxiIdWidth-1:0]       axi_b_id_i,
    input  axi_pkg::resp_t              axi_b_resp_i,
    input  logic [AxiUserWidth-1:0]     axi_b_user_i,
    input  logic                        axi_b_valid_i,
    output logic                        axi_b_ready_o,

    // AR — Read address channel
    output logic [AxiIdWidth-1:0]       axi_ar_id_o,
    output logic [AxiAddrWidth-1:0]     axi_ar_addr_o,
    output axi_pkg::len_t               axi_ar_len_o,
    output axi_pkg::size_t              axi_ar_size_o,
    output axi_pkg::burst_t             axi_ar_burst_o,
    output logic                        axi_ar_lock_o,
    output axi_pkg::cache_t             axi_ar_cache_o,
    output axi_pkg::prot_t              axi_ar_prot_o,
    output axi_pkg::qos_t               axi_ar_qos_o,
    output axi_pkg::region_t            axi_ar_region_o,
    output logic [AxiUserWidth-1:0]     axi_ar_user_o,
    output logic                        axi_ar_valid_o,
    input  logic                        axi_ar_ready_i,

    // R — Read data channel
    input  logic [AxiIdWidth-1:0]       axi_r_id_i,
    input  logic [AxiDataWidth-1:0]     axi_r_data_i,
    input  axi_pkg::resp_t              axi_r_resp_i,
    input  logic                        axi_r_last_i,
    input  logic [AxiUserWidth-1:0]     axi_r_user_i,
    input  logic                        axi_r_valid_i,
    output logic                        axi_r_ready_o
  );

  `include "axi/assign.svh"
  `include "axi/typedef.svh"
  `include "ara/intf_typedef.svh"

  // -------------------------------------------------------------------
  // Derived parameters (do not modify)
  // -------------------------------------------------------------------

  localparam AxiNarrowDataWidth = 64;
  localparam AxiNarrowStrbWidth = AxiNarrowDataWidth / 8;
  localparam AxiWideDataWidth   = AxiDataWidth;
  localparam AxiCoreIdWidth     = AxiIdWidth - 1;

  // -------------------------------------------------------------------
  // AXI type definitions
  // -------------------------------------------------------------------

  typedef logic [AxiDataWidth-1:0]       axi_data_t;
  typedef logic [AxiDataWidth/8-1:0]     axi_strb_t;
  typedef logic [AxiAddrWidth-1:0]       axi_addr_t;
  typedef logic [AxiUserWidth-1:0]       axi_user_t;
  typedef logic [AxiIdWidth-1:0]         axi_id_t;
  typedef logic [AxiNarrowDataWidth-1:0] axi_narrow_data_t;
  typedef logic [AxiNarrowStrbWidth-1:0] axi_narrow_strb_t;
  typedef logic [AxiCoreIdWidth-1:0]     axi_core_id_t;

  // System-level AXI (output port)
  `AXI_TYPEDEF_ALL(system, axi_addr_t, axi_id_t, axi_data_t, axi_strb_t, axi_user_t)
  // Ara-width AXI (internal, between ara and mux)
  `AXI_TYPEDEF_ALL(ara_axi, axi_addr_t, axi_core_id_t, axi_data_t, axi_strb_t, axi_user_t)
  // Ariane narrow AXI (internal, CVA6 scalar core)
  `AXI_TYPEDEF_ALL(ariane_axi, axi_addr_t, axi_core_id_t, axi_narrow_data_t, axi_narrow_strb_t,
    axi_user_t)

  // -------------------------------------------------------------------
  // CVA6 configuration
  // -------------------------------------------------------------------

  function automatic config_pkg::cva6_user_cfg_t gen_cva6_config(config_pkg::cva6_user_cfg_t cfg);
    cfg.AxiAddrWidth = AxiAddrWidth;
    cfg.AxiDataWidth = AxiNarrowDataWidth;
    cfg.AxiIdWidth   = AxiIdWidth;
    cfg.AxiUserWidth = AxiUserWidth;
    cfg.XF16         = FPUSupport[3];
    cfg.RVF          = FPUSupport[4];
    cfg.RVD          = FPUSupport[5];
    cfg.XF16ALT      = FPUSupport[2];
    cfg.XF8          = FPUSupport[1];
    cfg.NrPMPEntries = 0;
    return cfg;
  endfunction

  localparam config_pkg::cva6_user_cfg_t CVA6UserCfg = gen_cva6_config(cva6_config_pkg::cva6_cfg);
  localparam config_pkg::cva6_cfg_t      CVA6Cfg     = build_config_pkg::build_config(CVA6UserCfg);

  // -------------------------------------------------------------------
  // CVA6 <-> Ara interface types (resolved from macros)
  // -------------------------------------------------------------------

  `CVA6_TYPEDEF_EXCEPTION(exception_t, CVA6Cfg)
  `CVA6_INTF_TYPEDEF_ACC_REQ(accelerator_req_t, CVA6Cfg, fpnew_pkg::roundmode_e)
  `CVA6_INTF_TYPEDEF_ACC_RESP(accelerator_resp_t, CVA6Cfg, exception_t)
  `CVA6_INTF_TYPEDEF_MMU_REQ(acc_mmu_req_t, CVA6Cfg)
  `CVA6_INTF_TYPEDEF_MMU_RESP(acc_mmu_resp_t, CVA6Cfg, exception_t)
  `CVA6_INTF_TYPEDEF_CVA6_TO_ACC(cva6_to_acc_t, accelerator_req_t, acc_mmu_resp_t)
  `CVA6_INTF_TYPEDEF_ACC_TO_CVA6(acc_to_cva6_t, accelerator_resp_t, acc_mmu_req_t)

  // -------------------------------------------------------------------
  // AXI struct <-> port mapping
  // -------------------------------------------------------------------

  system_req_t  system_axi_req;
  system_resp_t system_axi_resp;

  // AW
  assign axi_aw_id_o     = system_axi_req.aw.id;
  assign axi_aw_addr_o   = system_axi_req.aw.addr;
  assign axi_aw_len_o    = system_axi_req.aw.len;
  assign axi_aw_size_o   = system_axi_req.aw.size;
  assign axi_aw_burst_o  = system_axi_req.aw.burst;
  assign axi_aw_lock_o   = system_axi_req.aw.lock;
  assign axi_aw_cache_o  = system_axi_req.aw.cache;
  assign axi_aw_prot_o   = system_axi_req.aw.prot;
  assign axi_aw_qos_o    = system_axi_req.aw.qos;
  assign axi_aw_region_o = system_axi_req.aw.region;
  assign axi_aw_atop_o   = system_axi_req.aw.atop;
  assign axi_aw_user_o   = system_axi_req.aw.user;
  assign axi_aw_valid_o  = system_axi_req.aw_valid;

  // W
  assign axi_w_data_o    = system_axi_req.w.data;
  assign axi_w_strb_o    = system_axi_req.w.strb;
  assign axi_w_last_o    = system_axi_req.w.last;
  assign axi_w_user_o    = system_axi_req.w.user;
  assign axi_w_valid_o   = system_axi_req.w_valid;

  // AR
  assign axi_ar_id_o     = system_axi_req.ar.id;
  assign axi_ar_addr_o   = system_axi_req.ar.addr;
  assign axi_ar_len_o    = system_axi_req.ar.len;
  assign axi_ar_size_o   = system_axi_req.ar.size;
  assign axi_ar_burst_o  = system_axi_req.ar.burst;
  assign axi_ar_lock_o   = system_axi_req.ar.lock;
  assign axi_ar_cache_o  = system_axi_req.ar.cache;
  assign axi_ar_prot_o   = system_axi_req.ar.prot;
  assign axi_ar_qos_o    = system_axi_req.ar.qos;
  assign axi_ar_region_o = system_axi_req.ar.region;
  assign axi_ar_user_o   = system_axi_req.ar.user;
  assign axi_ar_valid_o  = system_axi_req.ar_valid;

  // B ready, R ready
  assign axi_b_ready_o   = system_axi_req.b_ready;
  assign axi_r_ready_o   = system_axi_req.r_ready;

  // Response path
  assign system_axi_resp.aw_ready = axi_aw_ready_i;
  assign system_axi_resp.w_ready  = axi_w_ready_i;
  assign system_axi_resp.ar_ready = axi_ar_ready_i;
  assign system_axi_resp.b_valid  = axi_b_valid_i;
  assign system_axi_resp.b.id     = axi_b_id_i;
  assign system_axi_resp.b.resp   = axi_b_resp_i;
  assign system_axi_resp.b.user   = axi_b_user_i;
  assign system_axi_resp.r_valid  = axi_r_valid_i;
  assign system_axi_resp.r.id     = axi_r_id_i;
  assign system_axi_resp.r.data   = axi_r_data_i;
  assign system_axi_resp.r.resp   = axi_r_resp_i;
  assign system_axi_resp.r.last   = axi_r_last_i;
  assign system_axi_resp.r.user   = axi_r_user_i;

  // -------------------------------------------------------------------
  // ara_system instance
  // -------------------------------------------------------------------

  ara_system #(
    .NrLanes           (NrLanes             ),
    .VLEN              (VLEN                ),
    .OSSupport         (OSSupport           ),
    .FPUSupport        (FPUSupport          ),
    .FPExtSupport      (FPExtSupport        ),
    .FixPtSupport      (FixPtSupport        ),
    .SegSupport        (SegSupport          ),
    .CVA6Cfg           (CVA6Cfg             ),
    .exception_t       (exception_t         ),
    .accelerator_req_t (accelerator_req_t   ),
    .accelerator_resp_t(accelerator_resp_t  ),
    .acc_mmu_req_t     (acc_mmu_req_t       ),
    .acc_mmu_resp_t    (acc_mmu_resp_t      ),
    .cva6_to_acc_t     (cva6_to_acc_t       ),
    .acc_to_cva6_t     (acc_to_cva6_t       ),
    .AxiAddrWidth      (AxiAddrWidth        ),
    .AxiIdWidth        (AxiCoreIdWidth      ),
    .AxiNarrowDataWidth(AxiNarrowDataWidth  ),
    .AxiWideDataWidth  (AxiDataWidth        ),
    .ara_axi_ar_t      (ara_axi_ar_chan_t   ),
    .ara_axi_aw_t      (ara_axi_aw_chan_t   ),
    .ara_axi_b_t       (ara_axi_b_chan_t    ),
    .ara_axi_r_t       (ara_axi_r_chan_t    ),
    .ara_axi_w_t       (ara_axi_w_chan_t    ),
    .ara_axi_req_t     (ara_axi_req_t       ),
    .ara_axi_resp_t    (ara_axi_resp_t      ),
    .ariane_axi_ar_t   (ariane_axi_ar_chan_t),
    .ariane_axi_aw_t   (ariane_axi_aw_chan_t),
    .ariane_axi_b_t    (ariane_axi_b_chan_t ),
    .ariane_axi_r_t    (ariane_axi_r_chan_t ),
    .ariane_axi_w_t    (ariane_axi_w_chan_t ),
    .ariane_axi_req_t  (ariane_axi_req_t    ),
    .ariane_axi_resp_t (ariane_axi_resp_t   ),
    .system_axi_ar_t   (system_ar_chan_t    ),
    .system_axi_aw_t   (system_aw_chan_t    ),
    .system_axi_b_t    (system_b_chan_t     ),
    .system_axi_r_t    (system_r_chan_t     ),
    .system_axi_w_t    (system_w_chan_t     ),
    .system_axi_req_t  (system_req_t        ),
    .system_axi_resp_t (system_resp_t       )
  ) i_ara_system (
    .clk_i        (clk_i          ),
    .rst_ni       (rst_ni         ),
    .boot_addr_i  (boot_addr_i    ),
    .hart_id_i    (hart_id_i      ),
    .scan_enable_i(scan_enable_i  ),
    .scan_data_i  (scan_data_i    ),
    .scan_data_o  (scan_data_o    ),
    .axi_req_o    (system_axi_req ),
    .axi_resp_i   (system_axi_resp)
  );

endmodule : ara_cva6
