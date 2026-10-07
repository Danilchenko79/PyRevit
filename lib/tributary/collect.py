# -*- coding: utf-8 -*-
"""[Revit] Плиты уровня и опоры под ними -> JSON-совместимый dict в мм. Только чтение.

    data = collect(doc, level, params)            # params — tributary.params.merged(...)
    data = collect(doc, level, params, floor_ids)  # только выбранные плиты

Опора — несущая стена / колонна / балка (из модели и из загруженных связей, в имени которых
есть params['link_mask']), которая по высоте доходит до низа плиты снизу или проходит сквозь.
"""
from Autodesk.Revit.DB import (FilteredElementCollector, BuiltInCategory, BuiltInParameter,
                               ElementLevelFilter, Floor, Wall, WallKind, FamilyInstance,
                               RevitLinkInstance, LocationPoint, Line, Transform,
                               HostObjectUtils, PlanarFace)

from SlabLinks.creation import get_slab_faces_z, loop_to_polygon, polygon_area
from ramodel.physical import core_offset, is_structural_wall, section_dims
from ramodel.util import eid_int
from tributary.geom import split_loops

FT = 304.8


def _mm(v):
    return v * FT


def _xy(p):
    return [round(p.X * FT, 1), round(p.Y * FT, 1)]


def _name(el):
    try:
        sym = getattr(el, 'Symbol', None)
        if sym is not None:
            return u'{} : {}'.format(sym.FamilyName, el.Name)
        return el.Name
    except Exception:
        return u''


def _z_range(el, T):
    bb = el.get_BoundingBox(None)
    if bb is None:
        return None, None
    z = [T.OfPoint(bb.Min).Z, T.OfPoint(bb.Max).Z]
    return min(z) * FT, max(z) * FT


def _param_mm(el, bip, default=None):
    p = el.get_Parameter(bip)
    return p.AsDouble() * FT if (p and p.HasValue) else default


def level_slabs(doc, level, floor_ids=None):
    """Несущие плиты уровня (Floor)."""
    col = (FilteredElementCollector(doc).OfClass(Floor)
           .WherePasses(ElementLevelFilter(level.Id)).ToElements())
    out = []
    allowed = None if floor_ids is None else set(eid_int(i) for i in floor_ids)
    for f in col:
        if allowed is not None and eid_int(f.Id) not in allowed:
            continue
        p = f.get_Parameter(BuiltInParameter.FLOOR_PARAM_IS_STRUCTURAL)
        if not (p and p.AsInteger() == 1):
            continue
        out.append(f)
    return out


def _slab_parts(f):
    """Куски плиты по ВЕРХНИМ горизонтальным граням: контуры грани разбираются по вложенности
    (geom.split_loops). Отдельные куски одной плиты (несколько контуров в эскизе — Revit кладёт их
    в одну грань) и ступенчатый верх идут отдельными кусками, а не «проёмами» самого большого
    контура, как в SlabLinks.get_slab_polygons.
    Именно верх, а не низ: низ плиты подрезают тонкие полы-утеплители («d=2 poliash» вдоль фасада,
    KRM FL04/FL05) — по нижней грани там получался ложный проём, и стена отрезалась от плиты."""
    zb, zt = get_slab_faces_z(f)
    if zb is None:
        return [], u'no horizontal faces'
    h = _param_mm(f, BuiltInParameter.FLOOR_ATTR_THICKNESS_PARAM, 0.0)
    parts = []
    for r in HostObjectUtils.GetTopFaces(f):
        face = f.GetGeometryObjectFromReference(r)
        if not isinstance(face, PlanarFace) or face.FaceNormal.Z < 0.99:
            continue
        loops = []
        for loop in face.GetEdgesAsCurveLoops():
            poly = loop_to_polygon(loop)
            if poly and polygon_area(poly) > 0.0:
                loops.append([(round(x * FT, 1), round(y * FT, 1)) for x, y in poly])
        for outer, holes in split_loops(loops):
            parts.append({'id': eid_int(f.Id), 'name': _name(f), 'h': round(h, 1),
                          'z_bot': round(zb * FT, 1), 'z_top': round(face.Origin.Z * FT, 1),
                          'outer': [list(q) for q in outer],
                          'holes': [[list(q) for q in hl] for hl in holes]})
    if not parts:
        return [], u'no flat top face'
    return parts, None


