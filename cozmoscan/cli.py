"""Command-line entry point: one command per capture, per the case study spec.

    python -m cozmoscan.cli scan --capture-dir <dir> --tier lidar --room-id living_room --out out/living_room
    python -m cozmoscan.cli stitch --rooms out/a/result.json out/b/result.json \\
        --connectors connectors.json --placements placements.json --out out/property

Run `python -m cozmoscan.cli scan --help` / `stitch --help` for the full flag list.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cozmoscan.damage.rules import SurfaceTag
from cozmoscan.geometry.stitching import Connector, RoomPlacement
from cozmoscan.pipeline import DamagePhotoSpec, PipelineConfig, run_single_room, run_stitch


def _load_damage_manifest(path: str | None) -> list[DamagePhotoSpec]:
    if not path:
        return []
    entries = json.loads(Path(path).read_text())
    return [
        DamagePhotoSpec(surface_id=e["surface_id"], path=Path(e["path"]), pixels_per_meter=e["pixels_per_meter"], wall_index=e["wall_index"])
        for e in entries
    ]


def _load_surface_tags(path: str | None) -> dict[str, SurfaceTag] | None:
    if not path:
        return None
    raw = json.loads(Path(path).read_text())
    return {
        surface_id: SurfaceTag(
            surface_id=surface_id,
            has_plumbing=v.get("has_plumbing", False),
            is_exterior_wall=v.get("is_exterior_wall", False),
            is_below_grade=v.get("is_below_grade", False),
        )
        for surface_id, v in raw.items()
    }


def cmd_scan(args: argparse.Namespace) -> int:
    result = run_single_room(
        capture_dir=Path(args.capture_dir),
        tier=args.tier,
        room_id=args.room_id,
        out_dir=Path(args.out),
        config=PipelineConfig(),
        damage_photos=_load_damage_manifest(args.damage_manifest),
        surface_tags=_load_surface_tags(args.surface_tags),
    )
    n_openings = sum(len(w["openings"]) for w in result["room"]["walls"])
    print(f"OK: wrote {args.out}/result.json + {args.out}/{result['render_path']}")
    print(f"  room_id={result['room']['room_id']} tier={result['room']['tier']} walls={len(result['room']['walls'])} openings={n_openings}")
    print(f"  damage_regions={len(result['damage_regions'])} scope_line_items={len(result['scope_line_items'])}")
    return 0


def cmd_stitch(args: argparse.Namespace) -> int:
    connectors = [Connector(**c) for c in json.loads(Path(args.connectors).read_text())]
    placements = [RoomPlacement(**p) for p in json.loads(Path(args.placements).read_text())]
    result = run_stitch(
        room_json_paths=[Path(p) for p in args.rooms],
        connectors=connectors,
        placements=placements,
        out_dir=Path(args.out),
        correct_drift=not args.no_drift_correction,
        anchor_room_id=args.anchor,
    )
    print(f"OK: wrote {args.out}/property_result.json + {args.out}/{result['render_path']}")
    print(f"  rooms={[r['room_id'] for r in result['rooms']]} drift_correction={not args.no_drift_correction}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cozmoscan")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="Reconstruct one room from one raw capture (one command per capture).")
    scan.add_argument("--capture-dir", required=True, help="Path to a Stray Scanner-format capture directory.")
    scan.add_argument("--tier", required=True, choices=["lidar", "video", "photo"])
    scan.add_argument("--room-id", required=True)
    scan.add_argument("--out", required=True, help="Output directory for result.json + plan.png.")
    scan.add_argument("--damage-manifest", help="JSON file: list of {surface_id, path, pixels_per_meter, wall_index}.")
    scan.add_argument("--surface-tags", help="JSON file: {surface_id: {has_plumbing, is_exterior_wall, is_below_grade}}.")
    scan.set_defaults(func=cmd_scan)

    stitch = sub.add_parser("stitch", help="Combine N already-scanned rooms into one multi-room property.")
    stitch.add_argument("--rooms", nargs="+", required=True, help="Paths to each room's result.json (from `scan`).")
    stitch.add_argument("--connectors", required=True, help="JSON file: list of {room_a, wall_a, room_b, wall_b}.")
    stitch.add_argument("--placements", required=True, help="JSON file: list of {room_id, x, z, rotation_rad}.")
    stitch.add_argument("--out", required=True, help="Output directory for property_result.json + property_plan.png.")
    stitch.add_argument("--no-drift-correction", action="store_true", help="Disable Manhattan-snap drift correction (ablation 'off').")
    stitch.add_argument("--anchor", help="room_id to hold fixed at its given placement (default: first room).")
    stitch.set_defaults(func=cmd_stitch)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # pragma: no cover - top-level CLI error reporting
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
