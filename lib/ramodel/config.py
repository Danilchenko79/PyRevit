# -*- coding: utf-8 -*-
"""Rule settings. File: %APPDATA%\\RAModel\\settings.json."""
import os
import io
import json
import copy

# Default values. Dimensions in mm, loads in kN.
DEFAULTS = {
    # --- walls and openings ---
    "min_opening_width_mm": 400,      # narrower opening -> wall is not split
    "min_lintel_height_mm": 150,      # lower beam -> not created
    "min_pier_width_mm": 300,         # narrower pier -> warning
    "narrow_pier_mode": "merge",      # merge: join to the opening (wider lintel) | panel | skip
    "pier_snap_tol_mm": 150,          # alignment of pier edges between storeys
    "parapet_mode": "beam",           # beam: sill wall is part of the beam | load: weight as load | ignore
    "parapet_load_case": "DL1",       # Revit load case for load mode
    "concrete_unit_weight_kn_m3": 25.0,
    "min_slab_opening_mm": 600,       # slab opening with both sides smaller is ignored
    "min_slab_thickness_mm": 100,     # thinner slab (screed, finish) -> not a floor

    # --- snapping to slabs ---
    "slab_axis_mode": "middle",       # middle: slab axis | top: slab top
    "level_snap_tol_mm": 300,         # wall/column near a slab -> onto the slab axis
    "axis_merge_tol_mm": 700,         # slabs with closer elevations -> one plane (by the larger slab)
    "beam_snap_tol_mm": 700,          # slab not farther from the beam (vertically) -> beam into the slab plane
    "slab_edge_snap": True,           # slab edge -> onto wall axis or centre of edge columns
    "slab_edge_snap_tol_mm": 400,     # slab edge -> onto wall/beam axis if closer

    # --- plan alignment ---
    "angle_snap_deg": 0.5,            # walls/beams nearly parallel to the grid -> exactly parallel
    "grid_snap": True,                # wall axes, columns, beams -> onto grid lines
    "grid_snap_tol_mm": 60,
    "wall_stack_tol_mm": 150,         # storey wall axis -> onto the wall axis of the storey below
    "wall_collinear_tol_mm": 200,     # collinear walls with an axis step (different thickness) -> one axis
    "column_stack_tol_mm": 150,       # storey column -> onto the column of the storey below
    "wall_join_tol_mm": 300,          # wall ends -> to axis intersection / column centre
    "beam_end_snap_tol_mm": 400,      # beam ends -> column centre / wall axis

    # --- lintels ---
    "lintel_family": "PEER-Concrete-Beam-Rectangular",   # not in the model -> any suitable one
    "lintel_param_b": "Width",
    "lintel_param_h": "H",

    # --- supports ---
    "create_supports": False,         # False: do not create supports (assign in Robot)
    "wall_support": "fixed",          # fixed | pinned
    "column_support": "fixed",        # fixed | pinned

    # --- checks and auto-fixes ---
    "node_merge_tol_mm": 50,
    "extend_tol_mm": 300,
    "min_member_length_mm": 100,

    # --- export to Robot ---
    "robot_interop_path": "",         # empty = search in Program Files\\Autodesk
    "robot_project_type": "shell",    # shell | frame3d
    "robot_default_concrete": "C30/37",
    "robot_default_steel": "S235",
    "material_map": {},               # {"Concrete B25": "C20/25"}
    "section_map": {},                # {"IPE300": "IPE 300"}
    "self_weight_case": "",           # empty = first permanent load case
    "support_node_step_mm": 500,      # nodal support spacing along a line support
    "arc_segments": 8
}

# Allowed values for switch fields.
CHOICES = {
    "narrow_pier_mode": ["merge", "panel", "skip"],
    "parapet_mode": ["beam", "load", "ignore"],
    "slab_axis_mode": ["middle", "top"],
    "wall_support": ["fixed", "pinned"],
    "column_support": ["fixed", "pinned"],
    "robot_project_type": ["shell", "frame3d"],
}


def _coerce(v, default):
    """Value from the file -> type of the default value ("false" does not become True)."""
    if isinstance(default, bool):
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return bool(v)
        s = u'{}'.format(v).strip().lower()
        # Russian yes/no ('da'/'net') are also accepted in the settings file
        if s in (u'true', u'1', u'yes', u'\u0434\u0430'):
            return True
        if s in (u'false', u'0', u'no', u'\u043d\u0435\u0442', u''):
            return False
        raise ValueError(v)
    if isinstance(default, (int, float)):
        if v is None or isinstance(v, bool):
            raise TypeError(v)
        return float(v)
    if isinstance(default, dict):
        if not isinstance(v, dict):
            raise TypeError(v)
        return v
    if isinstance(default, list):
        if not isinstance(v, list):
            raise TypeError(v)
        return v
    if v is None:
        raise TypeError(v)
    return u'{}'.format(v)


# Values needed by modules without access to cfg (updated in load()).
RUNTIME = {'min_slab_thickness_mm': DEFAULTS['min_slab_thickness_mm']}


def settings_path():
    """Path to the user settings file."""
    base = os.environ.get('APPDATA') or os.path.expanduser('~')
    return os.path.join(base, 'RAModel', 'settings.json')


def load():
    """Settings = defaults + whatever the user specified in the file.

    A read error does not stop the run: key '_error' holds its text.
    """
    cfg = copy.deepcopy(DEFAULTS)
    path = settings_path()
    errors = []
    if os.path.exists(path):
        try:
            with io.open(path, 'r', encoding='utf-8-sig') as f:
                user = json.loads(f.read())
            for k, v in user.items():
                if k not in cfg:
                    errors.append(u'Unknown parameter "{}" - skipped'.format(k))
                    continue
                try:
                    cfg[k] = _coerce(v, DEFAULTS[k])
                except (TypeError, ValueError):
                    errors.append(u'{} = {}: invalid type, using {}'.format(k, v, DEFAULTS[k]))
        except Exception as e:
            errors.append(u'{}: {}'.format(path, e))
    for k, allowed in CHOICES.items():
        if cfg.get(k) not in allowed:
            errors.append(u'Invalid value {} = {}. Allowed: {}'.format(
                k, cfg.get(k), ', '.join(allowed)))
            cfg[k] = DEFAULTS[k]
    if errors:
        cfg['_error'] = u'\n'.join(errors)
    try:
        RUNTIME['min_slab_thickness_mm'] = float(cfg['min_slab_thickness_mm'])
    except (TypeError, ValueError):
        pass
    return cfg


def save(cfg):
    """Write settings (without service keys)."""
    path = settings_path()
    folder = os.path.dirname(path)
    if not os.path.isdir(folder):
        os.makedirs(folder)
    clean = dict((k, v) for k, v in cfg.items() if not k.startswith('_'))
    text = json.dumps(clean, ensure_ascii=False, indent=2, sort_keys=True)
    with io.open(path, 'w', encoding='utf-8') as f:
        f.write(u'' + text)
    return path


def ensure_file():
    """Create the file with defaults if it does not exist yet."""
    path = settings_path()
    if not os.path.exists(path):
        save(copy.deepcopy(DEFAULTS))
    return path


def mm(cfg, key):
    """Setting value in mm -> Revit feet."""
    return float(cfg[key]) / 304.8
