# -*- coding: utf-8 -*-
"""Create the real sections (one per group) and the reference markers.

Model-side only - opens its own transactions, no UI. Each group yields exactly
one real ViewSection built from the representative's node descriptor; every
other member gets a reference marker pointing back at that same view.

Window section: thin vertical slice (10 mm) at the window's plan position,
cropped between the lower window's head and this window's sill -> only the slab
and the concrete wall between the stacked windows are shown.
Beam section: symmetric transverse cross-section.
"""

from Autodesk.Revit.DB import (
    Transaction, ViewSection, XYZ,
)

from AutoSections.convert import mm, to_ft
from AutoSections import geometry as G

WIN_DEPTH = 10.0         # mm minimal slice depth along the wall
WIN_SIDE_MARGIN = 150.0  # mm margin each side of the wall thickness (across)
WIN_SLAB_WIDEN = 1000.0  # mm extra width toward the slab so the slab shows
BEAM_MARGIN = 500.0      # mm margin around the beam cross-section


def _build_box(desc):
    """Oriented section box from a node descriptor."""
    if desc['kind'] == 'WIN':
        top_z, bottom_z = desc['top_z'], desc['bottom_z']
        o = desc['origin']
        mid = XYZ(o.X, o.Y, (top_z + bottom_z) * 0.5)
        half_band = mm((top_z - bottom_z) * 0.5)
        base = desc['wall_thk'] * 0.5 + WIN_SIDE_MARGIN
        widen = desc.get('widen')
        x_neg = base + (WIN_SLAB_WIDEN if widen == 'neg' else 0.0)
        x_pos = base + (WIN_SLAB_WIDEN if widen == 'pos' else 0.0)
        return G.make_section_box(mid, desc['view_dir'],
                                  x_neg, x_pos, half_band, half_band,
                                  WIN_DEPTH * 0.5)

    x_half = desc['b'] * 0.5 + BEAM_MARGIN
    y_half = desc['h'] * 0.5 + BEAM_MARGIN
    z_half = desc['b'] * 0.5 + BEAM_MARGIN
    return G.make_section_box(desc['origin'], desc['view_dir'],
                              x_half, x_half, y_half, y_half, z_half)


def _section_name(prefix, idx, a, b):
    return '{}_{:02d}_{}x{}'.format(prefix, idx, int(a), int(b))


def _set_unique_name(view, base):
    """Set view.Name, suffixing _1, _2, ... on collision. Returns the name used."""
    name, suffix = base, 1
    while True:
        try:
            view.Name = name
            return name
        except Exception:
            name = '{}_{}'.format(base, suffix)
            suffix += 1
            if suffix > 50:
                return view.Name


def create_real_sections(doc, vft_id, groups):
    """Create one section per group.

    Returns (created, errors) where each created entry is:
        {"view", "members", "rep_id", "count"}.
    """
    created, errors = [], []
    t = Transaction(doc, 'AutoSections - Create unique sections')
    t.Start()
    try:
        idx = 1
        for key, info in groups.items():
            desc = info['desc']
            _kind, rep = info['members'][0]
            try:
                box = _build_box(desc)
                view = ViewSection.CreateSection(doc, vft_id, box)
                _set_unique_name(view, _section_name(
                    desc['prefix'], idx, desc['name_w'], desc['name_h']))
                created.append({'view': view, 'members': info['members'],
                                'rep_id': rep.Id, 'count': len(info['members'])})
                idx += 1
            except Exception as e:
                errors.append('{}: {}'.format(rep.Id, str(e)))
        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise
    return created, errors


def create_reference_sections(doc, parent_view, created):
    """Place a reference marker in `parent_view` for every duplicate member.

    Returns (ref_count, errors). No-op (0, [...]) when parent_view is None.
    """
    if parent_view is None:
        return 0, ['no plan view available to host reference markers']

    z = parent_view.GenLevel.Elevation if parent_view.GenLevel else None

    ref_count, errors = 0, []
    t = Transaction(doc, 'AutoSections - Create reference sections')
    t.Start()
    try:
        for entry in created:
            view = entry['view']
            for kind, elem in entry['members']:
                if elem.Id == entry['rep_id']:
                    continue
                origin, _view_dir, side = G.section_frame(elem, kind)
                if origin is None:
                    continue
                try:
                    zz = z if z is not None else origin.Z
                    head = XYZ(origin.X, origin.Y, zz)
                    # the marker line lies along the cut (the side axis), in plan
                    tail = head + side.Normalize() * to_ft(1000.0)
                    ViewSection.CreateReferenceSection(
                        doc, parent_view.Id, view.Id, head, tail)
                    ref_count += 1
                except Exception as e:
                    errors.append('ref {}: {}'.format(elem.Id, str(e)))
        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise
    return ref_count, errors
