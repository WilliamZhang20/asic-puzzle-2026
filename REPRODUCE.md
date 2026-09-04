# Reproducing the result from scratch

Everything below was re-run end to end on a clean checkout; the commands,
outputs and timings are the real ones. Total wall time for the full sequence is
about one minute on a single core.

## 0. Environment

Python 3.11 with three dependencies. Nothing else is required for steps 1-9.

```bash
cd /project/def-yashpant/wzhang20/asic-puzzle-2026
python3.11 -m venv .venv
.venv/bin/pip install gdstk shapely z3-solver
```

Versions used: `gdstk 1.0.1`, `shapely 2.1.2`, `z3 4.15.4`, CPython 3.11.4.

All commands below are run from the repository root, and all scripts import
`simulate_netlist` from their own directory, so invoke them by path
(`.venv/bin/python tools/<script>.py`) rather than copying them elsewhere.

Input files as shipped:

```text
8913ea4be5367b484d5886c3c5f7608942b67544a0dbe364b17223503b8d851a  puzzle.gds
```

---

## 1. Calibrate the extractor on the warm-up design

The warm-up ships both a GDS and the golden gate-level netlist that produced
it, so it is the only place the geometric extractor can be checked against
ground truth. Do this first — if it fails, nothing downstream is trustworthy.

```bash
.venv/bin/python tools/gds_extract.py warmup/04_final.gds -o warmup/extracted.json
```

`tools/gds_extract.py` unions the drawn shapes on layers 66-72 (poly, li1,
met1-met5) with Shapely, connects components through `licon`/`mcon` contacts
and the explicit `VIA_*` references, then resolves each standard-cell pin to
the net covering its pin geometry. Expected tail of the output:

```text
"nets_observed": 86, "instances": 79, "unresolved": 0
```

Then compare against the golden Verilog and DEF:

```bash
.venv/bin/python tools/validate_warmup.py warmup/extracted.json
```

```text
validated 79 functional instances and 84 logical nets
PASS: no missing pins, split nets, or shorted nets
```

`validate_warmup.py` checks three separate failure modes, not just cell counts:
missing pins, one golden net split across several extracted nets, and two
golden nets shorted into one.

Optional sanity read: `warmup/00_source.v` is the RTL, two shift registers plus
an adder and `comparator496`.

## 2. Extract the real design

```bash
.venv/bin/python tools/gds_extract.py puzzle.gds -o artifacts/puzzle_netlist.json
```

~18 s. Expected:

```text
"nets_observed": 728, "instances": 728, "unresolved": 0
189d5677191e6851ec75a6ce1442af11d86bc2ed58c5b8329ae063a8830793e9  artifacts/puzzle_netlist.json
```

`unresolved: 0` is the load-bearing number: every pin of all 728 cells landed on
exactly one net. The design is 66 distinct `sky130_fd_sc_hd` masters, of which
92 instances are flops (`dfrtp_2`, `dfstp_2`, `dfxtp_2`).

To confirm the extraction is not an artifact of one tolerance setting, edit the
default in `locate()` at `tools/gds_extract.py:87` (2 nm) to 0.5, 10 and 20 nm
and re-run; all four produce the same connectivity.

## 3. Negative control: replay the supplied waveform

Before trusting the simulator, check it reproduces the failures the puzzle
author handed us.

```bash
.venv/bin/python tools/simulate_netlist.py artifacts/puzzle_netlist.json \
    --replay-vcd example_inputs.vcd
```

`tools/simulate_netlist.py` is the gate-level evaluator: `gate_value()`
implements each SKY130 master's Boolean function (AOI/OAI cells by grouping
pins on their leading letter and inverting when the output pin is `Y`), and the
`Simulator` class settles combinational logic to a fixed point, applies async
set/reset, then clocks the flops. It prints one line per clock edge; filter out
the idle ones with `| grep -v "O=0x00 success=0"`. Expected, once per attempt:

```text
 1255000: O=0x54 success=0     <- 'T'
 1265000: O=0x52 success=0     <- 'R'
 1275000: O=0x59 success=0     <- 'Y'
 1285000: O=0x20 success=0
 1295000: O=0x41 success=0     <- 'A'
 1305000: O=0x47 success=0     <- 'G'
 1315000: O=0x41 success=0     <- 'A'
 1325000: O=0x49 success=0     <- 'I'
 1335000: O=0x4e success=0     <- 'N'
```

and the same nine bytes again starting at 2815000. `success` never rises.

Both supplied attempts are rejected, exactly as the README says they should be.

## 4. Solve, and prove the solution unique

