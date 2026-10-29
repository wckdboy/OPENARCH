"""Invalidate dependent review decisions when their geometry changes."""


def invalidate_dependents(old, new):
    envelope_changed = old.footprint != new.footprint or any(
        getattr(old, key).value_mm != getattr(new, key).value_mm
        for key in ['width', 'depth', 'eaves', 'wall_thickness'])
    old_levels = {level.id: level.elevation.value_mm for level in old.levels}
    new_levels = {level.id: level.elevation.value_mm for level in new.levels}
    old_openings = {opening.id: opening.model_dump(exclude={'reviewed', 'confidence'}) for opening in old.openings}
    new_openings = {opening.id: opening.model_dump(exclude={'reviewed', 'confidence'}) for opening in new.openings}
    if envelope_changed:
        for opening in new.openings:
            opening.reviewed = False
    for balcony in new.balconies:
        source_changed = balcony.source_opening and old_openings.get(balcony.source_opening) != new_openings.get(balcony.source_opening)
        if envelope_changed or source_changed or old_levels.get(balcony.level_id) != new_levels.get(balcony.level_id):
            if balcony.status == 'reviewed':
                balcony.status = 'proposed'
    return new
