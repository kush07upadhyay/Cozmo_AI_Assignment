"""Deterministic repair-scope line-item engine: (damage_class, measured extent) -> quantified
repair line items. Pure lookup + arithmetic, no ML -- every quantity traces back to a measured
area/length plus a disclosed waste factor, never a guessed number.
"""
from __future__ import annotations

from cozmoscan.types import DamageRegion, ScopeLineItem

# Material overage for cut waste/fitting -- standard restoration-estimating practice, not a
# measured value (disclosed assumption).
WASTE_FACTOR = 1.15
# Repaint typically extends past the damaged area itself to blend/feather the edge.
REPAINT_FEATHER_FACTOR = 1.3


def generate_line_items(region: DamageRegion) -> list[ScopeLineItem]:
    items: list[ScopeLineItem] = []

    if region.damage_class == "moisture_stain":
        items.append(
            ScopeLineItem(
                surface_id=region.surface_id,
                damage_class=region.damage_class,
                description="Remove and dispose of damaged drywall section",
                quantity=region.area_m2 * WASTE_FACTOR,
                unit="m2",
                rule="moisture_stain_drywall_removal_v1",
            )
        )
        items.append(
            ScopeLineItem(
                surface_id=region.surface_id,
                damage_class=region.damage_class,
                description="Install and finish replacement drywall",
                quantity=region.area_m2 * WASTE_FACTOR,
                unit="m2",
                rule="moisture_stain_drywall_install_v1",
            )
        )
        items.append(
            ScopeLineItem(
                surface_id=region.surface_id,
                damage_class=region.damage_class,
                description="Prime (stain-blocking) and repaint affected area",
                quantity=region.area_m2 * REPAINT_FEATHER_FACTOR,
                unit="m2",
                rule="moisture_stain_repaint_v1",
            )
        )
        if region.concealed_risk:
            items.append(
                ScopeLineItem(
                    surface_id=region.surface_id,
                    damage_class=region.damage_class,
                    description=f"Professional moisture/mold assessment recommended ({region.concealed_risk})",
                    quantity=1,
                    unit="ea",
                    rule="concealed_risk_assessment_v1",
                )
            )

    elif region.damage_class == "structural_crack":
        length_m = region.extent_m or 0.0
        items.append(
            ScopeLineItem(
                surface_id=region.surface_id,
                damage_class=region.damage_class,
                description="Structural engineer inspection",
                quantity=1,
                unit="ea",
                rule="crack_engineer_inspection_v1",
            )
        )
        items.append(
            ScopeLineItem(
                surface_id=region.surface_id,
                damage_class=region.damage_class,
                description="Epoxy/polyurethane crack injection repair",
                quantity=length_m * WASTE_FACTOR,
                unit="linear_m",
                rule="crack_injection_repair_v1",
            )
        )
        items.append(
            ScopeLineItem(
                surface_id=region.surface_id,
                damage_class=region.damage_class,
                description="Patch, texture-match, and repaint affected area",
                quantity=max(length_m * 0.3, 0.5),
                unit="m2",
                rule="crack_cosmetic_repair_v1",
            )
        )
        if region.concealed_risk:
            items.append(
                ScopeLineItem(
                    surface_id=region.surface_id,
                    damage_class=region.damage_class,
                    description=f"Structural assessment recommended ({region.concealed_risk})",
                    quantity=1,
                    unit="ea",
                    rule="concealed_risk_assessment_v1",
                )
            )

    return items


def generate_scope(regions: list[DamageRegion]) -> list[ScopeLineItem]:
    out: list[ScopeLineItem] = []
    for region in regions:
        out.extend(generate_line_items(region))
    return out
