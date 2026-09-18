"""Per-event tunables (spec section 24: events.settings)."""
from __future__ import annotations

from typing import Any

from app.core.exceptions import AppError
from app.models import Event

DEFAULT_SETTINGS: dict[str, Any] = {
    "radar_near_radius_m": 30,
    "freeze_duration_s": 120,  # FREEZE attack
    "jam_duration_s": 90,  # JAM attack: radar blackout
    "ward_duration_s": 300,  # WARD defence: attacks auto-blocked
    "guide_duration_s": 180,  # GUIDE: current target revealed
    "attack_response_window_s": 15,
    "staggered_start_offset_s": 120,
    "geofence_mode": "off",  # off | warn | block
    "starting_power_points": 100,
    "allow_attack_frozen": False,
    "puzzle_cooldown_s": 3,
}

# key -> (type, min, max) for numbers, (bool,) for flags, ("choice", options) for enums
_SPECS: dict[str, tuple] = {
    "radar_near_radius_m": (int, 5, 500),
    "freeze_duration_s": (int, 10, 1800),
    "jam_duration_s": (int, 10, 1800),
    "ward_duration_s": (int, 30, 3600),
    "guide_duration_s": (int, 30, 1800),
    "attack_response_window_s": (int, 5, 120),
    "staggered_start_offset_s": (int, 0, 1800),
    "geofence_mode": ("choice", ("off", "warn", "block")),
    "starting_power_points": (int, 0, 100000),
    "allow_attack_frozen": (bool,),
    "puzzle_cooldown_s": (int, 0, 120),
}


def event_settings(event: Event) -> dict[str, Any]:
    stored = event.settings or {}
    return {key: stored.get(key, default) for key, default in DEFAULT_SETTINGS.items()}


def validate_settings_patch(patch: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in patch.items():
        spec = _SPECS.get(key)
        if spec is None:
            raise AppError(f"Unknown setting '{key}'.")
        if spec[0] == "choice":
            if value not in spec[1]:
                raise AppError(f"{key} must be one of: {', '.join(spec[1])}.")
            clean[key] = value
        elif spec[0] is bool:
            if not isinstance(value, bool):
                raise AppError(f"{key} must be true or false.")
            clean[key] = value
        else:
            try:
                number = int(value)
            except (TypeError, ValueError):
                raise AppError(f"{key} must be a whole number.") from None
            low, high = spec[1], spec[2]
            if not low <= number <= high:
                raise AppError(f"{key} must be between {low} and {high}.")
            clean[key] = number
    return clean
