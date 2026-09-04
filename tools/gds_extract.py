#!/usr/bin/env python3
"""Recover a gate-level netlist from the routed conductors in a SKY130 GDS.

The puzzle GDS retains standard-cell hierarchy and local pin labels, but strips
top-level instance and net names.  This program unions conductor geometry on
li1 through met5, joins layers at explicit via references, and maps transformed
cell pin labels onto the resulting electrical components.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

import gdstk
from shapely import GeometryCollection, MultiPolygon, Point, Polygon
from shapely.ops import unary_union
from shapely.strtree import STRtree


CONDUCTOR_LAYERS = range(66, 73)  # poly, li1, met1, met2, met3, met4, met5
CONDUCTOR_DTYPES = {16, 20}       # pin and drawing purposes
IGNORED_MASTERS = {
    "sky130_fd_sc_hd__decap_3",
    "sky130_fd_sc_hd__tapvpwrvgnd_1",
    "sky130_fd_sc_hd__diode_2",
}
IGNORED_PINS = {"VPWR", "VGND", "VPB", "VNB"}


class DSU:
    def __init__(self, n: int):
        self.p = list(range(n))

    def find(self, x: int) -> int:
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: int, b: int) -> None:
        a, b = self.find(a), self.find(b)
        if a != b:
            self.p[b] = a


def transformed_point(point, ref):
    x, y = point
    if ref.x_reflection:
        y = -y
    angle = ref.rotation or 0.0
    scale = ref.magnification or 1.0
    ca, sa = math.cos(angle), math.sin(angle)
    return (
        ref.origin[0] + scale * (x * ca - y * sa),
        ref.origin[1] + scale * (x * sa + y * ca),
    )


def placement_corner(ref):
    """Return the lower-left placed boundary, matching DEF coordinates."""
    boundaries = [p for p in ref.cell.polygons if p.layer == 236]
    if not boundaries:
        return ref.origin
    ((x0, y0), (x1, y1)) = boundaries[0].bounding_box()
    corners = [
        transformed_point((x, y), ref)
        for x in (x0, x1)
        for y in (y0, y1)
    ]
    return (min(p[0] for p in corners), min(p[1] for p in corners))


def polygon_parts(geometry):
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    if isinstance(geometry, GeometryCollection):
        return [g for g in geometry.geoms if isinstance(g, Polygon)]
    raise TypeError(type(geometry))


def locate(point, regions, tree, tolerance=0.002):
    """Return region indices covering a point (with a 2 nm GDS tolerance)."""
    probe = Point(point).buffer(tolerance)
    return [int(i) for i in tree.query(probe) if regions[int(i)].intersects(probe)]


def extract(path: Path, verbose: bool = True):
    lib = gdstk.read_gds(str(path))
    tops = lib.top_level()
    if len(tops) != 1:
        raise RuntimeError(f"expected one top cell, found {[c.name for c in tops]}")
    top = tops[0]

    raw = defaultdict(list)
    # get_polygons also polygonizes paths.  depth=1 includes the direct child
    # masters (standard cells and via cells) but nothing below them.
    contact_cuts = defaultdict(list)
    for poly in top.get_polygons(depth=1):
        if poly.layer in CONDUCTOR_LAYERS and poly.datatype in CONDUCTOR_DTYPES:
            shape = Polygon(poly.points)
            if shape.is_valid and not shape.is_empty:
                raw[poly.layer].append(shape)
        # In SKY130 the 66/44 licon cuts bridge poly to li1 when a cut lies
        # over poly.  Joining these is needed because one logical input pin
        # can have several li1 access islands tied together by a poly gate.
        elif poly.layer in (66, 67) and poly.datatype == 44:
            contact_cuts[poly.layer].append(Polygon(poly.points).centroid)

    regions = {}
    trees = {}
    offsets = {}
    total = 0
    for layer in CONDUCTOR_LAYERS:
        offsets[layer] = total
        merged = unary_union(raw[layer])
        regions[layer] = polygon_parts(merged)
        trees[layer] = STRtree(regions[layer])
        total += len(regions[layer])
        if verbose:
            print(
                f"layer {layer}: {len(raw[layer])} shapes -> "
                f"{len(regions[layer])} conductor components",
                flush=True,
            )

    dsu = DSU(total)

    contact_count = defaultdict(int)
    for lower_layer, cuts in contact_cuts.items():
        upper_layer = lower_layer + 1
        for cut in cuts:
            lower = locate(cut.coords[0], regions[lower_layer], trees[lower_layer])
            upper = locate(cut.coords[0], regions[upper_layer], trees[upper_layer])
            if len(lower) == 1 and len(upper) == 1:
                dsu.union(
                    offsets[lower_layer] + lower[0], offsets[upper_layer] + upper[0]
                )
                contact_count[lower_layer] += 1

    # A via reference explicitly connects all conductor layers present in its
    # master.  Merely overlapping different metal layers is not a connection.
    via_count = 0
    for ref in top.references:
        if not ref.cell.name.startswith("VIA_"):
            continue
        layers = sorted(
            {
                p.layer
                for p in ref.cell.polygons
                if p.layer in CONDUCTOR_LAYERS and p.datatype in CONDUCTOR_DTYPES
            }
        )
        if len(layers) < 2:
            continue
        found = []
        for layer in layers:
            hits = locate(ref.origin, regions[layer], trees[layer])
            if len(hits) != 1:
                raise RuntimeError(
                    f"via {ref.cell.name} at {ref.origin} has {len(hits)} "
                    f"covering regions on layer {layer}"
                )
            found.append(offsets[layer] + hits[0])
        for other in found[1:]:
            dsu.union(found[0], other)
        via_count += 1

    # Assign stable compact net numbers after all cross-layer unions.
    roots = {}

    def net_for(layer, region_index):
        root = dsu.find(offsets[layer] + region_index)
        if root not in roots:
            roots[root] = len(roots)
        return roots[root]

    instances = []
    unresolved = []
    cell_serial = defaultdict(int)
    for ref in top.references:
        master = ref.cell.name
        if not master.startswith("sky130_fd_sc_hd__") or master in IGNORED_MASTERS:
            continue
        short = master.removeprefix("sky130_fd_sc_hd__")
        serial = cell_serial[short]
        cell_serial[short] += 1
        pins = {}
        pin_points = defaultdict(list)
        for label in ref.cell.labels:
            if label.layer != 67 or label.texttype != 5:
                continue
            if label.text in IGNORED_PINS:
                continue
            pin_points[label.text].append(transformed_point(label.origin, ref))
        for pin, points in pin_points.items():
            candidates = set()
            for point in points:
                for hit in locate(point, regions[67], trees[67]):
                    candidates.add(net_for(67, hit))
            if len(candidates) == 1:
                pins[pin] = candidates.pop()
            else:
                unresolved.append(
                    {
                        "instance": f"{short}_{serial}",
                        "pin": pin,
                        "points": points,
                        "candidate_nets": sorted(candidates),
                    }
                )
        instances.append(
            {
                "name": f"{short}_{serial}",
                "master": short,
                "origin": list(ref.origin),
                "placement": list(placement_corner(ref)),
                "rotation": ref.rotation or 0.0,
                "x_reflection": ref.x_reflection,
                "pins": pins,
            }
        )

    ports = {}
    for label in top.labels:
        if label.layer not in CONDUCTOR_LAYERS or label.texttype != 5:
            continue
        hits = locate(label.origin, regions[label.layer], trees[label.layer])
        candidates = {net_for(label.layer, hit) for hit in hits}
        if len(candidates) == 1:
            ports[label.text] = candidates.pop()
        elif label.text not in IGNORED_PINS:
            unresolved.append(
                {
                    "port": label.text,
                    "point": list(label.origin),
                    "candidate_nets": sorted(candidates),
                }
            )

    result = {
        "source": str(path),
        "top": top.name,
        "stats": {
            "conductor_components_before_vias": total,
            "vias": via_count,
            "poly_licon_contacts": contact_count[66],
            "li1_mcon_contacts": contact_count[67],
            "nets_observed": len(roots),
            "instances": len(instances),
            "unresolved": len(unresolved),
        },
        "ports": ports,
        "instances": instances,
        "unresolved": unresolved,
    }
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("gds", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    result = extract(args.gds, not args.quiet)
    rendered = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n")
        if not args.quiet:
            print(json.dumps(result["stats"], indent=2))
            print(f"wrote {args.output}")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
