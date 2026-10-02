"""Render a RoomModel / list of RoomModels (a stitched property) to a dimensioned top-down PNG.

This is the "rendered plan" deliverable: a homeowner-recognisable floor plan, not a debug plot.
Walls are drawn as thick black segments, openings as gaps with a door/window tick, dimensions
are annotated on each wall, and optional damage regions are overlaid as translucent patches.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Polygon as MplPolygon

from cozmoscan.types import RoomModel

WALL_COLOR = "#2b2b2b"
OPENING_COLOR = "#ffffff"
DOOR_TICK_COLOR = "#1565c0"
WINDOW_TICK_COLOR = "#2e7d32"
DAMAGE_COLORS = {
    "moisture_stain": "#8d6e63",
    "structural_crack": "#c62828",
    "mold": "#33691e",
}


def render_property_plan(
    rooms: list[RoomModel],
    out_path: Path,
    damage_regions: list[dict] | None = None,
    title: str = "",
) -> Path:
    fig, ax = plt.subplots(figsize=(10, 8))
    all_xy = []

    for room in rooms:
        poly_global = room.to_global_xy(room.floor_polygon)
        all_xy.append(poly_global)
        ax.add_patch(MplPolygon(poly_global, closed=True, facecolor="#f5f5f0", edgecolor="none", zorder=1))
        centroid = poly_global.mean(axis=0)
        ax.text(*centroid, room.room_id, ha="center", va="center", fontsize=10, weight="bold", zorder=5)

        for wall in room.walls:
            p1, p2 = room.to_global_xy(np.array([wall.p1, wall.p2]))
            wall_vec = p2 - p1
            wall_len_px = np.linalg.norm(wall_vec)
            direction = wall_vec / wall_len_px if wall_len_px > 1e-9 else wall_vec
            normal = np.array([-direction[1], direction[0]])

            if not wall.openings:
                ax.plot(*zip(p1, p2), color=WALL_COLOR, linewidth=4, zorder=3, solid_capstyle="butt")
            else:
                segs = sorted(wall.openings, key=lambda o: o.start_m)
                cursor = 0.0
                for o in segs:
                    seg_start, seg_end = p1 + direction * cursor, p1 + direction * o.start_m
                    if o.start_m > cursor:
                        ax.plot(*zip(seg_start, seg_end), color=WALL_COLOR, linewidth=4, zorder=3, solid_capstyle="butt")
                    gap_a = p1 + direction * o.start_m
                    gap_b = p1 + direction * (o.start_m + o.width.value)
                    ax.plot(*zip(gap_a, gap_b), color=OPENING_COLOR, linewidth=4, zorder=4, solid_capstyle="butt")
                    tick_color = DOOR_TICK_COLOR if o.kind == "door" else WINDOW_TICK_COLOR
                    mid = (gap_a + gap_b) / 2
                    ax.plot(*zip(mid - normal * 0.05, mid + normal * 0.05), color=tick_color, linewidth=2, zorder=6)
                    cursor = o.start_m + o.width.value
                if cursor < wall.length.value:
                    seg_start, seg_end = p1 + direction * cursor, p2
                    ax.plot(*zip(seg_start, seg_end), color=WALL_COLOR, linewidth=4, zorder=3, solid_capstyle="butt")

            mid = (p1 + p2) / 2 + normal * 0.25
            ax.text(
                *mid,
                f"{wall.length.value:.2f}±{wall.length.ci:.2f} m",
                ha="center",
                va="center",
                fontsize=7,
                color="#444",
                zorder=7,
            )

        if room.ceiling_height is not None:
            label = f"H: {room.ceiling_height.value:.2f}±{room.ceiling_height.ci:.2f} m   A: {room.floor_area.value:.1f}±{room.floor_area.ci:.1f} m²"
        else:
            label = f"H: n/a (no ceiling observed)   A: {room.floor_area.value:.1f}±{room.floor_area.ci:.1f} m²"
        ax.text(centroid[0], centroid[1] - 0.3, label, ha="center", va="center", fontsize=7, color="#555", zorder=5)

    for dmg in damage_regions or []:
        poly = np.array(dmg["polygon_xy"])
        color = DAMAGE_COLORS.get(dmg["damage_class"], "#ff00ff")
        ax.add_patch(MplPolygon(poly, closed=True, facecolor=color, edgecolor=color, alpha=0.45, zorder=8))
        c = poly.mean(axis=0)
        ax.text(c[0], c[1], f"{dmg['damage_class']}\n{dmg['area_m2']:.2f} m²", ha="center", va="center", fontsize=6, zorder=9)

    all_pts = np.concatenate(all_xy, axis=0)
    pad = 0.6
    ax.set_xlim(all_pts[:, 0].min() - pad, all_pts[:, 0].max() + pad)
    ax.set_ylim(all_pts[:, 1].min() - pad, all_pts[:, 1].max() + pad)
    ax.set_aspect("equal")
    ax.set_title(title or "Cozmo Scan — rendered plan")
    ax.set_xlabel("meters")
    ax.set_ylabel("meters")
    ax.grid(True, linestyle=":", alpha=0.3)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return out_path
