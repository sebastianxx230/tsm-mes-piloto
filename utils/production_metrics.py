"""Configuracion unica de procesos y calculos de avance del MES."""

from __future__ import annotations

from collections.abc import Mapping


PROCESS_DEFINITIONS = (
    ('hab', 'Habilitado', 'hab_real', 12.0, 'tracking-stage-blue'),
    ('arm', 'Armado', 'arm_real', 24.0, 'tracking-stage-orange'),
    ('sol', 'Soldado', 'sol_real', 28.0, 'tracking-stage-sky'),
    ('lim', 'Limpieza', 'lim_real', 12.0, 'tracking-stage-red'),
    ('lib', 'Liberacion', 'lib_real', 6.0, 'tracking-stage-green'),
    ('gal', 'Galvanizado', 'gal_real', 6.0, 'tracking-stage-teal'),
    ('are', 'Arenado', 'are_real', 6.0, 'tracking-stage-violet'),
    ('pin', 'Pintado', 'pin_real', 6.0, 'tracking-stage-rose'),
    ('des', 'Despacho', 'des_real', 0.0, 'tracking-stage-slate'),
)

DEFAULT_PROCESS_WEIGHTS = {
    key: weight for key, _, _, weight, _ in PROCESS_DEFINITIONS
}
DEFAULT_ACTIVE_PROCESSES = {
    key: key not in {'are', 'pin'} for key, _, _, _, _ in PROCESS_DEFINITIONS
}
PROCESS_KEYS = frozenset(DEFAULT_PROCESS_WEIGHTS)


def normalize_process_weights(raw: Mapping | None) -> dict[str, float]:
    values = dict(DEFAULT_PROCESS_WEIGHTS)
    if isinstance(raw, Mapping):
        for key in PROCESS_KEYS:
            if key not in raw:
                continue
            try:
                value = float(raw[key])
            except (TypeError, ValueError):
                continue
            values[key] = round(max(0.0, min(value, 100.0)), 2)
    values['des'] = 0.0
    return values


def normalize_active_processes(raw: Mapping | None) -> dict[str, bool]:
    values = dict(DEFAULT_ACTIVE_PROCESSES)
    if isinstance(raw, Mapping):
        for key in PROCESS_KEYS:
            if key in raw:
                values[key] = bool(raw[key])
    values['des'] = True
    return values


def process_settings(work_order) -> tuple[dict[str, float], dict[str, bool]]:
    return (
        normalize_process_weights(getattr(work_order, 'process_weights', None)),
        normalize_active_processes(getattr(work_order, 'active_processes', None)),
    )


def clamped_ratio(value, quantity):
    if value is None or value == -1 or not quantity:
        return None
    return max(0.0, min(float(value) / float(quantity), 1.0))


def component_progress(component, weights, active_processes):
    weighted_progress = 0.0
    available_weight = 0.0
    for key, _, field, _, _ in PROCESS_DEFINITIONS:
        if key == 'des' or not active_processes.get(key, False):
            continue
        weight = max(float(weights.get(key, 0.0)), 0.0)
        if weight <= 0:
            continue
        ratio = clamped_ratio(getattr(component, field), component.cantidad)
        if ratio is None:
            continue
        weighted_progress += ratio * weight
        available_weight += weight
    return (weighted_progress / available_weight * 100.0) if available_weight else 0.0


def quantity_weighted_average(progress_quantity_pairs):
    total_units = 0
    weighted_sum = 0.0
    for progress, quantity in progress_quantity_pairs:
        units = max(int(quantity or 0), 0)
        if units <= 0:
            continue
        weighted_sum += float(progress) * units
        total_units += units
    return weighted_sum / total_units if total_units else 0.0
