# -*- coding: utf-8 -*-
"""run(data, user_params) — грузовые площади и типы опор одного уровня. Чистый Python, мм."""
import time

from tributary import params as P
from tributary import supports, trib, classify, punching, vector


def run(data, user_params=None, with_regions=True):
    t0 = time.time()
    p = P.merged(user_params)
    slabs = data['slabs']
    grid = trib.Grid(slabs, p['grid_mm'])

    def dm_at(x, y):
        return P.d_m(grid.h_near(x, y), p)

    def slab_at(x, y):
        return grid.kind_at(x, y) == trib.SLAB

    topo = supports.build(data.get('walls', []), data.get('columns', []), data.get('beams', []),
                          p, dm_at, slab_at)
    points, others = topo['points'], topo['others']

    sources, owner = [], []          # owner: ('p', i) | ('o', i)
    for i, pt in enumerate(points):
        for s in pt['src']:
            sources.append(s)
            owner.append(('p', i))
    for i, ot in enumerate(others):
        for s in ot['src']:
            sources.append(s)
            owner.append(('o', i))
    label, _dist = trib.assign(grid, sources)
    by_slab, none_by_slab = trib.areas_by_slab(grid, label, len(sources))
    none_area = sum(none_by_slab.values())

    def floor_of(k):
        return slabs[k].get('id', k)

    for obj in points + others:
        obj['area'] = 0.0
        obj['area_by_floor'] = {}
    for si, d in enumerate(by_slab):
        kind, i = owner[si]
        obj = (points if kind == 'p' else others)[i]
        for k, a in d.items():
            obj['area'] += a
            f = floor_of(k)
            obj['area_by_floor'][f] = obj['area_by_floor'].get(f, 0.0) + a

    none_by_floor = {}
    for k, a in none_by_slab.items():
        none_by_floor[floor_of(k)] = none_by_floor.get(floor_of(k), 0.0) + a

    notes = list(topo['notes'])
    kept, dropped = [], []
    for pt in points:
        if pt['area'] <= 0.0:
            dropped.append(pt)
            continue
        h = grid.h_near(pt['x'], pt['y'])
        pt['h'] = h
        pt['dm'] = P.d_m(h, p)
        if pt['kind'] in ('column', 'pylon'):
            cls, flags, edist, eax = classify.column(grid, pt, pt['dm'], p)
            pt['cls'] = cls
            pt['edge_axis'] = eax
            pt['edge_dist'] = edist
            pt['flags'] = list(pt['flags']) + flags
        else:
            pt['cls'] = None
            extra = max(g['t'] for g in pt['dims']['legs']) / 2.0 if pt['dims'].get('legs') else 0.0
            pt['flags'] = list(pt['flags']) + classify.node_near_edge(
                grid, (pt['x'], pt['y']), pt['dm'], p, extra)
        kept.append(pt)

    kept.sort(key=lambda q: (-round(q['y'] / 500.0), q['x']))
    for n, pt in enumerate(kept):
        pt['n'] = n + 1
    rows = [punching.row(pt, p) for pt in kept]

    # --- векторные зоны: владелец = индекс в points, затем others, затем «без опоры»
    reg = None
    if with_regions:
        own_of_src = [i if kind == 'p' else len(points) + i for kind, i in owner]
        none_owner = len(points) + len(others)
        O = vector.owner_grid(grid, label, own_of_src, none_owner)
        rings = vector.regions(grid, O)
        reg = []
        for o, rr in rings.items():
            if o < len(points):
                pt = points[o]
                if not pt.get('n'):
                    continue
                ref = {'type': 'point', 'n': pt['n']}
            elif o < none_owner:
                ref = {'type': others[o - len(points)]['kind'], 'i': o - len(points)}
            else:
                ref = {'type': 'none'}
            ref['rings'] = rr
            reg.append(ref)

    area_raster = grid.slab_area()
    area_closed = grid.closed_cells * grid.s * grid.s
    area_points = sum(pt['area'] for pt in kept)
    area_others = sum(ot['area'] for ot in others)
    check = {
        'area_poly_m2': round(grid.area_poly / 1e6, 2),
        'area_raster_m2': round(area_raster / 1e6, 2),
        'area_joints_m2': round(area_closed / 1e6, 2),
        'area_points_m2': round(area_points / 1e6, 2),
        'area_walls_beams_m2': round(area_others / 1e6, 2),
        'area_none_m2': round(none_area / 1e6, 2),
    }
    if grid.area_poly > 0 and abs(area_raster - area_closed - grid.area_poly) > 0.01 * grid.area_poly:
        notes.append(u'raster area differs from the slab area by more than 1 % — '
                     u'check for overlapping slabs or reduce the grid step')
    if grid.overlaps:
        notes.append(u'slabs overlap in plan (no area correction): {}'.format(
            u', '.join(u'{}'.format(i) for i in sorted(set(grid.overlaps)))))
    if none_area > 0:
        notes.append(u'{:.2f} m² of slab without support (cantilever, or no supports under part of the slab)'
                     .format(none_area / 1e6))
    if dropped:
        notes.append(u'{} supports outside the slab — skipped'.format(len(dropped)))
    nodes = topo['stats']['nodes']
    skipped_nodes = nodes.get('wall_L_in', 0) + nodes.get('wall_T', 0) + nodes.get('wall_X', 0)
    if skipped_nodes:
        notes.append(u'concave corners are not checked: inner L — {}, T — {}, X — {} '
                     u'(their area goes to the walls)'.format(nodes.get('wall_L_in', 0),
                                                        nodes.get('wall_T', 0), nodes.get('wall_X', 0)))

    counts = {}
    for r in rows:
        counts[r['kind']] = counts.get(r['kind'], 0) + 1
    return {
        'meta': {'doc_title': data.get('doc_title'), 'level': data.get('level'),
                 'seconds': round(time.time() - t0, 1)},
        'params': p, 'rows': rows, 'points': kept, 'others': others,
        'dropped': dropped, 'check': check, 'notes': notes, 'counts': counts,
        'stats': topo['stats'], 'grid': grid, 'labels': label, 'regions': reg,
        'none_by_floor': none_by_floor,
        'data': data,
    }