```bash
.venv/bin/python tools/solve_challenge.py artifacts/puzzle_netlist.json \
    --max-solutions 2 -o artifacts/solution_bits.txt
```

~7 s. `tools/solve_challenge.py` unrolls the 92-flop transition system for 121
input cycles plus the one cycle where `enable` drops, with the 121 input bits as
free Z3 booleans, and asserts the `success` flop high at the end. `--max-solutions 2`
asks for a solution and then blocks that exact assignment and asks again:

```text
sat
solution 1: 0000000101010000100000000000010101010000000000001010000001000001000000100000101000010000000100000010000010010001010000000
.......#.#.
#....#.....
.......#.#.
#.#........
....#.#....
..#.....#..
....#.....#
.#....#....
...#......#
.....#..#..
.#.#.......
unsat
```

`sat` then `unsat` is the uniqueness proof: no second 121-bit input asserts
`success`.

## 5. Concrete replay of the answer

The Z3 model is a claim about a formula; this replays it on the actual gates.

```bash
.venv/bin/python tools/verify_solution.py artifacts/puzzle_netlist.json \
    artifacts/solution_bits.txt
```

```text
PASS: success=1
output=(* TWO STARS *)
rows=2 each, columns=2 each, adjacent-star conflicts=0
```

This is the submission string. The chip emits exactly 15 bytes on `O[7:0]` —
`28 2a 20 54 57 4f 20 53 54 41 52 53 20 2a 29` — then zeros forever; the `(*`
and `*)` delimiters come out of the hardware, they are not framing added here.

## 6. Recover the human puzzle without assuming Star Battle

```bash
.venv/bin/python tools/recover_regions.py artifacts/puzzle_netlist.json \
    --expected artifacts/region_map.txt
```

`tools/recover_regions.py` does not pattern-match on anything puzzle-shaped. At
each of the 121 input positions along an all-zeros trajectory it computes the
next-state vector for input 0 and for input 1 and diffs them. Eleven counter
flops turn out to have disjoint influence sets that exactly partition the 121
positions — those sets *are* the irregular regions.

```text
AAAAABBCDDE     A: 14 cells, flop=dfrtp_2_78
AAFAABCCDDE     B: 21 cells, flop=dfrtp_2_29
AAFBBBBCCDE     C:  7 cells, flop=dfrtp_2_77
AAFBGGGECCE     D:  5 cells, flop=dfrtp_2_76
FAFBGEEEEEE     E: 28 cells, flop=dfrtp_2_27
FFFBGGGEHHH     F:  8 cells, flop=dfrtp_2_83
BBBBBBGEHII     G: 11 cells, flop=dfrtp_2_82
BJJJGGGEHII     H:  9 cells, flop=dfrtp_2_74
BJJKEEEEHII     I:  6 cells, flop=dfrtp_2_28
BBJKKEEEHHH     J:  8 cells, flop=dfrtp_2_30
BJJKEEEEEEE     K:  4 cells, flop=dfrtp_2_75
PASS: recovered map matches expected artifact
```

## 7. Close the loop at the puzzle level

```bash
.venv/bin/python tools/verify_star_battle.py artifacts/region_map.txt \
    artifacts/solution_bits.txt
```

~18 s. This encodes *only* the ordinary two-star rules (2 per row, 2 per column,
2 per recovered region, no orthogonal or diagonal touching) in a fresh Z3 model
that never sees the netlist, and separately runs a plain Python row-by-row
backtracker with no solver at all.

```text
PASS: high-level Star Battle solution matches gate-level bitstream
PASS: blocking the solution is UNSAT (unique)
PASS: independent backtracker found one solution (715761 nodes)
region sizes: A=14 B=21 C=7 D=5 E=28 F=8 G=11 H=9 I=6 J=8 K=4
```

The gate-level answer and the human-level answer agree, derived through
completely separate paths, and the backtracker removes Z3 as a shared
dependency of the uniqueness claim.

### Submission visuals

Render the recovered region map and its unique solution as publication-sized
PNG files (SVG source is retained alongside each image):

```bash
.venv/bin/python tools/render_puzzle.py artifacts/region_map.txt \
    artifacts/solution_bits.txt --outdir artifacts/visuals
```

This writes `recovered_puzzle.png`, showing only the reverse-engineered puzzle,
and `solved_puzzle.png`, overlaying the 22-star solution and exact chip output.

Two complementary netlist views can also be regenerated directly from the
extracted JSON:

```bash
.venv/bin/python tools/render_netlist.py artifacts/puzzle_netlist.json \
    --outdir artifacts/visuals
```

