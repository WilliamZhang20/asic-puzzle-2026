# ASIC puzzle handoff

## Result

The recovered circuit accepts one unique 121-bit input.  Concrete gate-level
replay raises `success` and emits:

```text
(* TWO STARS *)
```

The comment delimiters are produced by the chip; the safest submission value is
the full string exactly as shown.

The serial input, in the order sampled on rising clock edges, is:

```text
0000000101010000100000000000010101010000000000001010000001000001000000100000101000010000000100000010000010010001010000000
```

Grouped as the intended 11x11 grid (`#` = 1/star, `.` = 0):

```text
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
```

The one-indexed star coordinates are:

```text
(1,8)  (1,10)
(2,1)  (2,6)
(3,8)  (3,10)
(4,1)  (4,3)
(5,5)  (5,7)
(6,3)  (6,9)
(7,5)  (7,11)
(8,2)  (8,7)
(9,4)  (9,11)
(10,6) (10,9)
(11,2) (11,4)
```

This is a two-star Star Battle checker.  The solution has 22 stars, exactly two
in every row, column, and irregular region, and no pair touching orthogonally or
diagonally.  The recovered region map is below; equal letters form a region:

```text
AAAAABBCDDE
AAFAABCCDDE
AAFBBBBCCDE
AAFBGGGECCE
FAFBGEEEEEE
FFFBGGGEHHH
BBBBBBGEHII
BJJJGGGEHII
BJJKEEEEHII
BBJKKEEEHHH
BJJKEEEEEEE
```

Region sizes are A=14, B=21, C=7, D=5, E=28, F=8, G=11, H=9, I=6,
J=8, and K=4.  Each contains exactly two stars in the solution.

## Reproduction

The local virtual environment contains `gdstk`, `numpy`, `shapely`, `networkx`,
and `z3-solver`.  From the repository root:

```bash
.venv/bin/python tools/gds_extract.py warmup/04_final.gds -o warmup/extracted.json
.venv/bin/python tools/validate_warmup.py warmup/extracted.json
.venv/bin/python tools/gds_extract.py puzzle.gds -o artifacts/puzzle_netlist.json
.venv/bin/python tools/simulate_netlist.py artifacts/puzzle_netlist.json --replay-vcd example_inputs.vcd
.venv/bin/python tools/solve_challenge.py artifacts/puzzle_netlist.json --max-solutions 2 -o artifacts/solution_bits.txt
.venv/bin/python tools/verify_solution.py artifacts/puzzle_netlist.json artifacts/solution_bits.txt
.venv/bin/python tools/recover_regions.py artifacts/puzzle_netlist.json --expected artifacts/region_map.txt
.venv/bin/python tools/verify_star_battle.py artifacts/region_map.txt artifacts/solution_bits.txt
```

Expected final verification output:

```text
PASS: success=1
output=(* TWO STARS *)
rows=2 each, columns=2 each, adjacent-star conflicts=0
```

To drive the chip: hold `rst_n` low and clock it, deassert `rst_n`, set `enable`
high, present the 121 bits above one per rising edge, then lower `enable` and
continue clocking.  The output bytes begin on the first post-disable rising edge.

## What was done

1. Read the repository and linked Jane Street instructions.  The target is a
   serial input that raises `success`, followed by simulation of the output
   generator to recover the final string.
2. Inspected both GDS files with `gdstk`.  Standard-cell master names and local
   pin labels remain in the hierarchy even though instance and net names were
   removed.
3. Built `tools/gds_extract.py`.  It unions conductive geometry with Shapely on
   SKY130 poly/li1/met1-met5 layers 66-72, joins poly-to-li1 at 66/44 licon
   cuts, joins li1-to-met1 at 67/44 mcon cuts, and joins higher layers at the
   explicit `VIA_*` references.  Transformed cell-pin labels and top-level port
   labels are then assigned to electrical components.
4. Validated extraction against the complete warm-up oracle.  The recovered
   result matches all 79 functional instances and all 84 logical nets with no
   missing pins, split nets, or shorts.  Modeling internal mcon connections was
   essential because some logical pins have multiple li1 access islands joined
   through met1 inside a standard cell.
5. Extracted the puzzle into `artifacts/puzzle_netlist.json`: 728 functional
   cells, including 84 resettable D flops, four settable D flops, and four plain
   D flops.  All pins resolved geometrically.
6. Confirmed SKY130 Boolean conventions against the open-source
   `sky130_fd_sc_hd` functional models, then built `tools/simulate_netlist.py`.
   Its replay of `example_inputs.vcd` exactly reproduces both `TRY AGAIN`
   sequences at timestamps 1,255,000-1,345,000 ps and
   2,815,000-2,905,000 ps, with `success=0`.
7. Built `tools/solve_challenge.py`, unrolled the recovered 92-flop transition
   system for the 121 enabled input clocks plus the first disabled clock, and
   constrained the `success` flop high.  Z3 solved it in roughly two seconds.
   Blocking the found 121-bit assignment made a second solve `unsat`, proving
   uniqueness for the modeled protocol.
8. Replayed the result with the independent concrete simulator.  `success`
   rises on the first disabled clock, and the next 15 nonzero output bytes are
   exactly `(* TWO STARS *)`.

