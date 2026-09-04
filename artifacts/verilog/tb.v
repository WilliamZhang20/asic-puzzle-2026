`timescale 1ns/1ps
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
    $write("\n");
    $display("success=%b", success);
    $finish;
  end
endmodule