`netlist_placement.png` plots all 728 cells at their recovered GDS positions,
with flip-flops and the immediate `success`/`O[7:0]` fan-in cones highlighted.
`register_dependencies.png` collapses the otherwise unreadable 92-node,
801-edge register graph into its 16 recovered clock banks; edge labels count
the underlying flop-to-flop dependencies.

## 8. Easter eggs

### The chip has five messages, not two

```bash
for p in zeros ones random; do
  .venv/bin/python tools/probe_messages.py artifacts/puzzle_netlist.json --pattern $p
done
.venv/bin/python tools/probe_messages.py artifacts/puzzle_netlist.json \
    --pattern file --bits artifacts/solution_bits.txt
```

```text
stars=0    success=0  'EMPTY SKY'
stars=121  success=0  'BIG BANG'
stars=68   success=0  'TRY AGAIN'
stars=22   success=1  '(* TWO STARS *)'
```

An empty grid and a completely full grid each get their own joke response. Each
trigger is an exact iff — provable by adding the negated condition to the Z3
unrolling from step 4 and checking `unsat`; in particular `success` high and
first output byte `0x28` imply each other, which is a second uniqueness proof
through a different observable than the `success` flop.

Those four targeted probes miss a fifth, more specific failure path. Enumerate
observable output traces symbolically instead of guessing inputs:

```bash
.venv/bin/python tools/enumerate_messages.py artifacts/puzzle_netlist.json \
    --trace-clocks 80
```

The script symbolically executes all 121 free input bits, records `O[7:0]` for
80 post-input clocks, asks Z3 for one reachable trace, blocks that entire trace,
and repeats. It therefore partitions all 2^121 inputs by externally visible
output without enumerating the inputs individually:

```text
trace 1: stars=  0 success=0 message='EMPTY SKY'
trace 2: stars= 42 success=0 message='TRY AGAIN'
trace 3: stars= 22 success=0 message='TWO NOT TOUCH'
trace 4: stars= 22 success=1 message='(* TWO STARS *)'
trace 5: stars=121 success=0 message='BIG BANG'
unsat after blocking 5 distinct output traces
```

The star counts shown for `TRY AGAIN` and `TWO NOT TOUCH` are merely example
witnesses chosen by Z3. The `TWO NOT TOUCH` witness has exactly two stars in
every row, column, and recovered region, but contains touching star pairs; the
message is the checker's terse reminder that stars may not touch, including
diagonally. `unsat` proves there is no sixth output trace within the complete
80-clock output window.

### The supplied "wrong" waveform spells a sentence

```bash
.venv/bin/python tools/decode_vcd_message.py example_inputs.vcd
```

Both failing attempts are 121 bits with 38 stars and columns 7-10 always zero.
Reading columns 0-6 of each row as a 7-bit character, LSB first:

```text
attempt 1: 'The night s'
attempt 2: 'ky awaits  '
hidden message: 'The night sky awaits  '
```

This also independently confirms that the 121-bit stream is a row-major 11x11
grid — the decode only produces English under that reading.

### Two more

`(* ... *)` is OCaml comment syntax, Jane Street's house language. And the
warm-up's magic constant, `assign eq = (val == 9'd496)` in `warmup/00_source.v`,
is the third perfect number.

## 9. Optional: re-simulate against the official SKY130 models

The strongest independent check replaces the Python gate evaluator entirely
with the vendor's own Verilog. Requires Icarus Verilog and a checkout of
`google/skywater-pdk-libs-sky130_fd_sc_hd` (neither is installed on this host).

```bash
.venv/bin/python tools/emit_verilog.py artifacts/puzzle_netlist.json \
    --outdir build/verilog
iverilog -g2012 -o build/sim -y $SKY130/cells -I $SKY130/cells \
    build/verilog/puzzle.v build/verilog/tb.v
vvp build/sim +bits=$(cat artifacts/solution_bits.txt)
```

`tools/emit_verilog.py` writes the 728 instances out verbatim as structural
Verilog against `sky130_fd_sc_hd__*` masters with the power pins tied off, plus
a testbench that drives the standard protocol and prints the emitted string.
Expected: `(* TWO STARS *)` and `success=1`. Feeding it either attempt from
`example_inputs.vcd`, or any single-bit mutation of the solution, should print
`TRY AGAIN` with `success=0`.

## Expected artifact hashes

```text
189d5677191e6851ec75a6ce1442af11d86bc2ed58c5b8329ae063a8830793e9  artifacts/puzzle_netlist.json
64070df39199aadae9d102679086d54bc0aeab98d483a43282bf14e4bda79e90  artifacts/solution_bits.txt
620fa4d7faba2d83d412977c183c74135020f7464c82b337b91a03b83357ac50  artifacts/region_map.txt
```
