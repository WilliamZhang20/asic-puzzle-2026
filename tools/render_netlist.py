#!/usr/bin/env python3
"""Render useful, non-hairball views of the recovered gate netlist."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from collections import Counter, defaultdict, deque
from pathlib import Path

from simulate_netlist import FLOP_PREFIXES, OUTPUT_PINS


def svg_text(x, y, text, size, *, anchor="middle", weight="400", fill="#17212B"):
    return (f'<text x="{x}" y="{y}" text-anchor="{anchor}" '
            f'font-family="DejaVu Sans,Arial,sans-serif" font-size="{size}" '
            f'font-weight="{weight}" fill="{fill}">{text}</text>')


def render_svg(svg: Path, png: Path, width: int) -> None:
    renderer = shutil.which("rsvg-convert")
    if not renderer:
        raise SystemExit("rsvg-convert is required to produce PNG output")
    subprocess.run([renderer, "-w", str(width), "-o", str(png), str(svg)], check=True)


def drivers(instances):
    result = {}
    for instance in instances:
        for pin, net in instance["pins"].items():
            if pin in OUTPUT_PINS:
                result[net] = instance
    return result


def backward_cone(start_nets, driver):
    queue, seen_nets, seen_cells = deque(start_nets), set(), set()
    while queue:
        net = queue.popleft()
        if net in seen_nets:
            continue
        seen_nets.add(net)
        instance = driver.get(net)
        if not instance:
            continue
        seen_cells.add(instance["name"])
        if not instance["master"].startswith(FLOP_PREFIXES):
            queue.extend(n for p, n in instance["pins"].items() if p not in OUTPUT_PINS)
    return seen_cells


def placement_view(data, destination: Path):
    instances, ports = data["instances"], data["ports"]
    driver = drivers(instances)
    out_cone = backward_cone([ports[f"O[{i}]"] for i in range(8)], driver)
    success_cone = backward_cone([ports["success"]], driver)
    xs = [i["placement"][0] for i in instances]
    ys = [i["placement"][1] for i in instances]
    xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
    width, height, pad, top = 1500, 1550, 70, 65
    sx = (width - 2 * pad) / (xmax - xmin)
    sy = (height - top - pad) / (ymax - ymin)
    xy = lambda i: (pad + (i["placement"][0] - xmin) * sx,
                    height - pad - (i["placement"][1] - ymin) * sy)

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
           '<rect width="100%" height="100%" fill="#FFFFFF"/>']

    # Draw signal connections faintly to show density without overwhelming cells.
    loads = defaultdict(list)
    for instance in instances:
        for pin, net in instance["pins"].items():
            if pin not in OUTPUT_PINS:
                loads[net].append(instance)
    for net, source in driver.items():
        x1, y1 = xy(source)
        for sink in loads.get(net, []):
            x2, y2 = xy(sink)
            out.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#64748B" stroke-opacity="0.045" stroke-width="1"/>')

    for instance in instances:
        x, y = xy(instance)
        flop = instance["master"].startswith(FLOP_PREFIXES)
        in_out, in_success = instance["name"] in out_cone, instance["name"] in success_cone
        if in_out and in_success: color = "#9B5DE5"
        elif in_out: color = "#F59E0B"
        elif in_success: color = "#10B981"
        elif flop: color = "#2563EB"
        else: color = "#94A3B8"
        radius = 7 if flop else 4
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius}" fill="{color}" stroke="#FFFFFF" stroke-width="1"/>')

    legend = [("#94A3B8", "combinational cell"), ("#2563EB", "flip-flop"),
              ("#F59E0B", "O[7:0] immediate fan-in"), ("#10B981", "success immediate fan-in"),
              ("#9B5DE5", "shared by both cones")]
    lx, ly = 110, 1495
    for index, (color, label) in enumerate(legend):
        x = lx + index * 275; y = ly
        out.append(f'<circle cx="{x}" cy="{y}" r="7" fill="{color}"/>')
        out.append(svg_text(x + 14, y + 6, label.replace("combinational cell", "logic").replace("flip-flop", "flop").replace(" immediate fan-in", " cone").replace("shared by both cones", "shared"), 16, anchor="start"))
    out.append('</svg>')
    destination.write_text("\n".join(out) + "\n")


def source_flops(net, driver, port_by_net):
    queue, seen, found, ports = [net], set(), set(), set()
    while queue:
        current = queue.pop()
        if current in seen:
            continue
        seen.add(current)
        instance = driver.get(current)
        if not instance:
            if current in port_by_net:
                ports.add(port_by_net[current])
        elif instance["master"].startswith(FLOP_PREFIXES):
            found.add(instance["name"])
        else:
            queue.extend(n for p, n in instance["pins"].items() if p not in OUTPUT_PINS)
    return found, ports


def bank_graph(data, destination: Path):
    instances = data["instances"]
    flops = [i for i in instances if i["master"].startswith(FLOP_PREFIXES)]
    by_name = {i["name"]: i for i in flops}
    banks = defaultdict(list)
    for flop in flops:
        banks[flop["pins"]["CLK"]].append(flop)
    bank_of = {f["name"]: net for net, members in banks.items() for f in members}
    driver = drivers(instances)
    port_by_net = {net: name for name, net in data["ports"].items()
                   if name in {"I", "enable", "rst_n", "clk"}}
    edges, input_edges = Counter(), Counter()
    for destination_flop in flops:
        sources, ports = source_flops(destination_flop["pins"]["D"], driver, port_by_net)
        for source in sources:
            edges[(bank_of[source], bank_of[destination_flop["name"]])] += 1
        for port in ports:
            input_edges[(port, bank_of[destination_flop["name"]])] += 1

    lines = ['digraph G {', 'graph [layout=neato, overlap=false, splines=line, bgcolor="#F8FAFC", pad="0.45", outputorder=edgesfirst];',
             'node [shape=box, style="rounded,filled", fontname="DejaVu Sans", fontsize=13, color="#334155", penwidth=1.5];',
             'edge [color="#64748B88", fontname="DejaVu Sans", fontsize=9, arrowsize=.65];']
    for net, members in sorted(banks.items()):
        x = sum(i["placement"][0] for i in members) / len(members)
        y = sum(i["placement"][1] for i in members) / len(members)
        outputish = x > 105
        fill = "#FFEDD5" if outputish else "#DBEAFE"
        label = f"bank n{net}\\n{len(members)} flops"
        lines.append(f'b{net} [label="{label}", fillcolor="{fill}", pos="{x*5:.1f},{y*5:.1f}!"];')
    active_ports = {port for (port, _), count in input_edges.items() if count >= 3}
    port_y = {"enable": 850, "I": 300}
    for port in sorted(active_ports):
        lines.append(f'p_{port} [label="{port}", shape=oval, fillcolor="#DCFCE7", pos="0,{port_y[port]}!"];')
    for (source, target), count in edges.items():
        if source != target and count >= 3:
            lines.append(f'b{source} -> b{target} [label="{count}", penwidth={1 + min(count, 12)/5:.1f}];')
    for (port, target), count in input_edges.items():
        if count >= 3:
            lines.append(f'p_{port} -> b{target} [label="{count}", color="#16A34A99"];')
    lines.append('}')
    destination.write_text("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("netlist", type=Path)
    parser.add_argument("--outdir", type=Path, default=Path("artifacts/visuals"))
    args = parser.parse_args()
    data = json.loads(args.netlist.read_text())
    args.outdir.mkdir(parents=True, exist_ok=True)
    placement_svg = args.outdir / "netlist_placement.svg"
    placement_view(data, placement_svg)
    render_svg(placement_svg, args.outdir / "netlist_placement.png", 1500)
    dot = args.outdir / "register_dependencies.dot"
    bank_graph(data, dot)
    subprocess.run(["dot", "-Kneato", "-Tsvg", str(dot), "-o", str(args.outdir / "register_dependencies.svg")], check=True)
    subprocess.run(["dot", "-Kneato", "-Tpng", "-Gdpi=150", str(dot), "-o", str(args.outdir / "register_dependencies.png")], check=True)
    print(f"wrote {args.outdir / 'netlist_placement.png'}")
    print(f"wrote {args.outdir / 'register_dependencies.png'}")


if __name__ == "__main__":
    main()