All workloads were lightweight (the slowest extraction took about seven
seconds) and were run on the Trillium login node without a scheduler allocation.

## Adversarial verification

After the initial solve, the result was challenged with implementations and
perturbations that do not simply rerun the Z3 proof:

1. Built Icarus Verilog 12.0 (`v12_0`, commit `4fd5291`) from source under
   `/tmp`, mechanically emitted the recovered 728-cell netlist as Verilog, and
   compiled it against 64 functional-model files from the official open-source
   SKY130 HD cell library (commit `ac7fb61`).  This simulation does not use the
   Python gate evaluator.
2. The official-model simulation independently replayed both supplied negative
   attempts.  Each held `success=0` and emitted exactly `TRY AGAIN`.
3. The same official-model simulation replayed the solved input.  It held
   `success=1` and emitted exactly `(* TWO STARS *)`.
   A second emitted netlist retained every exact drive-strength master through
   66 thin wrappers instead of collapsing strengths to generic models; it also
   passed both negative traces, the solution, and all 121 mutations.
4. Exhaustively compared all 60 combinational cell masters used in the puzzle
   against the official Verilog models: all 846 possible input combinations
   matched the Python/SMT Boolean implementation.
5. Replayed the accepted input plus every one of its 121 single-bit mutations
   through the official models.  The original was accepted and every mutation
   was rejected.
6. Re-extracted `puzzle.gds` with geometry lookup tolerances of 0.5, 2, 10, and
   20 nm.  Every run resolved all 728 instances with zero unresolved pins and
   produced the identical canonical pin-to-net partition SHA-256:
   `db8853270b6b4c9cc7869a4dab1454bf4c7541fb9a2c157aa5850c5e08c60ee4`.
7. Audited the extracted graph structurally: excluding the intentional shared
   power constants, it has no multi-driver nets and no loaded-but-undriven nets.
8. Reconfirmed the formal uniqueness result: the 121-cycle condition is `sat`;
   after blocking that complete bit assignment, it is `unsat`.
9. Recovered the irregular regions without assuming Star Battle semantics.  At
   each of the 121 input positions on an all-zero trajectory, I compared the
   immediate next-state vectors for input 0 and input 1.  Eleven counter flops
   have distinct influence sets that partition all 121 positions, yielding the
   A-K map above.  The accepted grid has exactly two stars in every recovered
   set.
10. Encoded only the ordinary high-level rules (two stars per row, column, and
    recovered region; no orthogonal or diagonal touching) in a fresh Z3 model.
    Its solution matches the gate-level bitstream, and blocking it is `unsat`.
    Thus the human-readable puzzle and the extracted ASIC independently agree
    on the same unique grid.
11. Removed Z3 as a shared uniqueness dependency by exhaustively enumerating
    the high-level puzzle with a plain Python row-by-row backtracker.  It visited
    715,761 search nodes and found exactly the same single grid.

Artifact hashes for the verified run:

```text
8913ea4be5367b484d5886c3c5f7608942b67544a0dbe364b17223503b8d851a  puzzle.gds
189d5677191e6851ec75a6ce1442af11d86bc2ed58c5b8329ae063a8830793e9  artifacts/puzzle_netlist.json
64070df39199aadae9d102679086d54bc0aeab98d483a43282bf14e4bda79e90  artifacts/solution_bits.txt
620fa4d7faba2d83d412977c183c74135020f7464c82b337b91a03b83357ac50  artifacts/region_map.txt
```

The strongest remaining theoretical dependency is the geometric extraction
itself: there is no independently supplied golden netlist for the real puzzle.
That risk is bounded by exact warm-up recovery, zero unresolved real-design
pins, structural consistency, and tolerance-invariant connectivity.  The final
input/output claim is independently confirmed by the official SKY130 models.

## Files

- `tools/gds_extract.py`: geometric GDS-to-netlist extractor.
- `tools/validate_warmup.py`: exact warm-up connectivity validator.
- `tools/simulate_netlist.py`: concrete SKY130 gate/event simulator and VCD replay.
- `tools/solve_challenge.py`: Z3 transition-system solver and uniqueness check.
- `tools/verify_solution.py`: concrete final replay plus Star Battle sanity checks.
- `tools/recover_regions.py`: reconstructs the region partition from differential
  next-state influence and verifies the saved map.
- `tools/verify_star_battle.py`: independent high-level puzzle solver and
  uniqueness proof.
- `tools/enumerate_messages.py`: symbolic enumeration of every reachable
  post-input output trace; proves the chip has exactly five message paths.
- `tools/render_puzzle.py`: regenerates submission-ready region and solution
  visuals from the checked artifacts.
- `tools/render_netlist.py`: renders the recovered cell placement/fan-in cones
  and a clock-bank-collapsed register dependency graph.
- `warmup/extracted.json`: recovered warm-up netlist.
- `artifacts/puzzle_netlist.json`: recovered puzzle netlist.
- `artifacts/solution_bits.txt`: unique serial input.
- `artifacts/region_map.txt`: recovered 11-region partition.
- `artifacts/solve.log` and `artifacts/uniqueness.log`: durable solver logs; matching
  `.status` files contain exit status 0.

There is no remaining uncertainty about the accepted input, emitted string, or
human-readable Star Battle instance.