def _sources(doc, mask):
    """[(doc, Transform, имя связи)] — модель и загруженные связи с mask в имени."""
    out = [(doc, Transform.Identity, u'')]
    for li in FilteredElementCollector(doc).OfClass(RevitLinkInstance).ToElements():
        name = li.Name or u''
        if mask and mask not in name:
            continue
        ld = li.GetLinkDocument()
        if ld is None:
            continue
        out.append((ld, li.GetTotalTransform(), name.split(u' : ')[0]))
    return out


class _Box(object):
    def __init__(self, slabs, margin):
        xs = [q[0] for s in slabs for q in s['outer']]
        ys = [q[1] for s in slabs for q in s['outer']]
        self.x0, self.x1 = min(xs) - margin, max(xs) + margin
        self.y0, self.y1 = min(ys) - margin, max(ys) + margin

    def hits(self, pts):
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return not (max(xs) < self.x0 or min(xs) > self.x1 or max(ys) < self.y0 or min(ys) > self.y1)


def collect(doc, level, p, floor_ids=None):
    data = {'doc_title': doc.Title,
            'level': {'name': level.Name, 'id': eid_int(level.Id), 'elev_mm': round(level.Elevation * FT, 1)},
            'slabs': [], 'walls': [], 'columns': [], 'beams': [], 'skipped': [], 'links': []}
    sk = data['skipped']
    for f in level_slabs(doc, level, floor_ids):
        parts, why = _slab_parts(f)
        if not parts:
            sk.append({'id': eid_int(f.Id), 'what': u'slab', 'reason': why})
        for s in parts:
            if s['h'] > 0:
                data['slabs'].append(s)
    if not data['slabs']:
        return data
    zb_lo = min(s['z_bot'] for s in data['slabs'])
    zt_hi = max(s['z_top'] for s in data['slabs'])
    h_max = max(s['h'] for s in data['slabs'])
    ztol = p['z_tol']
    box = _Box(data['slabs'], 1000.0)

    def supports_slab(z0, z1):
        return z0 is not None and z0 < zb_lo - 100.0 and z1 > zb_lo - ztol

    for sdoc, T, lname in _sources(doc, p.get('link_mask')):
        if lname:
            data['links'].append(lname)
        # стены
        for w in (FilteredElementCollector(sdoc).OfCategory(BuiltInCategory.OST_Walls)
                  .WhereElementIsNotElementType().ToElements()):
            if not isinstance(w, Wall) or not is_structural_wall(w):
                continue
            try:
                if w.WallType.Kind in (WallKind.Stacked, WallKind.Curtain):
                    continue
            except Exception:
                continue
            z0, z1 = _z_range(w, T)
            if not supports_slab(z0, z1):
                continue
            crv = getattr(w.Location, 'Curve', None)
            if not isinstance(crv, Line):
                bb = w.get_BoundingBox(None)
                if bb is not None and box.hits([_xy(T.OfPoint(bb.Min)), _xy(T.OfPoint(bb.Max))]):
                    sk.append({'id': eid_int(w.Id), 'link': lname, 'what': u'wall',
                               'reason': u'curved — ignored'})
                continue
            off, t = core_offset(w)
            shift = w.Orientation.Multiply(off)
            a = _xy(T.OfPoint(crv.GetEndPoint(0).Add(shift)))
            b = _xy(T.OfPoint(crv.GetEndPoint(1).Add(shift)))
            if not box.hits([a, b]):
                continue
            data['walls'].append({'id': eid_int(w.Id), 'link': lname, 'name': _name(w),
                                  'p0': a, 'p1': b, 't': round(t * FT, 1)})
        # колонны
        for c in (FilteredElementCollector(sdoc).OfCategory(BuiltInCategory.OST_StructuralColumns)
                  .WhereElementIsNotElementType().ToElements()):
            if not isinstance(c, FamilyInstance):
                continue
            z0, z1 = _z_range(c, T)
            if not supports_slab(z0, z1):
                continue
            loc = c.Location
            if not isinstance(loc, LocationPoint):
                sk.append({'id': eid_int(c.Id), 'link': lname, 'what': u'column',
                           'reason': u'slanted — ignored'})
                continue
            pt = _xy(T.OfPoint(loc.Point))
            if not box.hits([pt]):
                continue
            kind, b, h = section_dims(c.Symbol)
            hand = T.OfVector(c.HandOrientation)
            if kind is None:
                bb = c.get_BoundingBox(None)
                b = abs(bb.Max.X - bb.Min.X)
                h = abs(bb.Max.Y - bb.Min.Y)
                kind = 'rect'
                hand = T.OfVector(Transform.Identity.BasisX)
                sk.append({'id': eid_int(c.Id), 'link': lname, 'what': u'column',
                           'reason': u'section not recognised — bounding box used'})
            data['columns'].append({'id': eid_int(c.Id), 'link': lname, 'name': _name(c),
                                    'x': pt[0], 'y': pt[1], 'b': round(b * FT, 1),
                                    'h': round(h * FT, 1), 'ux': hand.X, 'uy': hand.Y,
                                    'shape': 'round' if kind == 'round' else 'rect'})
        # балки: пересекают плиту по высоте и выше её толщины (прямые и обратные);
        # скрытые балки в толщине плиты — не опора
        if not p.get('use_beams', 1):
            continue
        for bm in (FilteredElementCollector(sdoc).OfCategory(BuiltInCategory.OST_StructuralFraming)
                   .WhereElementIsNotElementType().ToElements()):
            if not isinstance(bm, FamilyInstance):
                continue
            z0, z1 = _z_range(bm, T)
            if z0 is None or z1 < zb_lo - ztol or z0 > zt_hi + ztol or z1 - z0 < h_max + ztol:
                continue
            crv = getattr(bm.Location, 'Curve', None)
            if not isinstance(crv, Line):
                continue
            a = _xy(T.OfPoint(crv.GetEndPoint(0)))
            b = _xy(T.OfPoint(crv.GetEndPoint(1)))
            if not box.hits([a, b]):
                continue
            kind, bw, _h = section_dims(bm.Symbol)
            data['beams'].append({'id': eid_int(bm.Id), 'link': lname, 'name': _name(bm),
                                  'p0': a, 'p1': b, 'b': round(bw * FT, 1) if bw else 300.0})
    return data


