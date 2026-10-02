"""End-to-end per-capture orchestration: raw capture directory -> RoomModel (+ optional damage
regions/scope) -> schema-validated JSON + rendered plan PNG. ``run_single_room`` is the "one
command per capture" entry point the CLI (cozmoscan/cli.py) wraps directly. Stitching multiple
already-scanned rooms into one property (``run_stitch``) is a separate, also-single-command,
step since it inherently needs >1 capture's output as input -- it cannot be "per capture".
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from cozmoscan.capture.photo_tier import PhotoTierConfig, load_photo_capture, photo_room_model
from cozmoscan.capture.stray_scanner import StrayScannerConfig, load_lidar_capture
from cozmoscan.capture.video_tier import VideoTierConfig, load_video_capture
from cozmoscan.damage.detector import DamageDetectorConfig, detect_damage, to_damage_region
from cozmoscan.damage.rules import SurfaceTag, infer_concealed_risks
from cozmoscan.damage.scope import generate_scope
from cozmoscan.geometry.manhattan_room import ManhattanConfig, fit_room_box
from cozmoscan.geometry.stitching import Connector, RoomPlacement, stitch_rooms
from cozmoscan.render.plan_renderer import render_property_plan
from cozmoscan.types import CaptureBundle, DamageRegion, RoomModel, Tier

SCHEMA_VERSION = "1.0"
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "capture_output.schema.json"
PROPERTY_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "property_output.schema.json"


@dataclass
class DamagePhotoSpec:
    """One close-up surface photo to run damage detection against, supplied alongside a capture.
    Geometry reconstruction and damage inspection are deliberately independent inputs: sparse
    scan point clouds / wide room-level video frames don't have the resolution or focus damage
    detection needs, so close-up stills of specific surfaces are a separate, optional input."""

    surface_id: str
    path: Path
    pixels_per_meter: float
    wall_index: int  # which room.walls[] entry this surface belongs to, for plan placement


@dataclass
class PipelineConfig:
    stray_scanner: StrayScannerConfig = field(default_factory=StrayScannerConfig)
    video_tier: VideoTierConfig = field(default_factory=VideoTierConfig)
    photo_tier: PhotoTierConfig = field(default_factory=PhotoTierConfig)
    manhattan: ManhattanConfig = field(default_factory=ManhattanConfig)
    damage_detector: DamageDetectorConfig = field(default_factory=DamageDetectorConfig)


def _load_bundle(capture_dir: Path, tier: Tier, room_id: str, cfg: PipelineConfig) -> CaptureBundle:
    if tier == "lidar":
        return load_lidar_capture(capture_dir, room_id, cfg.stray_scanner)
    if tier == "video":
        return load_video_capture(capture_dir, room_id, cfg.video_tier)
    if tier == "photo":
        return load_photo_capture(capture_dir, room_id, cfg.photo_tier)
    raise ValueError(f"Unknown tier {tier!r}")


def _build_room(bundle: CaptureBundle, cfg: PipelineConfig) -> RoomModel:
    if bundle.tier == "photo":
        return photo_room_model(bundle, cfg.photo_tier)
    trajectory_xz = np.array([[p.position[0], p.position[2]] for p in bundle.poses]) if bundle.poses else None
    return fit_room_box(bundle.point_cloud, bundle.tier, bundle.room_id, cfg.manhattan, trajectory_xz=trajectory_xz)


def _detect_damage_regions(
    damage_photos: list[DamagePhotoSpec], cfg: PipelineConfig, surface_tags: dict[str, SurfaceTag] | None
) -> list[tuple[DamageRegion, int]]:
    """Returns (region, wall_index) pairs -- kept paired rather than two parallel lists since a
    single photo can yield zero, one, or several detections, so regions don't line up 1:1 with
    ``damage_photos`` by position."""
    import cv2

    pairs: list[tuple[DamageRegion, int]] = []
    for spec in damage_photos:
        bgr = cv2.imread(str(spec.path))
        if bgr is None:
            raise FileNotFoundError(f"Could not read damage photo {spec.path}")
        for d in detect_damage(bgr, cfg.damage_detector):
            pairs.append((to_damage_region(d, spec.surface_id, spec.pixels_per_meter), spec.wall_index))

    regions = infer_concealed_risks([r for r, _ in pairs], surface_tags)
    return list(zip(regions, [w for _, w in pairs]))


def _damage_region_to_plan_marker(region: DamageRegion, room: RoomModel, wall_index: int) -> dict:
    """Projects a wall-local (along-wall, height) DamageRegion onto the top-down plan as a small
    fixed-size marker at the correct position along the correct wall -- not a literal to-scale
    top-down footprint, since damage lives on a *vertical* surface and a floor plan is a
    horizontal slice (disclosed rendering choice, see docs/10_ui_ux_rendered_plan.md)."""
    wall = room.walls[wall_index]
    u_center = float(np.clip(region.polygon_xy[:, 0].mean(), 0.0, wall.length.value))
    direction = wall.direction()
    normal = np.array([-direction[1], direction[0]])
    local_pt = wall.p1 + direction * u_center + normal * 0.15
    global_pt = room.to_global_xy(local_pt[None, :])[0]
    half = 0.1
    marker = np.array([global_pt + [-half, -half], global_pt + [half, -half], global_pt + [half, half], global_pt + [-half, half]])
    return {"polygon_xy": marker.tolist(), "damage_class": region.damage_class, "area_m2": region.area_m2}


def _validate(result: dict, schema_path: Path = SCHEMA_PATH) -> None:
    import jsonschema

    schema = json.loads(schema_path.read_text())
    jsonschema.validate(result, schema)


def run_single_room(
    capture_dir: Path,
    tier: Tier,
    room_id: str,
    out_dir: Path,
    config: PipelineConfig | None = None,
    damage_photos: list[DamagePhotoSpec] | None = None,
    surface_tags: dict[str, SurfaceTag] | None = None,
) -> dict:
    """The "one command per capture" entry point: raw capture -> dimensioned room plan (JSON +
    PNG), with optional per-surface damage regions/scope if close-up damage photos are supplied."""
    cfg = config or PipelineConfig()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    bundle = _load_bundle(Path(capture_dir), tier, room_id, cfg)
    room = _build_room(bundle, cfg)

    region_wall_pairs = _detect_damage_regions(damage_photos or [], cfg, surface_tags)
    damage_regions = [r for r, _ in region_wall_pairs]
    scope_items = generate_scope(damage_regions)
    plan_markers = [_damage_region_to_plan_marker(r, room, w) for r, w in region_wall_pairs]

    render_path = render_property_plan([room], out_dir / "plan.png", damage_regions=plan_markers, title=f"{room_id} ({tier})")

    result = {
        "schema_version": SCHEMA_VERSION,
        "capture_id": bundle.capture_id,
        "room": room.as_dict(),
        "damage_regions": [r.as_dict() for r in damage_regions],
        "scope_line_items": [s.as_dict() for s in scope_items],
        "render_path": render_path.name,
    }
    _validate(result)
    (out_dir / "result.json").write_text(json.dumps(result, indent=2))
    return result


def run_stitch(
    room_json_paths: list[Path],
    connectors: list[Connector],
    placements: list[RoomPlacement],
    out_dir: Path,
    correct_drift: bool = True,
    anchor_room_id: str | None = None,
) -> dict:
    """Combines N already-scanned rooms (each a run_single_room output) into one stitched
    multi-room property plan. See module docstring for why this is a separate command."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    per_room_results = [json.loads(Path(p).read_text()) for p in room_json_paths]
    rooms = [RoomModel.from_dict(r["room"]) for r in per_room_results]
    stitched = stitch_rooms(rooms, placements, connectors, correct_drift=correct_drift, anchor_room_id=anchor_room_id)

    plan_markers = []
    for room, raw in zip(stitched, per_room_results):
        for region_dict in raw["damage_regions"]:
            region = DamageRegion.from_dict(region_dict)
            wall_index = next((w.index for w in room.walls if w.surface_id == region.surface_id), 0)
            plan_markers.append(_damage_region_to_plan_marker(region, room, wall_index))

    render_path = render_property_plan(stitched, out_dir / "property_plan.png", damage_regions=plan_markers, title="Stitched property")

    result = {
        "schema_version": SCHEMA_VERSION,
        "rooms": [r.as_dict() for r in stitched],
        "damage_regions": [dmg for raw in per_room_results for dmg in raw["damage_regions"]],
        "scope_line_items": [item for raw in per_room_results for item in raw["scope_line_items"]],
        "render_path": render_path.name,
    }
    _validate(result, PROPERTY_SCHEMA_PATH)
    (out_dir / "property_result.json").write_text(json.dumps(result, indent=2))
    return result
