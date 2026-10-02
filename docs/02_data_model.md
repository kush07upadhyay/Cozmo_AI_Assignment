# 02 — Data Model

All types live in [cozmoscan/types.py](../cozmoscan/types.py) unless noted. Every type that
appears in a JSON output has matching `as_dict()` / `from_dict()` methods for round-tripping,
and the exact wire format is the published JSON Schema in [schema/](../schema/) — this doc
describes the in-memory shape; the schema files are the authoritative JSON contract.

## Capture-time types

| Type | Fields | Notes |
|---|---|---|
| `Pose` | `timestamp: float`, `position: np.ndarray(3,)`, `quaternion_xyzw: np.ndarray(4,)` | Camera-to-world rigid transform at one instant. `rotation_matrix()` / `camera_to_world()` helpers. |
| `Intrinsics` | `fx, fy, cx, cy: float`, `width, height: int` | Pinhole camera intrinsics; `scaled_to()` rescales for a different image resolution (depth frames are lower-res than RGB). |
| `WeightedPointCloud` | `points: np.ndarray(N,3)`, `weights: np.ndarray(N,)`, `source_tier: Tier`, `labels: Optional[np.ndarray]` | The unified point representation every tier converges on. Weights in `[0,1]`, higher = more trusted (e.g. ARKit depth confidence). |
| `CaptureBundle` | `capture_id, room_id: str`, `tier: Tier`, `source_dir: Path`, `point_cloud: WeightedPointCloud`, `poses: list[Pose]`, `photo_paths: list[Path]`, `meta: dict` | Everything the reconstruction stage needs for one room, one tier. `meta` carries tier-specific disclosure notes (e.g. video tier's triangulated-point count, frames used). |

## Measurement — confidence intervals on everything

```python
@dataclass
class Measurement:
    value: float
    ci: float      # +/- half-width, same units as value
    method: str    # e.g. "lidar_histogram_peak_k2.8" — traces back to the exact algorithm+config
```

Every physical quantity in the output (wall length, opening width/height, ceiling height, floor
area) is a `Measurement`, never a bare float — this is how "CI on every measurement" (spec
requirement) is enforced structurally rather than by convention. `method` is a short tag
identifying which algorithm and config produced the number, for traceability. See
[03_algorithms.md](03_algorithms.md) for how `ci` is actually computed and calibrated per tier.

## Room geometry types

| Type | Fields | Notes |
|---|---|---|
| `Opening` | `wall_index: int`, `start_m: float`, `width: Measurement`, `height: Measurement`, `kind: str`, `sill_height_m: float` | `kind` is `"door"` (sill <=0.15m) or `"window"`. `start_m` is offset along the wall from its first endpoint. |
| `Wall` | `index: int`, `p1, p2: np.ndarray(2,)`, `length: Measurement`, `openings: list[Opening]`, `surface_id: str` | `p1`/`p2` are room-local 2D coordinates. `surface_id` defaults to `f"wall_{index}"`, auto-assigned in `__post_init__` — this is the handle damage photos attach to. |
| `RoomModel` | `room_id: str`, `tier: Tier`, `walls: list[Wall]`, `floor_polygon: np.ndarray(K,2)`, `ceiling_height: Optional[Measurement]`, `floor_area: Measurement`, `transform_to_global: np.ndarray(3,3)`, `point_count: int`, `notes: list[str]`, `meta: dict` | The core reconstruction output. `ceiling_height` is `None` (with an explanatory note) when no ceiling was observed — never guessed. `transform_to_global` is a real (non-identity) homogeneous 2D transform from the room's own local frame (however `fit_room_box` happened to orient it) into a shared frame; `stitch_rooms()` overwrites this per room when combining a property. |

## Damage types

| Type | Fields | Notes |
|---|---|---|
| `DamageRegion` | `damage_class: str`, `surface_id: str`, `polygon_xy: np.ndarray(K,2)`, `area_m2: float`, `confidence: float`, `extent_m: Optional[float]`, `concealed_risk: Optional[str]`, `concealed_rule: Optional[str]` | `damage_class` is `"moisture_stain"` \| `"structural_crack"` \| `"mold"`. `polygon_xy` is in the **surface's own local (along-surface, height) meters frame** — not room-global, not pixel space — see [10_ui_ux_rendered_plan.md](10_ui_ux_rendered_plan.md) for how this gets placed on the top-down plan. `concealed_risk`/`concealed_rule` are `None` until `infer_concealed_risks()` fires a rule. |
| `SurfaceTag` (in [cozmoscan/damage/rules.py](../cozmoscan/damage/rules.py)) | `surface_id: str`, `has_plumbing, is_exterior_wall, is_below_grade: bool` | Optional building-context metadata supplied by the caller (not vision-derived) that sharpens concealed-risk inference. Defaults are all `False` — the rule engine never assumes context it wasn't given. |
| `ScopeLineItem` | `surface_id, damage_class, description: str`, `quantity: float`, `unit: str`, `rule: str` | One repair line item. `rule` names the deterministic rule version that generated it (auditable, not a black box). |

## Pipeline input types ([cozmoscan/pipeline.py](../cozmoscan/pipeline.py))

| Type | Fields | Notes |
|---|---|---|
| `DamagePhotoSpec` | `surface_id: str`, `path: Path`, `pixels_per_meter: float`, `wall_index: int` | One close-up surface photo supplied alongside a capture for damage detection — independent input from the geometry scan itself. |
| `PipelineConfig` | `stray_scanner, video_tier, photo_tier, manhattan, damage_detector` (each a tier/stage config dataclass) | Bundles every stage's tunables behind one object. |

## Published JSON output schemas

Two schemas, both JSON Schema draft-07, validated via `jsonschema.validate()` before any output
file is written (`cozmoscan/pipeline.py::_validate()`):

- [schema/capture_output.schema.json](../schema/capture_output.schema.json) — `run_single_room()` /
  `cozmoscan scan` output (`result.json`). Top-level required keys: `schema_version, capture_id,
  room, damage_regions, scope_line_items, render_path`.
- [schema/property_output.schema.json](../schema/property_output.schema.json) — `run_stitch()` /
  `cozmoscan stitch` output (`property_result.json`). Same shape but `rooms` (plural array)
  instead of a singular `room`, and no `capture_id` (a property isn't one capture). Deliberately
  self-contained (duplicates the shared `$defs` rather than cross-file `$ref`, to avoid
  cross-file schema resolution complexity for a 2-schema project).

Both schemas are strict (`additionalProperties: false` throughout) — the schema is a real
contract, not a loose sanity check.