def export_json(doc, level_key, user_params=None, out_dir=None):
    """Для скилла Claude (revit-py): собрать уровень и записать JSON. Возвращает ASCII-строку."""
    import os
    import io
    import json
    from tributary import params as P
    from tributary.report import default_out_dir, safe_name
    lv = find_level(doc, level_key)
    if lv is None:
        return 'ERROR level not found: {}'.format(level_key)
    p = P.merged(user_params)
    data = collect(doc, lv, p)
    out_dir = out_dir or default_out_dir()
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    path = os.path.join(out_dir, u'{}_{}.json'.format(safe_name(doc.Title), safe_name(lv.Name)))
    with io.open(path, 'w', encoding='utf-8') as f:
        f.write(json.dumps(data))           # ensure_ascii=True: файл чистый ASCII
    return ('OK json={} doc={} level={} slabs={} walls={} columns={} beams={} skipped={} links={}'
            .format(path, doc.Title, lv.Name, len(data['slabs']), len(data['walls']),
                    len(data['columns']), len(data['beams']), len(data['skipped']),
                    len(data['links']))).encode('ascii', 'replace').decode('ascii')


def find_level(doc, key):
    """Уровень по id (int/str) или имени."""
    from Autodesk.Revit.DB import Level, ElementId
    try:
        el = doc.GetElement(ElementId(int(key)))
        if isinstance(el, Level):
            return el
    except Exception:
        pass
    for lv in FilteredElementCollector(doc).OfClass(Level).ToElements():
        if lv.Name == key:
            return lv
    return None
