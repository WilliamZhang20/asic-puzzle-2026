#!/usr/bin/env python3
"""Mechanically emit the extracted netlist as structural Verilog, plus a
self-checking testbench, so the result can be re-simulated against the
official open-source SKY130 functional models instead of the Python gate
evaluator in simulate_netlist.py.

Usage:
    python tools/emit_verilog.py artifacts/puzzle_netlist.json \
        --outdir build/verilog --bits artifacts/solution_bits.txt
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

SUPPLY_PINS = ("VPWR", "VGND", "VPB", "VNB")


def net_name(net: int) -> str:
    return f"n{net}"


def emit_netlist(data: dict) -> str:
    ports = data["ports"]
    power = {ports["VPWR"], ports["VGND"]}
    # Input nets are declared and driven by the continuous assignments below;
    # every other net (including the success/O output nets) needs a plain
    # wire declaration.
    driven_elsewhere = power | {ports[name] for name in ("clk", "rst_n", "enable", "I")}

    lines = ["`default_nettype none", "", "module puzzle ("]
    decls = []
    for name in ("clk", "rst_n", "enable", "I"):
        decls.append(f"    input wire {name}")
    decls.append("    output wire success")
    decls.append("    output wire [7:0] O")
    lines.append(",\n".join(decls))
    lines.append(");")

    nets = sorted({net for inst in data["instances"] for net in inst["pins"].values()})
    for net in nets:
        if net in driven_elsewhere:
            continue
        lines.append(f"  wire {net_name(net)};")

    # Bind the port names onto their extracted nets.
    lines.append("")
    lines.append(f"  wire {net_name(ports['VPWR'])};")
    lines.append(f"  wire {net_name(ports['VGND'])};")
    lines.append(f"  assign {net_name(ports['VPWR'])} = 1'b1;")
    lines.append(f"  assign {net_name(ports['VGND'])} = 1'b0;")
    lines.append("")
    for name in ("clk", "rst_n", "enable", "I"):
        lines.append(f"  wire {net_name(ports[name])} = {name};")
    lines.append(f"  assign success = {net_name(ports['success'])};")
    for bit in range(8):
        lines.append(f"  assign O[{bit}] = {net_name(ports[f'O[{bit}]'])};")
    lines.append("")

    for inst in data["instances"]:
        master = f"sky130_fd_sc_hd__{inst['master']}"
        conns = [f".{pin}({net_name(net)})" for pin, net in sorted(inst["pins"].items())]
        conns += [
            f".VPWR({net_name(ports['VPWR'])})",
            f".VGND({net_name(ports['VGND'])})",
            f".VPB({net_name(ports['VPWR'])})",
            f".VNB({net_name(ports['VGND'])})",
        ]
        lines.append(f"  {master} {inst['name']} (" + ", ".join(conns) + ");")

    lines.append("endmodule")
    lines.append("`default_nettype wire")
    return "\n".join(lines) + "\n"


TESTBENCH = """`timescale 1ns/1ps
module tb;
  reg clk = 0, rst_n = 0, enable = 0, I = 0;
  wire success;
  wire [7:0] O;
  integer i, emitted;
  reg [0:120] pattern;

  puzzle dut (.clk(clk), .rst_n(rst_n), .enable(enable), .I(I),
              .success(success), .O(O));

  task step; begin #1 clk = 1; #1 clk = 0; end endtask

  initial begin
    if (!$value$plusargs("bits=%s", pattern)) begin
      $display("ERROR: pass +bits=<121 binary digits>");
      $finish;
    end
    for (i = 0; i < 3; i = i + 1) step;
    rst_n = 1; enable = 1;
    for (i = 0; i < 121; i = i + 1) begin
      I = (pattern[i] == "1");
      step;
    end
    enable = 0; I = 0;
    emitted = 0;
    for (i = 0; i < 200; i = i + 1) begin
      #1 clk = 1;
      if (O !== 8'h00) begin
        $write("%c", O);
        emitted = emitted + 1;
      end else if (emitted > 0) begin
        i = 200;
      end
      #1 clk = 0;
    end
    $write("\\n");
    $display("success=%b", success);
    $finish;
  end
endmodule
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("netlist", type=Path)
    parser.add_argument("--outdir", type=Path, default=Path("build/verilog"))
    args = parser.parse_args()

    data = json.loads(args.netlist.read_text())
    args.outdir.mkdir(parents=True, exist_ok=True)
    (args.outdir / "puzzle.v").write_text(emit_netlist(data))
    (args.outdir / "tb.v").write_text(TESTBENCH)
    print(f"wrote {args.outdir / 'puzzle.v'} ({len(data['instances'])} instances)")
    print(f"wrote {args.outdir / 'tb.v'}")
    print()
    print("Then, with Icarus Verilog and the SKY130 HD library available:")
    print("  iverilog -g2012 -o sim \\")
    print("    -y $SKY130/cells -I $SKY130/cells \\")
    print(f"    {args.outdir / 'puzzle.v'} {args.outdir / 'tb.v'}")
    print("  vvp sim +bits=$(cat artifacts/solution_bits.txt)")


if __name__ == "__main__":
    main()
