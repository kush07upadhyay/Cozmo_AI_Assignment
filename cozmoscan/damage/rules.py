"""Concealed-damage rule engine: infers risk of HIDDEN damage (mold behind drywall, structural
movement, etc.) from a visible DamageRegion plus optional surface metadata.

This is deliberately rule-based rather than ML-based: concealed risk is fundamentally not
visible in a photo (that's what "concealed" means) -- it can only be *inferred* from indirect
evidence (area, extent, and known building context like "this wall has plumbing in it"). Every
flag is traceable to a named rule version, so the inference is auditable, not a black box.

Surface metadata (SurfaceTag) is optional and defaults to "unknown" for every field -- when no
metadata is supplied, only the area/length-based fallback rules fire. This is an honest
default: the engine never assumes plumbing/exterior/below-grade context it wasn't told.
"""
from __future__ import annotations

from dataclasses import dataclass

from cozmoscan.types import DamageRegion


@dataclass
class SurfaceTag:
    """Building-context metadata for one surface, supplied by the caller (e.g. from a floor
    plan or inspector notes) -- not something vision alone can determine."""

    surface_id: str
    has_plumbing: bool = False
    is_exterior_wall: bool = False
    is_below_grade: bool = False


LARGE_STAIN_AREA_M2 = 0.3
LONG_CRACK_EXTENT_M = 1.5


def infer_concealed_risk(region: DamageRegion, tags: dict[str, SurfaceTag] | None = None) -> DamageRegion:
    """Mutates and returns `region` with `concealed_risk`/`concealed_rule` set if a rule fires.
    Rules are checked in order of specificity (metadata-backed rules before fallback
    area/length-only heuristics) and the first match wins."""
    tags = tags or {}
    tag = tags.get(region.surface_id)

    if region.damage_class == "moisture_stain":
        if tag and tag.has_plumbing:
            region.concealed_risk = "mold_or_rot_behind_wall"
            region.concealed_rule = "moisture_stain_on_plumbing_wall_v1"
        elif tag and tag.is_exterior_wall:
            region.concealed_risk = "insulation_moisture_intrusion"
            region.concealed_rule = "moisture_stain_on_exterior_wall_v1"
        elif region.area_m2 >= LARGE_STAIN_AREA_M2:
            region.concealed_risk = "possible_mold_growth"
            region.concealed_rule = "large_moisture_stain_area_v1"

    elif region.damage_class == "structural_crack":
        if tag and tag.is_below_grade:
            region.concealed_risk = "foundation_settlement"
            region.concealed_rule = "crack_below_grade_v1"
        elif region.extent_m is not None and region.extent_m >= LONG_CRACK_EXTENT_M:
            region.concealed_risk = "structural_movement"
            region.concealed_rule = "long_structural_crack_v1"

    return region


def infer_concealed_risks(regions: list[DamageRegion], tags: dict[str, SurfaceTag] | None = None) -> list[DamageRegion]:
    return [infer_concealed_risk(r, tags) for r in regions]
