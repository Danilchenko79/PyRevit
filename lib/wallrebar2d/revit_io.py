# -*- coding: utf-8 -*-
"""Чтение стен из активного вида и расстановка 2D-семейств армирования.

Только IronPython внутри Revit. Вся геометрия/подбор — в core.py.
Координаты core — мм в плане; здесь переводим в футы.
"""
import math
import os
import json
import codecs
import clr
from Autodesk.Revit.DB import (IFamilyLoadOptions, FamilySource)
from Autodesk.Revit.DB import (FilteredElementCollector, Wall, Line, LocationCurve,
                               BuiltInParameter, BuiltInCategory, Family, FamilyInstance,
                               XYZ, ElementTransformUtils, ElementId, Element, StorageType,
                               Level, PlanViewRange, PlanViewPlane, IndependentTag,
                               Reference, TagMode, TagOrientation, FamilySymbol,
                               Options, GeometryInstance, Curve, CurveElement,
                               GraphicsStyleType, LeaderEndCondition, Transaction,
                               Solid, ViewDetailLevel, CurveLoop, GeometryCreationUtilities,
                               BooleanOperationsUtils, BooleanOperationsType, SolidUtils)
from System.Collections.Generic import List

# Группа параметров: в Revit 2024 BuiltInParameterGroup убран, остался GroupTypeId (ForgeTypeId)
try:
    from Autodesk.Revit.DB import GroupTypeId
except ImportError:
    GroupTypeId = None
try:
    from Autodesk.Revit.DB import BuiltInParameterGroup
except ImportError:
    BuiltInParameterGroup = None
try:
    from Autodesk.Revit.DB import ExternalDefinitionCreationOptions, SpecTypeId
except ImportError:
    ExternalDefinitionCreationOptions = None
    SpecTypeId = None

from wallrebar2d import core

MM = 304.8
FAILED_PARAMS = {}   # семейство -> параметры, которые не удалось записать (read-only / нет)


def _name(el):
    try:
        return Element.Name.__get__(el)
    except Exception:
        return getattr(el, 'Name', u'?')


# ----------------------------------------------------------------------
# разбор вида: уровни и View Range
# ----------------------------------------------------------------------
PLANE_NAMES = ('TopClipPlane', 'CutPlane', 'BottomClipPlane', 'ViewDepthPlane', 'UnderlayBottom')


def _levels_sorted(doc):
    return sorted(FilteredElementCollector(doc).OfClass(Level), key=lambda l: l.Elevation)


def _resolve_range_level(doc, view, lid, levels):
    """Уровень из PlanViewRange; понимает служебные Level Above / Level Below."""
    base = view.GenLevel
    if lid is None:
        return base
    v = lid.IntegerValue
    if v > 0:
        el = doc.GetElement(lid)
        return el if isinstance(el, Level) else base
    if base is None:
        return None
    try:
        idx = [l.Id.IntegerValue for l in levels].index(base.Id.IntegerValue)
    except ValueError:
        return base
    try:
        if v == PlanViewRange.LevelAbove.IntegerValue:
            return levels[idx + 1] if idx + 1 < len(levels) else base
        if v == PlanViewRange.LevelBelow.IntegerValue:
            return levels[idx - 1] if idx - 1 >= 0 else base
    except Exception:
        pass
    return base


def view_info(doc, view):
    """Всё, что нужно знать о виде для отбора стен. Отметки в мм."""
    levels = _levels_sorted(doc)
    base = view.GenLevel
    above = below = None
    if base is not None:
        for l in levels:
            if l.Elevation > base.Elevation + 1e-6:
                above = l
                break
        for l in reversed(levels):
            if l.Elevation < base.Elevation - 1e-6:
                below = l
                break
    info = {
        'view': _name(view),
        'view_type': str(view.ViewType),
        'level': _name(base) if base is not None else None,
        'level_z': round(base.Elevation * MM) if base is not None else None,
        'level_above': _name(above) if above is not None else None,
        'level_above_z': round(above.Elevation * MM) if above is not None else None,
        'level_below': _name(below) if below is not None else None,
        'level_below_z': round(below.Elevation * MM) if below is not None else None,
        'range': [],
        'cut_z': None,
    }
    try:
        vr = view.GetViewRange()
    except Exception as ex:
        info['range_error'] = unicode(ex)
        return info
    for pname in PLANE_NAMES:
        pv = getattr(PlanViewPlane, pname, None)
        if pv is None:
            continue
        try:
            lid = vr.GetLevelId(pv)
            off = vr.GetOffset(pv)
        except Exception:
            continue
        lvl = _resolve_range_level(doc, view, lid, levels)
        abs_z = round((lvl.Elevation + off) * MM) if lvl is not None else None
        info['range'].append({'plane': pname, 'level_id': lid.IntegerValue,
                              'level': _name(lvl) if lvl is not None else None,
                              'offset_mm': round(off * MM), 'abs_mm': abs_z})
        if pname == 'CutPlane':
            info['cut_z'] = abs_z
    return info


def _wall_z_mm(w):
    bb = w.get_BoundingBox(None)
    if bb is None:
        return None, None
    return round(bb.Min.Z * MM), round(bb.Max.Z * MM)


# ----------------------------------------------------------------------
# правила отбора по высоте
# ----------------------------------------------------------------------
RULE_TITLES = {
    'cut_by_view': u'cut by the view cut plane',
    'top_at_level_above': u'wall top at the level above',
    'top_at_view_level': u'wall top at the view level',
    'all_visible': u'every wall visible on the view',
}


def vertical_ok(z0, z1, rule, info, S):
    """(взять, причина). Отметки в мм."""
    cut_tol = S.get('cut_tolerance_cm', 5) * 10
    reach_tol = S.get('reach_tolerance_cm', 20) * 10
    if rule == 'all_visible':
        return True, u'visible on the view'
    if z0 is None or z1 is None:
        return False, u'wall has no bounding box'
    if rule == 'cut_by_view':
        cz = info.get('cut_z')
        if cz is None:
            return False, u'view cut plane cannot be read'
        if z0 + cut_tol < cz < z1 - cut_tol:
            return True, u'cut plane %d inside %d..%d' % (cz, z0, z1)
        return False, u'cut plane %d outside %d..%d' % (cz, z0, z1)
    if rule == 'top_at_level_above':
        az = info.get('level_above_z')
        if az is None:
            return False, u'no level above'
        if abs(z1 - az) <= reach_tol and z0 < az - reach_tol:
            return True, u'top %d at level %s' % (z1, info.get('level_above'))
        return False, u'top %d not at the level above (%d)' % (z1, az)
    if rule == 'top_at_view_level':
        lz = info.get('level_z')
        if lz is None:
            return False, u'view has no level'
        if abs(z1 - lz) <= reach_tol and z0 < lz - reach_tol:
            return True, u'top %d at the view level %s' % (z1, info.get('level'))
        return False, u'top %d not at the view level (%d)' % (z1, lz)
    return True, u''


# ----------------------------------------------------------------------
# чтение
# ----------------------------------------------------------------------
def _cut_parts(wall, cut_ft, p0, u):
    """Куски стены в разрезе горизонтальной плоскостью на отметке cut_ft (футы):
    [(s0, s1)] в мм вдоль оси стены от p0 (мм), u — единичный вектор оси. Тела строятся
    в памяти, транзакция не нужна. None — если геометрию взять не удалось."""
    opt = Options()
    opt.DetailLevel = ViewDetailLevel.Fine
    bb = wall.get_BoundingBox(None)
    if bb is None:
        return None
    z = cut_ft - 0.5 / MM
    x0, y0, x1, y1 = bb.Min.X - 1.0, bb.Min.Y - 1.0, bb.Max.X + 1.0, bb.Max.Y + 1.0
    pts = [XYZ(x0, y0, z), XYZ(x1, y0, z), XYZ(x1, y1, z), XYZ(x0, y1, z)]
    loop = CurveLoop()
    for i in range(4):
        loop.Append(Line.CreateBound(pts[i], pts[(i + 1) % 4]))
    loops = List[CurveLoop]()
    loops.Add(loop)
    box = GeometryCreationUtilities.CreateExtrusionGeometry(loops, XYZ.BasisZ, 1.0 / MM)
    parts = []
    for g in wall.get_Geometry(opt):
        if not isinstance(g, Solid) or g.Volume < 1e-6:
            continue
        inter = BooleanOperationsUtils.ExecuteBooleanOperation(g, box, BooleanOperationsType.Intersect)
        if inter is None or inter.Volume < 1e-9:
            continue
        for part in SolidUtils.SplitVolumes(inter):
            ss = []
            for e in part.Edges:
                cv = e.AsCurve()
                for q in (cv.GetEndPoint(0), cv.GetEndPoint(1)):
                    ss.append((q.X * MM - p0[0]) * u[0] + (q.Y * MM - p0[1]) * u[1])
            if ss:
                parts.append((min(ss), max(ss)))
    parts.sort()
    merged = []
    for a, b in parts:
        if merged and a <= merged[-1][1] + 1.0:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def _in_other_wall(pt, wd, others):
    """Точка (мм) лежит в сечении другой взятой стены — значит, пустота в этой стене — это
    стык (угол / Т / крест), а не проём."""
    for o in others:
        if o is wd or not o.get('cut_parts'):
            continue
        dx, dy = o['p1'][0] - o['p0'][0], o['p1'][1] - o['p0'][1]
        L = (dx * dx + dy * dy) ** 0.5
        if L < 1.0:
            continue
        ux, uy = dx / L, dy / L
        vx, vy = pt[0] - o['p0'][0], pt[1] - o['p0'][1]
        if abs(-uy * vx + ux * vy) > o['t'] / 2.0 + 5.0:
            continue
        s = ux * vx + uy * vy
        if any(a - 5.0 <= s <= b + 5.0 for a, b in o['cut_parts']):
            return True
    return False


def read_view(doc, view, S, log=None, only_ids=None):
    """(walls, openings, columns, verdicts, info).

    verdicts — решение по каждой стене вида с причиной.
    info['rule_used'] — какое правило отбора в итоге сработало.
    only_ids — работать только по заранее выделенным стенам (высота проверяется так же).
    """
    info = view_info(doc, view)
    wf = S['wall_filter']
    verdicts = []
    cands = []          # [(wall, verdict_dict)]

    for w in FilteredElementCollector(doc, view.Id).OfClass(Wall):
        wid = w.Id.IntegerValue
        z0, z1 = _wall_z_mm(w)
        v = {'id': wid, 'type': _name(w.WallType), 't_cm': round(w.Width * MM / 10.0, 1),
             'z_mm': [z0, z1], 'taken': False, 'reason': u''}
        reason = None
        if only_ids is not None and wid not in only_ids:
            reason = u'not in the selection'
        elif not isinstance(w.Location, LocationCurve) or not isinstance(w.Location.Curve, Line):
            reason = u'not a straight wall'
        else:
            sp = w.get_Parameter(BuiltInParameter.WALL_STRUCTURAL_SIGNIFICANT)
            tn = wf.get('type_name_contains')
            if wf.get('structural_only') and sp and sp.AsInteger() == 0:
                reason = u'not structural'
            elif tn and tn not in _name(w.WallType):
                reason = u'type name without "%s"' % tn
            elif w.Width * MM < wf.get('min_thickness_cm', 0) * 10:
                reason = u'thinner than %s cm' % wf.get('min_thickness_cm')
        if reason is not None:
            v['reason'] = reason
            verdicts.append(v)
            if log:
                log.skipped(u'Wall %d' % wid, reason)
            continue
        cands.append((w, v))

    # --- правило по высоте: пробуем цепочку, пока хоть что-то не пройдёт ---
    if only_ids is not None:
        # Выделенные вручную стены тоже проверяем по высоте (22.09): мышкой на ричинг-плане
        # цепляется стена ЭТАЖА НИЖЕ, она видна как подложка, и раньше её армировало молча.
        rule = (S.get('level_rule_chain') or ['cut_by_view'])[0]
        rule_used = 'preselected+' + rule
        for w, v in cands:
            ok, why = vertical_ok(v['z_mm'][0], v['z_mm'][1], rule, info, S)
            v['taken'] = ok
            v['reason'] = (u'selected by hand, ' + why) if ok else (u'selected, but ' + why)
            if not ok and log:
                log.skipped(u'Wall %d' % v['id'], v['reason'])
    else:
        chain = S.get('level_rule_chain',
                      ['cut_by_view', 'top_at_level_above', 'top_at_view_level', 'all_visible'])
        rule_used = None
        for rule in chain:
            hits = []
            for w, v in cands:
                ok, why = vertical_ok(v['z_mm'][0], v['z_mm'][1], rule, info, S)
                hits.append((ok, why))
            if any(ok for ok, _ in hits):
                rule_used = rule
                for (w, v), (ok, why) in zip(cands, hits):
                    v['taken'] = bool(ok)
                    v['reason'] = why
                break
        if rule_used is None:
            rule_used = chain[0] if chain else 'all_visible'
            for w, v in cands:
                ok, why = vertical_ok(v['z_mm'][0], v['z_mm'][1], rule_used, info, S)
                v['taken'] = False
                v['reason'] = why
    info['rule_used'] = rule_used
    info['rule_title'] = RULE_TITLES.get(rule_used, rule_used)

    walls, openings = [], []
    for w, v in cands:
        verdicts.append(v)
        if not v['taken']:
            if log:
                log.skipped(u'Wall %d' % v['id'], v['reason'])
            continue
        c = w.Location.Curve
        a, b = c.GetEndPoint(0), c.GetEndPoint(1)
        wd = dict(id=v['id'], p0=(a.X * MM, a.Y * MM), p1=(b.X * MM, b.Y * MM),
                  t=w.Width * MM, name=v['type'])
        walls.append(wd)
        ax = core.Axis(wd['p0'], wd['p1'], wd['t'])
        wd['cut_parts'] = None
        if S.get('openings_from_section', True) and info.get('cut_z') is not None:
            try:
                wd['cut_parts'] = _cut_parts(w, info['cut_z'] / MM, wd['p0'], ax.u)
            except Exception as ex_:
                if log:
                    log.error(u'Wall %d section' % v['id'], unicode(ex_))
        wd['_inserts'] = []
        for iid in w.FindInserts(True, False, True, True):
            e = doc.GetElement(iid)
            bb = e.get_BoundingBox(None)
            if bb is None:
                continue
            pts = [(bb.Min.X * MM, bb.Min.Y * MM), (bb.Max.X * MM, bb.Min.Y * MM),
                   (bb.Max.X * MM, bb.Max.Y * MM), (bb.Min.X * MM, bb.Max.Y * MM)]
            ss = [ax.s_of(q) for q in pts]
            # FindInserts отдаёт и окно СОСЕДНЕЙ стены (общая вставка) — ядро такие отбрасывает
            host = getattr(e, 'Host', None)
            wd['_inserts'].append(dict(id=iid.IntegerValue, wall_id=wd['id'], s0=min(ss), s1=max(ss),
                                       host_id=host.Id.IntegerValue if host is not None else None,
                                       h=(bb.Max.Z - bb.Min.Z) * MM,
                                       z0=bb.Min.Z * MM, z1=bb.Max.Z * MM,
                                       name=_name(e)))

    # --- проёмы: по реальному сечению стены (07.10.2026), иначе по габаритам вставок ---
    info['cut_gaps'] = []
    for wd in walls:
        ins = wd.pop('_inserts', [])
        parts = wd.get('cut_parts')
        if parts is None:
            openings.extend(ins)
            continue
        dx, dy = wd['p1'][0] - wd['p0'][0], wd['p1'][1] - wd['p0'][1]
        L = (dx * dx + dy * dy) ** 0.5
        u = (dx / L, dy / L) if L else (1.0, 0.0)
        gaps, pos = [], 0.0
        for a, b in parts:
            if a > pos + 5.0:
                gaps.append((pos, min(a, L)))
            pos = max(pos, b)
            if pos >= L:
                break
        if pos < L - 5.0:
            gaps.append((pos, L))
        k = 0
        for g0, g1 in gaps:
            if g1 - g0 <= 5.0:
                continue
            mid = ((g0 + g1) / 2.0)
            pt = (wd['p0'][0] + u[0] * mid, wd['p0'][1] + u[1] * mid)
            if _in_other_wall(pt, wd, walls):
                continue                          # стык с другой стеной, не проём
            own = [o for o in ins if (o.get('host_id') in (None, wd['id']))
                   and o['s0'] < g1 - 5.0 and o['s1'] > g0 + 5.0]
            k += 1
            openings.append(dict(id=u'cut:%d:%d' % (wd['id'], k), wall_id=wd['id'], s0=g0, s1=g1,
                                 host_id=wd['id'], h=max([o['h'] for o in own]) if own else None,
                                 z0=min([o['z0'] for o in own]) if own else None,
                                 z1=max([o['z1'] for o in own]) if own else None,
                                 name=own[0]['name'] if own else u'no wall at the cut plane'))
            if not own:
                info['cut_gaps'].append((wd['id'], int(round(g0)), int(round(g1))))

    columns = []
    cols = FilteredElementCollector(doc, view.Id).OfCategory(
        BuiltInCategory.OST_StructuralColumns).WhereElementIsNotElementType()
    for cl in cols:
        bb = cl.get_BoundingBox(None)
        if bb:
            columns.append(dict(id=cl.Id.IntegerValue, xmin=bb.Min.X * MM, xmax=bb.Max.X * MM,
                                ymin=bb.Min.Y * MM, ymax=bb.Max.Y * MM))
    return walls, openings, columns, verdicts, info


# ----------------------------------------------------------------------
# семейства
# ----------------------------------------------------------------------
class _KeepExisting(IFamilyLoadOptions):
    """Уже загруженное семейство не трогаем (правки в проекте важнее файла).
    IronPython: out-параметры возвращаются кортежем после результата."""

    def OnFamilyFound(self, familyInUse, overwriteParameterValues):
        return False, False

    def OnSharedFamilyFound(self, sharedFamily, familyInUse, source, overwriteParameterValues):
        return False, FamilySource.Project, False


def wanted_family_names(S):
    """Имена всех семейств инструмента: роли из S['families'] + семейства тегов из S['tags']."""
    out = []
    for n in list((S.get('families') or {}).values()) + \
            [p[0] for p in (S.get('tags') or {}).values() if p]:
        if n and n not in out:
            out.append(n)
    return out


def load_missing_families(doc, folder, S, log=None):
    """Семейства, которых нет в проекте, грузит из <folder>/<имя>.rfa (имя файла = имя семейства).
    Загруженные в проекте не перезаписывает. Нужна открытая TransactionGroup или ничего.
    -> (загружено, нет файла, ошибки [(имя, текст)])."""
    have = set(_name(f) for f in FilteredElementCollector(doc).OfClass(Family))
    todo = [n for n in wanted_family_names(S) if n not in have]
    files = [(n, os.path.join(folder, n + u'.rfa')) for n in todo]
    files = [(n, p) for n, p in files if os.path.isfile(p)]
    loaded, failed = [], []
    if files:
        t = Transaction(doc, u'Wall Rebar 2D: load families')
        t.Start()
        try:
            for n, p in files:
                try:
                    ref = clr.Reference[Family]()
                    ok = doc.LoadFamily(p, _KeepExisting(), ref)
                    if ok and ref.Value is not None:
                        loaded.append(n)
                    else:
                        failed.append((n, u'LoadFamily returned False'))
                except Exception as ex:
                    failed.append((n, unicode(ex)))
            t.Commit()
        except Exception:
            t.RollBack()
            raise
    absent = [n for n in todo if n not in [f for f, _ in files]]
    if log:
        for n in loaded:
            log.processed(u'family %s' % n, u'loaded from the button folder')
        for n, why in failed:
            log.error(u'family %s' % n, why)
    return loaded, absent, failed


def find_symbols(doc, S):
    """{'edge': FamilySymbol, 'inner': ..., 'corner': ...}; бросает, если чего-то нет."""
    want = S['families']
    found = {}
    for fam in FilteredElementCollector(doc).OfClass(Family):
        n = _name(fam)
        for key, fname in want.items():
            if n == fname:
                ids = list(fam.GetFamilySymbolIds())
                if ids:
                    found[key] = doc.GetElement(ids[0])
    optional = ('pier', 'stirrup', 'hairpin')
    missing = [want[k] for k in want if k not in found and k not in optional]
    if missing:
        raise Exception(u'Families not loaded in the project and not found as .rfa in the '
                        u'button folder: ' + u', '.join(missing))
    for k in optional:
        if k not in found:
            found[k] = None       # нет семейства простенка / хомута — без них
    return found


def delete_previous(doc, view, S):
    """Удаляет на виде экземпляры, поставленные этим инструментом раньше (по Comments)."""
    marker = S['marker_comment']
    ids = List[ElementId]()
    for fi in FilteredElementCollector(doc, view.Id).OfClass(FamilyInstance):
        p = fi.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        if p and p.AsString() == marker:
            ids.Add(fi.Id)
    if ids.Count:
        doc.Delete(ids)
    return ids.Count


# --- установка параметров -------------------------------------------------
def _set(inst, name, value, kind):
    p = inst.LookupParameter(name)
    if p is None or p.IsReadOnly:
        return False
    if kind == 'len_mm':
        p.Set(float(value) / MM)
    elif kind == 'int':
        p.Set(int(value))
    elif kind == 'num':
        p.Set(float(value))
    elif kind == 'str':
        p.Set(unicode(value))
    return True


def _place(doc, view, symbol, origin_mm, ex, S, params):
    """Ставит семейство в точку origin (мм), поворачивает так, чтобы +X семейства смотрел вдоль ex."""
    if not symbol.IsActive:
        symbol.Activate()
    pt = XYZ(origin_mm[0] / MM, origin_mm[1] / MM, 0.0)
    inst = doc.Create.NewFamilyInstance(pt, symbol, view)
    ang = math.atan2(ex[1], ex[0])
    if abs(ang) > 1e-6:
        axis = Line.CreateBound(pt, XYZ(pt.X, pt.Y, pt.Z + 1.0))
        ElementTransformUtils.RotateElement(doc, inst.Id, axis, ang)
    failed = [name for name, value, kind in params if not _set(inst, name, value, kind)]
    cp = inst.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    if cp and not cp.IsReadOnly:
        cp.Set(S['marker_comment'])
    if failed:
        FAILED_PARAMS.setdefault(_name(symbol.Family), set()).update(failed)
    return inst


def _perp(d):
    """+Y семейства при +X = d (поворот на +90°)."""
    return (-d[1], d[0])


def _origin_for_zone(P, d, t_mm):
    """Семейства зон (edge/inner) растут от начала вдоль +X и вниз (-Y) на h.
    Чтобы зона легла симметрично на ось стены, начало сдвигаем на +Y на h/2."""
    py = _perp(d)
    return (P[0] + py[0] * t_mm / 2.0, P[1] + py[1] * t_mm / 2.0)


# ----------------------------------------------------------------------
# план расстановки: что и где должно стоять
# ----------------------------------------------------------------------
KEY_PARAM = 'InstanceDescription'   # общий строковый параметр всех PR_Reinforcement*


def _key(*parts):
    return u'|'.join(unicode(x) for x in parts)


def _zone_params(t_mm, edge, per_row, S):
    return [('h', t_mm, 'len_mm'),
            ('Cover', S['cover_cm'] * 10, 'len_mm'),
            ('offset', S['edge_offset_cm'] * 10, 'len_mm'),
            ('Rebar_Spacing', S['edge_bar_spacing_mm'], 'len_mm'),
            ('Quantity x', per_row, 'int'),
            ('Quantity y', edge['rows'], 'int'),
            ('Rebar_Diameter', edge['dia'], 'len_mm')]


def _inner_params(t_mm, inner, length_mm, S):
    return [('h', t_mm, 'len_mm'),
            ('Cover', S['cover_cm'] * 10, 'len_mm'),
            ('offset', inner['gap_cm'] * 10, 'len_mm'),
            # семейство: Quantity x = floor((w - offset) / шаг) + 1, стержни в offset + i*шаг, пока <= w.
            # offset здесь = шагу, поэтому при w = длине зоны выходил лишний стержень на месте
            # краевого -> даём w на полшага короче (последний стержень + полшага)
            ('w', length_mm - inner['spacing_mm'] / 2.0, 'len_mm'),
            ('Rebar_Spacing', inner['spacing_mm'], 'len_mm'),
            ('Quantity y', inner['rows'], 'int'),
            ('Rebar_Diameter', inner['dia'], 'len_mm')]


def _corner_geometry(node, S):
    """(origin, ex, b_mm, h_mm, wings, extra) для углового семейства.

    У семейства один размер b на обе вертикальные ветви и один h на обе горизонтальные.
    «Тело» узла строится по самой толстой стене каждого направления (по её оси). Луч, у которого
    толщина или ось не совпадают с телом (стена 25 над стеной 30 с общей гранью и т.п.),
    в семействе гасится и возвращается в extra — его рисует краевое семейство по реальной
    оси и толщине стены, иначе стержни выходят за грань стены (20.09.2026).
    extra: список dict(dv, t, n, P) — направление, толщина, позиций, точка на оси луча у грани узла."""
    legs = node.legs

    def ax_score(l):
        return -abs(l['chain'].axis.u[0])

    h_leg = sorted(legs, key=ax_score)[0]
    ex = h_leg['chain'].axis.u
    if ex[0] < 0 or (abs(ex[0]) < 1e-6 and ex[1] < 0):
        ex = (-ex[0], -ex[1])
    ey = _perp(ex)
    h_legs = [l for l in legs if abs(core._dot(l['chain'].axis.u, ex)) >= 0.7]
    v_legs = [l for l in legs if abs(core._dot(l['chain'].axis.u, ex)) < 0.7]
    main_h = sorted(h_legs, key=lambda l: -l['t'])[0] if h_legs else None
    main_v = sorted(v_legs, key=lambda l: -l['t'])[0] if v_legs else None
    h_mm = main_h['t'] if main_h else (main_v['t'] if main_v else 0.0)
    b_mm = main_v['t'] if main_v else h_mm
    # центр тела узла: по оси главной вертикальной стены (координата вдоль ex)
    # и по оси главной горизонтальной (координата вдоль ey)
    cx = core._dot(main_v['chain'].axis.p0, ex) if main_v else core._dot(node.p, ex)
    cy = core._dot(main_h['chain'].axis.p0, ey) if main_h else core._dot(node.p, ey)
    C = (ex[0] * cx + ey[0] * cy, ex[1] * cx + ey[1] * cy)
    origin = (C[0] - ex[0] * b_mm / 2.0 + ey[0] * h_mm / 2.0,
              C[1] - ex[1] * b_mm / 2.0 + ey[1] * h_mm / 2.0)
    d = node.design
    per_leg = (d.get('wings') or []) if d else []
    wings = {'Top': 0, 'Bottom': 0, 'Left': 0, 'Right': 0}
    wide = {}                                    # ветвь -> (позиций, толщина стены, смещение оси от центра тела)
    extra = []
    for i, l in enumerate(legs):
        u = l['chain'].axis.u
        dv = (u[0] * l['dir'], u[1] * l['dir'])
        n = per_leg[i] if i < len(per_leg) else 1
        along_ex = abs(core._dot(dv, ex)) >= 0.7
        if along_ex:
            k = 'Right' if core._dot(dv, ex) > 0 else 'Left'
            shift = core._dot(l['chain'].axis.p0, ey) - cy
            fits = abs(l['t'] - h_mm) <= 1.0 and abs(shift) <= 1.0
        else:
            k = 'Top' if core._dot(dv, ey) > 0 else 'Bottom'
            shift = core._dot(l['chain'].axis.p0, ex) - cx
            fits = abs(l['t'] - b_mm) <= 1.0 and abs(shift) <= 1.0
        wide[k] = (n, l['t'], shift)
        if fits:
            wings[k] = n
            continue
        if n:
            half = (b_mm if along_ex else h_mm) / 2.0
            ax = l['chain'].axis
            foot = ax.pt(ax.s_of(C))                 # проекция центра узла на ось этого луча
            extra.append(dict(dv=dv, t=l['t'], n=n,
                              P=(foot[0] + dv[0] * half, foot[1] + dv[1] * half)))
    return origin, ex, b_mm, h_mm, wings, extra, wide


def _dir_code(dv):
    """Луч узла в мировых осях: R / L / T / B — для ключа отдельной ветви."""
    if abs(dv[0]) >= abs(dv[1]):
        return 'R' if dv[0] > 0 else 'L'
    return 'T' if dv[1] > 0 else 'B'


def pier_family_applies(r, S, pier_ok=True):
    """Отдельный простенок: оба конца торец/проём (узлов и колонн нет) и L <= порога."""
    if not (pier_ok and S.get('use_pier_family')):
        return False
    if r['L_cm'] > S['short_wall_max_cm'] + 1e-6:
        return False
    return all(k in ('start', 'end', 'opening') for k, _ in r['edges'])


def _pier_item(r, S):
    """Одно семейство PR_Walls Reinforcement на весь простенок.

    Геометрия семейства: начало в углу, локальный +X поперёк стены (толщина Width),
    локальный -Y вдоль простенка (Length). Ставим начало на грани у торца s0 так,
    чтобы ось стены прошла по середине толщины.
    """
    p = r['pier']
    ax = p.chain.axis
    u = ax.u
    t = p.t
    e = r['edge']
    wall_id = p.chain.pieces[0][3]
    ex = _perp(u)                                   # локальный +X семейства = поперёк стены
    P = ax.pt(p.s0)
    origin = (P[0] - ex[0] * t / 2.0, P[1] - ex[1] * t / 2.0)
    rows = max(1, e['rows'])
    min_bars = int(S.get('pier_family_min_bars', 4))
    per_row = max(e['per_row'], int(math.ceil(min_bars / float(rows))))
    dia_i, sp_req, rows_i = core._inner_for(t / 10.0, S)
    params = [
        ('Length', p.L, 'len_mm'),
        ('Width', t, 'len_mm'),
        ('Cover', S['cover_cm'] * 10, 'len_mm'),
        ('Quantity x', per_row, 'int'),
        ('Quantity y', rows, 'int'),
        ('Rebar_Diameter', e['dia'], 'len_mm'),
        ('Edge_Spacing', S['edge_bar_spacing_mm'], 'len_mm'),
        ('Rebar_Spacing', sp_req, 'len_mm'),          # требуемый шаг внутри, ряд считает сам
        ('Rebar_Diameter Mesh', dia_i, 'len_mm'),
        ('Inner_On', 1, 'int'),
    ]
    side = r.get('out_side') or 1
    return dict(fam='pier',
                key=_key('P', wall_id, int(round(p.s0))),
                origin=origin, ex=ex, params=params,
                out=(ax.n[0] * side, ax.n[1] * side),
                label=u'pier %d [%.0f] by family: edge %dx%dØ%d, inner Ø%d@%d'
                      % (wall_id, p.s0, rows, per_row, e['dia'], dia_i, sp_req))


def _stirrup_item(r, S, walls=None):
    """Хомут Shape 52 рядом с короткой стеной, снаружи. Ставится по ЦЕНТРУ
    (origin = центр контура). Окончательное место считает core.stirrup_place
    в apply_plan, когда известны поля размеров семейства (см. _stirrup_origin)."""
    p = r['pier']
    ax = p.chain.axis
    u = ax.u
    st = r['stirrup']
    side = r.get('stirrup_side') or 1
    n = (ax.n[0] * side, ax.n[1] * side)
    t_w = st.get('t', p.t)
    off = t_w / 2.0 + S.get('stirrup_gap_mm', 100) + st['B_mm'] / 2.0
    mid = ax.pt((st['s_lo'] + st['s_hi']) / 2.0)
    center = (mid[0] + n[0] * off, mid[1] + n[1] * off)
    wall_id = p.chain.pieces[0][3]
    layout = dict(axis=ax, s_lo=st['s_lo'], s_hi=st['s_hi'], t=t_w, side=side,
                  A=st['A_mm'], B=st['B_mm'], m_along=0.0, m_across=0.0)
    params = [('Rebar_A', st['A_mm'], 'len_mm'),
              ('Rebar_B', st['B_mm'], 'len_mm'),
              ('Rebar_Diameter', st['dia'], 'len_mm'),
              ('Rebar_Spacing', st['spacing_mm'], 'len_mm'),
              ('Vis_Hook', 1 if S.get('stirrup_hooks', True) else 0, 'int'),
              ('Rebar_Vis Dims', 1 if S.get('stirrup_show_dims', True) else 0, 'int'),
              ('Rebar_Quantity Text', u'', 'str')]
    return dict(fam='stirrup', key=_key('H', wall_id, int(round(p.s0))),
                origin=center, center=True, ex=u, out=n, params=params,
                layout=layout, walls=walls or [], half_across=st['B_mm'] / 2.0,
                label=u'stirrup %d [%.0f] %.0fx%.0f Ø%d@%d'
                      % (wall_id, p.s0, st['A_mm'], st['B_mm'], st['dia'], st['spacing_mm']))


def _hairpin_item(r, S, walls=None):
    """Пешка (П-стержень, PEER_Rebar_Shape 21) — деталь рядом со стеной, снаружи; ветви вдоль
    стены, как у настоящего стержня. Место считает core.stirrup_place, как у хомута.
    У семейства основание — локальная X (A за вычетом 2 * Rebar_Cover), ветви B / D — вдоль -Y."""
    p = r['pier']
    ax = p.chain.axis
    hp = r['hairpin']
    side = r.get('out_side') or 1
    n = (ax.n[0] * side, ax.n[1] * side)
    d_into = (ax.u[0] * hp['d'], ax.u[1] * hp['d'])
    ex = (-d_into[1], d_into[0])                 # +X семейства: -Y семейства смотрит вдоль d_into
    s_lo, s_hi = min(hp['closed'], hp['open']), max(hp['closed'], hp['open'])
    off = p.t / 2.0 + S.get('stirrup_gap_mm', 100) + hp['base'] / 2.0
    mid = ax.pt((s_lo + s_hi) / 2.0)
    center = (mid[0] + n[0] * off, mid[1] + n[1] * off)
    wall_id = p.chain.pieces[0][3]
    layout = dict(axis=ax, s_lo=s_lo, s_hi=s_hi, t=p.t, side=side,
                  A=hp['leg'], B=hp['base'], m_along=0.0, m_across=0.0)
    params = [('A', p.t, 'len_mm'),
              ('Rebar_Cover', hp['cov'], 'len_mm'),
              ('Rebar_B', hp['leg'], 'len_mm'),
              ('Rebar_D', hp['leg'], 'len_mm'),
              ('Rebar_Diameter', hp['dia'], 'len_mm'),
              ('Rebar_Spacing', hp['spacing_mm'], 'len_mm'),
              ('Vis_Dims', 1 if S.get('stirrup_show_dims', True) else 0, 'int'),
              ('Rebar_Quantity Text', u'', 'str')]
    return dict(fam='hairpin', key=_key('U', wall_id, int(round(p.s0))),
                origin=center, center=True, ex=ex, wall_u=ax.u, out=n, params=params,
                layout=layout, walls=walls or [], half_across=hp['base'] / 2.0,
                swap_margins=True,
                fixed_margins=tuple(float(v) for v in S.get('hairpin_detail_margins_mm', (200, 300))),
                label=u'hairpin %d [%.0f] %.0fx%.0f Ø%d@%d'
                      % (wall_id, p.s0, hp['base'], hp['leg'], hp['dia'], hp['spacing_mm']))


def _stirrup_line_style(doc, S):
    return _own_line_style(doc, S.get('stirrup_in_line_style', u'PR_WallRebar2D Stirrup'),
                           S.get('stirrup_in_line_weight', 1))


def _own_line_style(doc, name, weight=1):
    """Свой стиль линий (подкатегория Lines): тонкая линия. По нему же скрипт узнаёт
    свои линии на виде при следующем прогоне. -> (GraphicsStyle, Category)"""
    lines_cat = doc.Settings.Categories.get_Item(BuiltInCategory.OST_Lines)
    sub = None
    for c in lines_cat.SubCategories:
        if c.Name == name:
            sub = c
            break
    if sub is None:
        sub = doc.Settings.Categories.NewSubcategory(lines_cat, name)
        sub.SetLineWeight(int(weight), GraphicsStyleType.Projection)
        doc.Regenerate()
    return sub.GetGraphicsStyle(GraphicsStyleType.Projection), sub


def _view_plane_z(view):
    """Кандидаты Z плоскости вида (футы): линии детализации должны лежать в ней."""
    zs = []
    try:
        zs.append(view.SketchPlane.GetPlane().Origin.Z)
    except Exception:
        pass
    try:
        zs.append(view.GenLevel.Elevation)
    except Exception:
        pass
    try:
        zs.append(view.Origin.Z)
    except Exception:
        pass
    zs.append(0.0)
    return zs


def draw_stirrup_lines(doc, view, results, S, log=None):
    """Этап «хомут в стене»: контур хомута тонкими линиями детализации ВНУТРИ короткой стены
    (те же стены и те же A x B, что у хомута-детали; защитный слой stirrup_cover_mm).
    Линии перерисовываются целиком: старые своего стиля на виде удаляются. -> (нарисовано контуров, удалено линий)"""
    style, sub = _stirrup_line_style(doc, S)
    old = List[ElementId]()
    for ce in FilteredElementCollector(doc, view.Id).OfClass(CurveElement):
        try:
            if ce.LineStyle.Id == style.Id:
                old.Add(ce.Id)
        except Exception:
            continue
    n_old = old.Count
    if n_old:
        doc.Delete(old)
    c = float(S.get('stirrup_cover_mm', 25))
    zs = _view_plane_z(view)
    z_ok = None
    n = 0
    for r in results:
        st = r.get('stirrup')
        if not st:
            continue
        p = r['pier']
        ax = p.chain.axis
        hb = st.get('t', p.t) / 2.0 - c
        q = [(st['s_lo'] + c, +hb), (st['s_hi'] - c, +hb), (st['s_hi'] - c, -hb), (st['s_lo'] + c, -hb)]
        pts2 = [(ax.pt(s_)[0] + ax.n[0] * o_, ax.pt(s_)[1] + ax.n[1] * o_) for s_, o_ in q]
        done = False
        for z in ([z_ok] if z_ok is not None else zs):
            try:
                made = []
                for k in range(4):
                    a_, b_ = pts2[k], pts2[(k + 1) % 4]
                    ln = Line.CreateBound(XYZ(a_[0] / MM, a_[1] / MM, z), XYZ(b_[0] / MM, b_[1] / MM, z))
                    dc = doc.Create.NewDetailCurve(view, ln)
                    dc.LineStyle = style
                    made.append(dc)
                z_ok = z
                done = True
                break
            except Exception as ex_:
                err = ex_
        if done:
            n += 1
        elif log:
            log.error(u'stirrup inside wall %d' % p.chain.pieces[0][3], unicode(err))
    for r in results:
        hp = r.get('hairpin')
        if not hp:
            continue
        p = r['pier']
        ax = p.chain.axis
        lat = hp['t'] / 2.0 - hp['cov']
        q = [(hp['open'], +lat), (hp['closed'], +lat), (hp['closed'], -lat), (hp['open'], -lat)]
        pts2 = [(ax.pt(s_)[0] + ax.n[0] * o_, ax.pt(s_)[1] + ax.n[1] * o_) for s_, o_ in q]
        done = False
        for z in ([z_ok] if z_ok is not None else zs):
            try:
                for k in range(3):
                    a_, b_ = pts2[k], pts2[k + 1]
                    ln = Line.CreateBound(XYZ(a_[0] / MM, a_[1] / MM, z), XYZ(b_[0] / MM, b_[1] / MM, z))
                    dc = doc.Create.NewDetailCurve(view, ln)
                    dc.LineStyle = style
                z_ok = z
                done = True
                break
            except Exception as ex_:
                err = ex_
        if done:
            n += 1
        elif log:
            log.error(u'hairpin inside wall %d' % p.chain.pieces[0][3], unicode(err))
    return n, n_old


# Префиксы ключей по этапам: снятый этап не трогаем (не ставим, не удаляем, не правим)
# (хомут в стене — линии детализации, у них ключей нет: см. draw_stirrup_lines)
STAGE_PREFIXES = {'stage_rebar': ('E', 'S', 'I', 'C', 'CW', 'P', 'K'),
                  'stage_stirrup_detail': ('H', 'U')}


def frozen_prefixes(S):
    out = set()
    for stage, prefixes in STAGE_PREFIXES.items():
        if not S.get(stage, True):
            out.update(prefixes)
    return out


def _key_prefix(key):
    return (key or u'').split(u'|', 1)[0]


_MARGINS = {}   # (id типа, dims) -> (поле вдоль, поле поперёк), мм


def _measure_margins(doc, view, symbol, item):
    """Сколько семейство рисует вокруг контура (размеры, крюки): временный
    экземпляр далеко от всего, bbox против кривых, потом удаляется."""
    dims = 1 if S_get(item, 'Rebar_Vis Dims') else 0
    key = (symbol.Id.IntegerValue, dims)
    if key in _MARGINS:
        return _MARGINS[key]
    if not symbol.IsActive:
        symbol.Activate()
    o = item['origin']                       # внутри crop-области вида, иначе bbox = None
    inst = doc.Create.NewFamilyInstance(XYZ(o[0] / MM, o[1] / MM, 0.0), symbol, view)
    for name, value, kind in item['params']:
        _set(inst, name, value, kind)
    doc.Regenerate()
    m_along = m_across = 0.0
    try:
        opt = Options()
        opt.View = view
        xs, ys = [], []

        def walk(g):
            for o in g:
                if isinstance(o, GeometryInstance):
                    walk(o.GetInstanceGeometry())
                elif isinstance(o, Curve):
                    for q in (o.GetEndPoint(0), o.GetEndPoint(1)):
                        xs.append(q.X * MM)
                        ys.append(q.Y * MM)
        walk(inst.get_Geometry(opt))
        bb = inst.get_BoundingBox(view)
        if xs and bb is not None:
            m_along = max(min(xs) - bb.Min.X * MM, bb.Max.X * MM - max(xs), 0.0)
            m_across = max(min(ys) - bb.Min.Y * MM, bb.Max.Y * MM - max(ys), 0.0)
    finally:
        doc.Delete(inst.Id)
        doc.Regenerate()
    _MARGINS[key] = (m_along, m_across)
    return _MARGINS[key]


def S_get(item, name):
    for n, v, k in item['params']:
        if n == name:
            return v
    return None


def _stirrup_origin(doc, view, symbol, item, S):
    """Окончательное место выноски с учётом полей размеров и всех стен вида."""
    if item.get('fixed_margins'):
        # габарит семейства врёт (у Shape 21 скрытые выноска/метка дают +0,9..1 м) — поля из настроек
        m_along, m_across = item['fixed_margins']
    else:
        m_along, m_across = _measure_margins(doc, view, symbol, item)
        if item.get('swap_margins'):             # у пешки ветви вдоль локальной Y семейства
            m_along, m_across = m_across, m_along
    lay = dict(item['layout'], m_along=m_along, m_across=m_across)
    center, ha, hb = core.stirrup_place(lay, item.get('walls') or [], S, boxes=_STIRRUP_BOXES)
    item['origin'] = center
    item['half_across'] = hb
    item['half_along'] = ha
    _STIRRUP_BOXES.append(core.box_aabb(center, item.get('wall_u') or item['ex'], ha, hb))
    return center


_STIRRUP_BOXES = []   # прямоугольники выносок, уже размещённых в этом прогоне (мм)


def _column_item(r, S):
    """Простенок-колонна одним семейством «2 Line Spacing» от торца до торца."""
    p = r['pier']
    ax = p.chain.axis
    col = r['column']
    side = r.get('out_side') or 1
    step = col['spacing_mm'] or 1.0
    params = [('h', p.t, 'len_mm'),
              ('Cover', S['cover_cm'] * 10, 'len_mm'),
              ('offset', col['offset_mm'], 'len_mm'),
              # семейство: Quantity x = floor((w - offset) / шаг) + 1 (проверено 20.09 на экземпляре):
              # стержни идут от offset с шагом, пока не дойдут до w -> w = последний стержень + полшага
              # запас после последнего стержня меньше отступа от торца -> зона семейства внутри стены
              ('w', col['offset_mm'] + (col['per_row'] - 1) * step
                    + min(step / 2.0, max(col['offset_mm'] - 5.0, 1.0)), 'len_mm'),
              ('Rebar_Spacing', step, 'len_mm'),
              ('Quantity y', col['rows'], 'int'),
              ('Rebar_Diameter', col['dia'], 'len_mm')]
    wall_id = p.chain.pieces[0][3]
    return dict(fam='inner', key=_key('K', wall_id, int(round(p.s0))), wall=p.chain.id,
                bars=_bars_strip(ax.pt(p.s0), ax.u, p.t,
                                 [col['offset_mm'] + k * step for k in range(col['per_row'])], S),
                origin=_origin_for_zone(ax.pt(p.s0), ax.u, p.t), ex=ax.u,
                out=(ax.n[0] * side, ax.n[1] * side), params=params,
                label=u'column %d [%.0f] %dØ%d@%d' % (wall_id, p.s0, col['n'], col['dia'], step))


def _bars_strip(P, d, t, positions, S, shift=0.0):
    """Точки стержней (мм): вдоль d от P на расстояниях positions, два ряда у граней стены
    толщиной t (защитный слой cover_cm); shift — сдвиг оси рядов поперёк (вдоль _perp(d))."""
    lat = t / 2.0 - S['cover_cm'] * 10.0
    n = _perp(d)
    rows = (lat, -lat) if lat > 1.0 else (0.0,)
    pts = []
    for s_ in positions:
        for l in rows:
            pts.append((P[0] + d[0] * s_ + n[0] * (l + shift), P[1] + d[1] * s_ + n[1] * (l + shift)))
    return pts


def _corner_bars(origin, ex, b_mm, h_mm, wings4, S):
    """Точки стержней углового семейства. wings4: {'Top': (n, t, shift), ...}."""
    ey = _perp(ex)
    C = (origin[0] + ex[0] * b_mm / 2.0 - ey[0] * h_mm / 2.0,
         origin[1] + ex[1] * b_mm / 2.0 - ey[1] * h_mm / 2.0)
    cov = S['cover_cm'] * 10.0
    hx, hy = max(b_mm / 2.0 - cov, 0.0), max(h_mm / 2.0 - cov, 0.0)
    pts = [(C[0] + ex[0] * sx * hx + ey[0] * sy * hy, C[1] + ex[1] * sx * hx + ey[1] * sy * hy)
           for sx in (-1, 1) for sy in (-1, 1)]
    sp = float(S['corner_wing_spacing_mm'])
    dirs = {'Top': (ey, h_mm / 2.0, -1.0), 'Bottom': ((-ey[0], -ey[1]), h_mm / 2.0, 1.0),
            'Left': ((-ex[0], -ex[1]), b_mm / 2.0, -1.0), 'Right': (ex, b_mm / 2.0, 1.0)}
    for k, (n_k, t_k, shift_k) in wings4.items():
        if not n_k:
            continue
        d, face, sgn = dirs[k]
        P = (C[0] + d[0] * face, C[1] + d[1] * face)
        pts.extend(_bars_strip(P, d, t_k, [(i + 1) * sp for i in range(n_k)], S, shift=sgn * shift_k))
    return pts


def _far_pair(pts):
    """Две самые далёкие друг от друга точки (первый и последний стержень «по диагонали»)."""
    best = (pts[0], pts[0], -1.0)
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            dd = (pts[i][0] - pts[j][0]) ** 2 + (pts[i][1] - pts[j][1]) ** 2
            if dd > best[2]:
                best = (pts[i], pts[j], dd)
    return best[0], best[1]


def _group_for_tags(plan, S):
    """Один тег на группу — логика пользователя «в стенке стоит один диаметр — зачем три тега»:
      1. в пределах ОДНОЙ стенки соседние элементы одного диаметра (край, ряд, колонна), между
         стержнями которых не больше tag_group_gap_mm, — одна группа;
      2. узел присоединяется только к ОДНОЙ стенке — первой из примыкающих (короткие первыми),
         где тот же диаметр и арматура рядом (элемент стенки ИЛИ узел на другом
         её конце); иначе через узлы склеилось бы всё ядро в один тег;
      3. ветвь-заплатка угла (CW) всегда вместе со своим углом.
    Сумма стержней пишется в «Rebar_Quantity Text» хозяина (у кого стержней больше, при равенстве —
    угол), он получает тег роли group («… (Text Quantity)»), остальные члены группы — без тега."""
    gap = float(S.get('tag_group_gap_mm', 250))
    items = [i for i in plan if i.get('bars')]
    for i in items:
        xs = [q[0] for q in i['bars']]
        ys = [q[1] for q in i['bars']]
        i['_rect'] = (min(xs), min(ys), max(xs), max(ys))
        i['_dia'] = S_get(i, 'Rebar_Diameter')
        i['tag_bars'] = list(i['bars'])
        i['tag_role'] = None
        i['no_tag'] = False
    parent = list(range(len(items)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def near(a, b):
        return items[a]['_dia'] == items[b]['_dia'] and core.rects_overlap(items[a]['_rect'], items[b]['_rect'], gap)

    if S.get('tag_group_on', True):
        idx = range(len(items))
        by_wall = {}
        for k in idx:
            if items[k].get('wall') is not None:
                by_wall.setdefault(items[k]['wall'], []).append(k)
        for ks in by_wall.values():                       # 1. внутри стенки
            for a in ks:
                for b in ks:
                    if a < b and near(a, b):
                        parent[find(a)] = find(b)
        nodes_k = [k for k in idx if items[k].get('fam') == 'corner']
        for k in idx:                                     # 3. заплатка — к своему углу
            if items[k].get('cw_fallback'):
                for c in nodes_k:
                    if items[c].get('node') == items[k].get('node') and items[c]['_dia'] == items[k]['_dia']:
                        parent[find(k)] = find(c)
        for c in nodes_k:                                 # 2. узел — к одной стенке, короткие первыми
            for wall_id, wall_len in items[c].get('node_walls') or []:
                cand = [k for k in by_wall.get(wall_id, []) if near(c, k)]
                # в стенке может не быть своих элементов — только ветви двух узлов на её концах
                # (короткая стенка между узлами): тогда узлы этой стенки объединяются между собой
                cand += [k for k in nodes_k if k != c and near(c, k)
                         and any(w == wall_id for w, _l in (items[k].get('node_walls') or []))]
                if cand:
                    parent[find(c)] = find(cand[0])
                    break
    clusters = {}
    for k in range(len(items)):
        clusters.setdefault(find(k), []).append(items[k])
    for members in clusters.values():
        texts = {}
        if len(members) > 1:
            host = sorted(members, key=lambda m: (-len(m['bars']), m['fam'] != 'corner', m['key']))[0]
            total = sum(len(m['bars']) for m in members)
            allpts = []
            for m in members:
                allpts.extend(m['bars'])
                m['no_tag'] = m is not host
            host['tag_role'] = 'group'
            host['tag_bars'] = allpts
            texts[id(host)] = unicode(total)
        for m in members:
            txt = texts.get(id(m), u'')
            for prm in ('params', 'params_wide'):
                if m.get(prm) is not None and not any(n == 'Rebar_Quantity Text' for n, v, k in m[prm]):
                    m[prm].append(('Rebar_Quantity Text', txt, 'str'))


def _wing_reach(ev, leg_dir, chain, S):
    """Сколько мм от грани узла занимает ветвь углового семейства на этом простенке
    (0 — на этом конце узла нет). Первый стержень ветви — в шаге от грани узла,
    плюс полшага зазора после последнего."""
    if ev.kind not in ('corner', 'tee', 'cross'):
        return 0.0
    nd = ev.ref
    d = getattr(nd, 'design', None)
    if not d:
        return 0.0
    wings = d.get('wings') or []
    n = 1
    for i, l in enumerate(nd.legs):
        if l['chain'] is chain and l['dir'] == leg_dir and i < len(wings):
            n = wings[i]
            break
    return (n + 0.5) * float(S.get('corner_wing_spacing_mm', 70))


def build_plan(results, nodes, S, pier_ok=True, stirrup_ok=True, walls=None, hairpin_ok=True):
    """Список того, что должно стоять на виде. Каждый элемент со своим ключом."""
    plan = []
    for r in results:
        if stirrup_ok and r.get('stirrup'):
            plan.append(_stirrup_item(r, S, walls))
        if hairpin_ok and r.get('hairpin'):
            plan.append(_hairpin_item(r, S, walls))
        if r.get('stub'):                        # огрызок: только угловое семейство
            continue
        if r.get('column'):                      # простенок-колонна: один ряд на всю длину
            plan.append(_column_item(r, S))
            continue
        if pier_family_applies(r, S, pier_ok):
            plan.append(_pier_item(r, S))
            continue
        p = r['pier']
        ax = p.chain.axis
        u = ax.u
        t = p.t
        e = r['edge']
        wall_id = p.chain.pieces[0][3]
        side = r.get('out_side') or 1
        out_r = (ax.n[0] * side, ax.n[1] * side)
        if r['single_group']:
            w_mm = (r['single_per_row'] - 1) * S['edge_bar_spacing_mm'] + 2 * S['edge_offset_cm'] * 10
            s_start = p.s0 + (p.L - w_mm) / 2.0
            # короткий простенок у угла: группа налезает на ветвь углового семейства —
            # дополнительную арматуру не ставим, там работает угол (пользователь, 19.09)
            if (s_start < p.s0 + _wing_reach(p.ev0, +1, p.chain, S) or
                    s_start + w_mm > p.s1 - _wing_reach(p.ev1, -1, p.chain, S)):
                continue
            plan.append(dict(fam='edge',
                             key=_key('E', wall_id, int(round(p.s0)), 'C'),
                             origin=_origin_for_zone(ax.pt(s_start), u, t), ex=u, out=out_r,
                             params=_zone_params(t, e, r['single_per_row'], S),
                             label=u'pier %d [%.0f] single group %dØ%d'
                                   % (wall_id, p.s0, r['single_per_row'] * e['rows'], e['dia'])))
            continue
        pairs = ((r['edges'][0], p.s0, u, r['edge0'], '0'),
                 (r['edges'][1], p.s1, (-u[0], -u[1]), r['edge1'], '1'))
        skip_edge = r.get('skip_edge') or [False, False]
        for (kind, ref), s_end, d, ee, side in pairs:
            if kind in ('start', 'end', 'opening') and skip_edge[int(side)]:
                continue                         # арматура угла доходит сюда — краевую группу не ставим
            if kind in ('start', 'end', 'opening'):
                plan.append(dict(fam='edge', wall=p.chain.id,
                                 bars=_bars_strip(ax.pt(s_end), d, t,
                                                  [S['edge_offset_cm'] * 10.0 + k * S['edge_bar_spacing_mm']
                                                   for k in range(ee['per_row'])], S),
                                 key=_key('E', wall_id, int(round(p.s0)), side),
                                 origin=_origin_for_zone(ax.pt(s_end), d, t), ex=d, out=out_r,
                                 params=_zone_params(t, ee, ee['per_row'], S),
                                 label=u'edge %d [%.0f] %dØ%d' % (wall_id, s_end, ee['n'], ee['dia'])))
            elif kind == 'step' and ref:
                if t >= max(ref.get('t_from', 0), ref.get('t_to', 0)) - 1:
                    n_bars, dia_rule = S['thickness_step_add']
                    dia = S.get('edge_min_diameter', 12) if dia_rule == 'edge_min' else dia_rule
                    rows = min(n_bars, ee['rows']) or 1
                    step_edge = dict(rows=rows, dia=dia)
                    plan.append(dict(fam='edge',
                                     key=_key('S', wall_id, int(round(s_end))),
                                     origin=_origin_for_zone(ax.pt(s_end), d, t), ex=d, out=out_r,
                                     params=_zone_params(t, step_edge, max(1, n_bars // rows), S),
                                     label=u'thickness step %d [%.0f]' % (wall_id, s_end)))
        if r['inner']:
            x0_mm = r['inner']['x_start_cm'] * 10
            length_mm = r['inner']['length_cm'] * 10
            plan.append(dict(fam='inner', wall=p.chain.id,
                             bars=_bars_strip(ax.pt(p.s0 + x0_mm), u, t,
                                              [(k + 1) * r['inner']['spacing_mm']
                                               for k in range(r['inner']['per_row'])], S),
                             key=_key('I', wall_id, int(round(p.s0))),
                             origin=_origin_for_zone(ax.pt(p.s0 + x0_mm), u, t), ex=u, out=out_r,
                             params=_inner_params(t, r['inner'], length_mm, S),
                             label=u'inner %d [%.0f] %dØ%d@%d'
                                   % (wall_id, p.s0, r['inner']['n'], r['inner']['dia'],
                                      r['inner']['spacing_mm'])))
    for nd in nodes:
        if nd.design is None:
            continue
        origin, ex, b_mm, h_mm, wings, extra, wide = _corner_geometry(nd, S)
        d = nd.design
        params = [('b', b_mm, 'len_mm'), ('h', h_mm, 'len_mm'),
                  ('Cover', S['cover_cm'] * 10, 'len_mm'),
                  ('Rebar_Diameter', d['dia'], 'len_mm'),
                  ('Corner_Quantity b', S['corner_block_bars'][0], 'int'),
                  ('Corner_Quantity h', S['corner_block_bars'][1], 'int'),
                  ('Spacing 50', S['corner_wing_spacing_mm'], 'len_mm')]
        vis = {'Top': 'Vis_WallTop', 'Bottom': 'Vis_WallBot',
               'Left': 'Vis_WallLeft', 'Right': 'Vis_WallRight'}
        cnt = {'Top': 'Wall_Top', 'Bottom': 'Wall_Bottom',
               'Left': 'Wall_Left', 'Right': 'Wall_Right'}
        # Вариант для семейства со СВОЕЙ шириной и смещением каждой ветви (имена — в настройках
        # corner_wing_width_params / corner_wing_offset_params): все ветви рисует само семейство.
        params_wide = list(params)
        wn = S.get('corner_wing_width_params') or {}
        on = S.get('corner_wing_offset_params') or {}
        for k in wings:
            n_k, t_k, shift_k = wide.get(k, (0, (b_mm if k in ('Top', 'Bottom') else h_mm), 0.0))
            params_wide.append((vis[k], 1 if n_k else 0, 'int'))
            params_wide.append((cnt[k], n_k if n_k else 2, 'int'))
            if wn.get(k):
                params_wide.append((wn[k], t_k, 'len_mm'))
            if on.get(k):
                params_wide.append((on[k], shift_k, 'len_mm'))
        for k in wings:
            params.append((vis[k], 1 if wings[k] else 0, 'int'))
            params.append((cnt[k], wings[k] if wings[k] else 2, 'int'))
        narrow4 = dict((k, (wings[k], (b_mm if k in ('Top', 'Bottom') else h_mm), 0.0)) for k in wings)
        wide4 = dict((k, wide.get(k, (0, 0.0, 0.0))) for k in wings)
        node_walls = {}
        for l in nd.legs:
            lo_, hi_ = core._chain_span(l['chain'])
            node_walls[l['chain'].id] = hi_ - lo_
        plan.append(dict(fam='corner', params_wide=params_wide, node=nd.id,
                         node_walls=sorted(node_walls.items(), key=lambda kv: (kv[1], kv[0])),
                         bars=_corner_bars(origin, ex, b_mm, h_mm, narrow4, S),
                         bars_wide=_corner_bars(origin, ex, b_mm, h_mm, wide4, S),
                         key=_key('C', int(round(nd.p[0])), int(round(nd.p[1]))),
                         origin=origin, ex=ex, params=params,
                         out=getattr(nd, 'outward', None) or _perp(ex), node_p=nd.p,
                         label=u'node %d %s %dØ%d' % (nd.id, nd.kind, d['n'], d['dia'])))
        # лучи другой толщины / со сдвинутой осью: ветвь краевым семейством по реальной стене
        sp = S['corner_wing_spacing_mm']
        for x in extra:
            dv = x['dv']
            wparams = [('h', x['t'], 'len_mm'),
                       ('Cover', S['cover_cm'] * 10, 'len_mm'),
                       ('offset', sp, 'len_mm'),
                       ('Rebar_Spacing', sp, 'len_mm'),
                       ('Quantity x', x['n'], 'int'),
                       ('Quantity y', 2, 'int'),
                       ('Rebar_Diameter', d['dia'], 'len_mm')]
            plan.append(dict(fam='edge', cw_fallback=True, node=nd.id,
                             bars=_bars_strip(x['P'], dv, x['t'], [(k + 1) * sp for k in range(x['n'])], S),
                             key=_key('CW', int(round(nd.p[0])), int(round(nd.p[1])), _dir_code(dv)),
                             origin=_origin_for_zone(x['P'], dv, x['t']), ex=dv,
                             out=_perp(dv), params=wparams,
                             label=u'node %d leg %s (wall %.0f) %dØ%d'
                                   % (nd.id, _dir_code(dv), x['t'], 2 * x['n'], d['dia'])))
    return plan


# ----------------------------------------------------------------------
# применение плана: создать / обновить / удалить
# ----------------------------------------------------------------------
# Параметры, задающие ГЕОМЕТРИЮ элемента (зависят от стены). Их расхождение с расчётом
# значит «стена изменилась» — элемент сносится и ставится заново. Всё остальное
# (Ø, количество, шаг) — расчётные: ручную правку сохраняем (update_policy = keep_manual).
SHAPE_PARAMS = set(['h', 'w', 'b', 'offset', 'Cover', 'Length', 'Width',
                    'Rebar_A', 'Rebar_B', 'Inner_On',
                    'Vis_WallTop', 'Vis_WallBot', 'Vis_WallLeft', 'Vis_WallRight',
                    'Wall_Top_Width', 'Wall_Bottom_Width', 'Wall_Left_Width', 'Wall_Right_Width',
                    'Wall_Top_Offset', 'Wall_Bottom_Offset', 'Wall_Left_Offset', 'Wall_Right_Offset'])


# Параметры, которые скрипт пишет в ЛЮБОЕ семейство арматуры сверх расчётных
REQUIRED_EXTRA = (KEY_PARAM, 'Rebar_Quantity Text')

KIND_NO_FAMILY = u'FAMILY NOT LOADED'
KIND_NO_TYPES = u'FAMILY HAS NO TYPES'
KIND_NO_PARAMS = u'PARAMETERS MISSING'
KIND_RO_PARAMS = u'PARAMETERS ARE READ-ONLY'
KIND_NO_CHECK = u'COULD NOT BE CHECKED'
KIND_NO_TAG = u'TAG TYPE NOT FOUND'


def missing_param_names(problems):
    """Имена параметров, которых не хватает (из отчёта preflight)."""
    names = []
    for x in problems or []:
        if x.get('kind') == KIND_NO_PARAMS:
            names.extend(n.strip() for n in (x.get('detail') or u'').split(u','))
    return sorted(set(n for n in names if n))


def shared_param_status(doc, names):
    """Есть ли у проекта файл общих параметров и лежат ли в нём нужные определения.
    -> dict(path, found={имя: ExternalDefinition}, absent=[имена])."""
    app = doc.Application
    try:
        path = app.SharedParametersFilename
    except Exception:
        path = None
    out = dict(path=path or u'', exists=False, found={}, absent=sorted(names))
    if not path or not os.path.isfile(path):
        return out                                # путь не задан или файла нет на диске (сетевой диск?)
    out['exists'] = True
    try:
        f = app.OpenSharedParameterFile()
    except Exception:
        f = None
    if f is None:
        return out
    found = {}
    for g in f.Groups:
        for d in g.Definitions:
            if d.Name in names:
                found[d.Name] = d
    out['found'] = found
    out['absent'] = sorted(n for n in names if n not in found)
    return out


def param_categories(doc, S):
    """Категории, к которым привязывать параметры проекта: категории загруженных семейств
    инструмента, иначе Detail Items."""
    want = set((S.get('families') or {}).values())
    cats = {}
    for fam in FilteredElementCollector(doc).OfClass(Family):
        if _name(fam) in want and fam.FamilyCategory is not None:
            cats[fam.FamilyCategory.Id.IntegerValue] = fam.FamilyCategory
    if not cats:
        c = doc.Settings.Categories.get_Item(BuiltInCategory.OST_DetailComponents)
        if c is not None:
            cats[c.Id.IntegerValue] = c
    return list(cats.values())


SPF_GROUP = 'WallRebar2D'
TAB = chr(9)
EOL = chr(10)
SPF_HEADER = EOL.join([
    u'# This is a Revit shared parameter file.',
    u'# Do not edit manually.',
    TAB.join([u'*META', u'VERSION', u'MINVERSION']),
    TAB.join([u'META', u'2', u'1']),
    TAB.join([u'*GROUP', u'ID', u'NAME']),
    TAB.join([u'*PARAM', u'GUID', u'NAME', u'DATATYPE', u'DATACATEGORY', u'GROUP',
              u'VISIBLE', u'DESCRIPTION', u'USERMODIFIABLE', u'HIDEWHENNOVALUE']),
    u''])


def own_spf_path():
    """Свой файл общих параметров — на случай, если у проекта его нет или он недоступен."""
    return os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')),
                        'WallRebar2D', 'WallRebar2D_shared_params.txt')


def ensure_and_bind(doc, names, categories, log=None):
    """Создаёт недостающие определения в файле общих параметров (в файле проекта, а если его нет
    или он недоступен — в своём, %AppData%/WallRebar2D/) и привязывает их как параметры проекта.
    МЕНЯЕТ МОДЕЛЬ — вызывать после подтверждения пользователем.
    -> dict(path, created, added, errors)."""
    app = doc.Application
    out = dict(path=u'', created=[], added=[], errors=[])
    if ExternalDefinitionCreationOptions is None or SpecTypeId is None:
        out['errors'].append((u'-', u'this Revit version cannot create shared parameters from API'))
        return out
    try:
        orig = app.SharedParametersFilename
    except Exception:
        orig = u''
    target = orig if (orig and os.path.isfile(orig)) else own_spf_path()
    out['path'] = target
    try:
        if not os.path.isfile(target):
            folder = os.path.dirname(target)
            if folder and not os.path.isdir(folder):
                os.makedirs(folder)
            f = codecs.open(target, 'w', 'utf-8')
            f.write(SPF_HEADER)
            f.close()
        app.SharedParametersFilename = target
        df = app.OpenSharedParameterFile()
        if df is None:
            out['errors'].append((u'-', u'cannot open the shared parameter file %s' % target))
            return out
        group = None
        for g in df.Groups:
            if g.Name == SPF_GROUP:
                group = g
                break
        if group is None:
            group = df.Groups.Create(SPF_GROUP)
        have = {}
        for g in df.Groups:
            for d in g.Definitions:
                have[d.Name] = d
        defs = []
        for n in names:
            if n in have:
                defs.append(have[n])
                continue
            try:
                opt = ExternalDefinitionCreationOptions(n, SpecTypeId.String.Text)
                opt.Visible = True
                opt.UserModifiable = True
                d = group.Definitions.Create(opt)
                defs.append(d)
                out['created'].append(n)
                if log:
                    log.processed(u'shared parameter %s' % n, u'created in %s' % target)
            except Exception as ex_:
                out['errors'].append((n, unicode(ex_)))
        if defs:
            added, errors = add_project_params(doc, defs, categories, log)
            out['added'] = added
            out['errors'].extend(errors)
    finally:
        try:
            if orig and orig != target:
                app.SharedParametersFilename = orig
        except Exception:
            pass
    return out


def add_project_params(doc, ext_defs, categories, log=None):
    """Привязывает определения из файла общих параметров как параметры проекта (экземпляра).
    МЕНЯЕТ МОДЕЛЬ — вызывать только после подтверждения пользователем. -> (added, errors)."""
    app = doc.Application
    cats = app.Create.NewCategorySet()
    for c in categories:
        cats.Insert(c)
    binding = app.Create.NewInstanceBinding(cats)
    added, errors = [], []
    t = Transaction(doc, 'WallRebar2D: add project parameters')
    t.Start()
    try:
        groups = []
        if GroupTypeId is not None:
            groups.append(GroupTypeId.Data)
        if BuiltInParameterGroup is not None:
            groups.append(BuiltInParameterGroup.PG_DATA)
        groups.append(None)
        for d in ext_defs:
            try:
                ok = False
                for g in groups:
                    try:
                        ok = (doc.ParameterBindings.Insert(d, binding) if g is None
                              else doc.ParameterBindings.Insert(d, binding, g))
                        break
                    except Exception:
                        continue
                if ok:
                    added.append(d.Name)
                    if log:
                        log.processed(u'project parameter %s' % d.Name, u'bound to %d category(ies)' % cats.Size)
                else:
                    errors.append((d.Name, u'Revit refused the binding (name already in use?)'))
            except Exception as ex_:
                errors.append((d.Name, unicode(ex_)))
        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise
    if log:
        for nm, why in errors:
            log.error(u'project parameter %s' % nm, why)
    return added, errors


def preflight(doc, view, S, plan=None, log=None):
    """Проверка ПЕРЕД расстановкой: загружены ли нужные семейства арматуры и тегов и есть ли
    в них параметры, которые скрипт собирается писать. Параметры проверяются на ВРЕМЕННОМ
    экземпляре внутри транзакции с откатом — модель не меняется.
    -> [dict(kind, name, detail)]; пустой список = всё на месте."""
    problems = []
    want = S.get('families') or {}
    need = {}
    origin = {}
    count = {}
    for i in (plan or []):
        role = i['fam']
        need.setdefault(role, set()).update(n for n, v, k in i['params'])
        origin.setdefault(role, i['origin'])
        count[role] = count.get(role, 0) + 1
    for role in need:
        need[role].update(REQUIRED_EXTRA)

    fams = {}
    for fam in FilteredElementCollector(doc).OfClass(Family):
        fams[_name(fam)] = fam
    syms = {}
    for role in sorted(need):
        fname = want.get(role)
        fam = fams.get(fname)
        if fam is None:
            problems.append(dict(kind=KIND_NO_FAMILY, name=fname or u'(name not set in settings)',
                                 detail=u'role "%s", %d element(s) to place' % (role, count.get(role, 0))))
            continue
        ids = list(fam.GetFamilySymbolIds())
        if not ids:
            problems.append(dict(kind=KIND_NO_TYPES, name=fname, detail=u'role "%s"' % role))
            continue
        syms[role] = doc.GetElement(ids[0])

    if syms:
        t = Transaction(doc, 'WallRebar2D preflight')
        t.Start()
        try:
            for role in sorted(syms):
                sym = syms[role]
                try:
                    if not sym.IsActive:
                        sym.Activate()
                        doc.Regenerate()
                    o = origin.get(role) or (0.0, 0.0)
                    inst = doc.Create.NewFamilyInstance(XYZ(o[0] / MM, o[1] / MM, 0.0), sym, view)
                    miss, ro = [], []
                    for n in sorted(need[role]):
                        q = inst.LookupParameter(n)
                        if q is None:
                            miss.append(n)
                        elif q.IsReadOnly:
                            ro.append(n)
                    if miss:
                        problems.append(dict(kind=KIND_NO_PARAMS, name=_name(sym.Family),
                                             detail=u', '.join(miss)))
                    if ro:
                        problems.append(dict(kind=KIND_RO_PARAMS, name=_name(sym.Family),
                                             detail=u', '.join(ro)))
                except Exception as ex_:
                    problems.append(dict(kind=KIND_NO_CHECK, name=want.get(role, role),
                                         detail=unicode(ex_)))
        finally:
            t.RollBack()

    if S.get('place_tags'):
        roles_needed = set(['default', 'group'])
        for i in (plan or []):
            if i['fam'] in ('stirrup', 'corner', 'hairpin'):
                roles_needed.add(i['fam'])
        all_syms = tag_symbols(doc)
        for role in sorted(roles_needed):
            pair = (S.get('tags') or {}).get(role)
            if not pair:
                continue
            fam_name, type_name = (list(pair) + [u''])[:2]
            if tag_symbol_for(doc, fam_name, type_name, all_syms) is None:
                problems.append(dict(kind=KIND_NO_TAG, name=u'%s : %s' % (fam_name, type_name),
                                     detail=u'role "%s"' % role))
    if log:
        for x in problems:
            log.error(u'family check: %s' % x['kind'], u'%s — %s' % (x['name'], x['detail']))
    return problems


def _split_key(raw):
    """'ключ#подпись' -> (ключ, подпись). Старые элементы без подписи -> (ключ, None)."""
    if not raw:
        return None, None
    if u'#' in raw:
        k, sig = raw.split(u'#', 1)
        return k, sig
    return raw, None


def _fmt_val(value, kind):
    if kind == 'int':
        return unicode(int(value))
    if kind == 'str':
        return unicode(value)
    return u'%.1f' % float(value)


def _signature(params):
    """Подпись расчётных параметров, которые записал скрипт: 'Rebar_Diameter=16.0;Quantity x=4'."""
    parts = []
    for name, value, kind in params:
        if name in SHAPE_PARAMS:
            continue
        parts.append(u'%s=%s' % (name, _fmt_val(value, kind)))
    return u';'.join(parts)


def _read_val(inst, name, kind):
    p = inst.LookupParameter(name)
    if p is None:
        return None
    if kind == 'len_mm':
        return u'%.1f' % (p.AsDouble() * MM)
    if kind == 'int':
        return unicode(p.AsInteger())
    if kind == 'num':
        return u'%.1f' % p.AsDouble()
    if kind == 'str':
        return unicode(p.AsString() or u'')
    return None


def _sig_of(inst):
    kp = inst.LookupParameter(KEY_PARAM)
    return _split_key(kp.AsString() if kp else None)[1]


def existing_by_key(doc, view, S):
    """{ключ: экземпляр} для всего, что этот инструмент ставил на виде."""
    marker = S['marker_comment']
    out = {}
    orphans = []
    for fi in FilteredElementCollector(doc, view.Id).OfClass(FamilyInstance):
        c = fi.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        if not c or c.AsString() != marker:
            continue
        kp = fi.LookupParameter(KEY_PARAM)
        k, _sig = _split_key(kp.AsString() if kp else None)
        if k:
            out[k] = fi
        else:
            orphans.append(fi)
    return out, orphans


def _needs(inst, params, only=None):
    """Какие параметры отличаются от плановых. only — ограничить набором имён."""
    diff = []
    for name, value, kind in params:
        if only is not None and name not in only:
            continue
        p = inst.LookupParameter(name)
        if p is None or p.IsReadOnly:
            continue
        if kind == 'len_mm':
            if abs(p.AsDouble() * MM - float(value)) > 0.5:
                diff.append(name)
        elif kind == 'int':
            if p.AsInteger() != int(value):
                diff.append(name)
        elif kind == 'num':
            if abs(p.AsDouble() - float(value)) > 1e-6:
                diff.append(name)
        elif kind == 'str':
            if (p.AsString() or u'') != unicode(value):
                diff.append(name)
    return diff


def _manual_edits(inst, item):
    """Расчётные параметры, которые отличаются от того, что скрипт записал в прошлый раз
    (= пользователь правил руками). Без подписи (старые элементы) — считаем ручным всё,
    что отличается от нового расчёта, чтобы ничего не затереть."""
    sig = _sig_of(inst)
    last = {}
    if sig:
        for part in sig.split(u';'):
            if u'=' in part:
                n, v = part.split(u'=', 1)
                last[n] = v
    manual = []
    for name, value, kind in item['params']:
        if name in SHAPE_PARAMS:
            continue
        cur = _read_val(inst, name, kind)
        if cur is None:
            continue
        base = last.get(name)
        if base is None:
            base = _fmt_val(value, kind)      # нет подписи: сравниваем с расчётом
        if cur != base:
            manual.append(name)
    return manual


def _write(inst, item, S, skip=None):
    """Записать параметры плана (кроме skip), ключ с подписью и маркер."""
    skip = set(skip or [])
    failed = [n for n, v, k in item['params'] if n not in skip and not _set(inst, n, v, k)]
    kp = inst.LookupParameter(KEY_PARAM)
    if kp is not None and not kp.IsReadOnly:
        kp.Set(u'%s#%s' % (item['key'], _signature(item['params'])))
    cp = inst.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    if cp and not cp.IsReadOnly:
        cp.Set(S['marker_comment'])
    if failed:
        FAILED_PARAMS.setdefault(item['fam'], set()).update(failed)


def _geom_center(inst, view):
    """Центр контура (по кривым геометрии экземпляра на виде), мм. None, если кривых нет."""
    try:
        opt = Options()
        opt.View = view
        geo = inst.get_Geometry(opt)
    except Exception:
        return None
    xs, ys = [], []

    def walk(g):
        for o in g:
            if isinstance(o, GeometryInstance):
                walk(o.GetInstanceGeometry())
            elif isinstance(o, Curve):
                for q in (o.GetEndPoint(0), o.GetEndPoint(1)):
                    xs.append(q.X * MM)
                    ys.append(q.Y * MM)
    if geo is None:
        return None
    walk(geo)
    if not xs:
        return None
    return ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)


def _center_on(doc, view, inst, item):
    """Для элементов с center=True: сдвинуть так, чтобы центр контура лёг в origin."""
    doc.Regenerate()
    cur = _geom_center(inst, view)
    if cur is None:
        return False
    dx = item['origin'][0] - cur[0]
    dy = item['origin'][1] - cur[1]
    if abs(dx) > 1.0 or abs(dy) > 1.0:
        ElementTransformUtils.MoveElement(doc, inst.Id, XYZ(dx / MM, dy / MM, 0.0))
        return True
    return False


def _create(doc, view, symbol, item, S):
    if not symbol.IsActive:
        symbol.Activate()
    o = item['origin']
    pt = XYZ(o[0] / MM, o[1] / MM, 0.0)
    inst = doc.Create.NewFamilyInstance(pt, symbol, view)
    ang = math.atan2(item['ex'][1], item['ex'][0])
    if abs(ang) > 1e-6:
        axis = Line.CreateBound(pt, XYZ(pt.X, pt.Y, pt.Z + 1.0))
        ElementTransformUtils.RotateElement(doc, inst.Id, axis, ang)
    _write(inst, item, S)
    if item.get('center'):
        _center_on(doc, view, inst, item)
    return inst


def _corner_family_is_wide(doc, view, symbol, plan, S):
    """Есть ли в угловом семействе параметры ширины ветви (проверка на временном экземпляре)."""
    names = [v for v in (S.get('corner_wing_width_params') or {}).values() if v]
    first = None
    for i in plan:
        if i.get('fam') == 'corner':
            first = i
            break
    if symbol is None or first is None or not names:
        return False
    if not symbol.IsActive:
        symbol.Activate()
    o = first['origin']
    inst = doc.Create.NewFamilyInstance(XYZ(o[0] / MM, o[1] / MM, 0.0), symbol, view)
    try:
        ok = all(inst.LookupParameter(n) is not None for n in names)
    finally:
        doc.Delete(inst.Id)
    return ok


def apply_plan(doc, view, syms, plan, S, mode, log=None):
    """mode: 'update' — сверить и поправить, 'recreate' — снести своё и поставить заново.
    Возвращает (instances, counts)."""
    counts = dict(created=0, recreated=0, updated=0, kept=0, manual=0, deleted=0, moved=0)
    del _STIRRUP_BOXES[:]
    existing, orphans = existing_by_key(doc, view, S)
    if _corner_family_is_wide(doc, view, syms.get('corner'), plan, S):
        # семейство само умеет ветви своей ширины: отдельные ветви-заплатки не нужны
        plan = [i for i in plan if not i.get('cw_fallback')]
        for i in plan:
            if i.get('params_wide'):
                i['params'] = i['params_wide']
                i['bars'] = i.get('bars_wide') or i.get('bars')
        if log:
            log.processed(u'corner family', u'legs with own width — via family parameters')
    _group_for_tags(plan, S)
    frozen = frozen_prefixes(S)
    held = {}                                    # элементы снятых этапов: не ставим, не правим, не удаляем
    if frozen:
        held = dict((k, fi) for k, fi in existing.items() if _key_prefix(k) in frozen)
        existing = dict((k, fi) for k, fi in existing.items() if k not in held)
        orphans = []
    counts['held'] = len(held)
    policy = S.get('update_policy', 'keep_manual')

    if mode == 'recreate':
        ids = List[ElementId]()
        for fi in list(existing.values()) + orphans:
            ids.Add(fi.Id)
        if ids.Count:
            doc.Delete(ids)
            counts['deleted'] = ids.Count
        existing = {}
        orphans = []

    instances = []
    seen = set()
    for item in plan:
        seen.add(item['key'])
        if (item['fam'] in ('stirrup', 'hairpin') and item.get('layout')
                and syms.get(item['fam']) is not None):
            _stirrup_origin(doc, view, syms[item['fam']], item, S)   # детерминированно
        if _key_prefix(item['key']) in frozen:
            if item['key'] in held:              # стоит с прошлого прогона — отдаём только под теги
                item['_held'] = True               # этап снят: параметры не дописываем
                instances.append((held[item['key']], item))
                txt = S_get(item, 'Rebar_Quantity Text')
                if S.get('place_tags') and txt is not None:
                    qp = held[item['key']].LookupParameter('Rebar_Quantity Text')
                    if qp is not None and not qp.IsReadOnly and (qp.AsString() or u'') != txt:
                        qp.Set(txt)              # единственное, что этап «теги» пишет в чужой элемент
            continue
        inst = existing.get(item['key'])
        if inst is None:
            inst = _create(doc, view, syms[item['fam']], item, S)
            counts['created'] += 1
            if log:
                log.processed(item['label'], u'created')
        else:
            # семейство совпадает?
            fam_now = _name(inst.Symbol.Family)
            why = None
            if fam_now != S['families'][item['fam']]:
                why = u'different family'
            elif policy == 'keep_manual':
                # геометрия: положение и «фигурные» параметры
                if _needs(inst, item['params'], only=SHAPE_PARAMS):
                    why = u'geometry changed (%s)' % u', '.join(
                        _needs(inst, item['params'], only=SHAPE_PARAMS))
                else:
                    o = item['origin']
                    if item.get('center'):
                        cur = _geom_center(inst, view)
                    else:
                        lp = inst.Location.Point
                        cur = (lp.X * MM, lp.Y * MM)
                    if cur is None:
                        why = u'no geometry'
                    else:
                        dx, dy = o[0] - cur[0], o[1] - cur[1]
                        dist = math.sqrt(dx * dx + dy * dy)
                        tol = S.get('recreate_move_tol_mm', 20)
                        if dist > tol:
                            why = u'wall moved (%.0f mm)' % dist
                        elif dist > 1.0:
                            # мелкий сдвиг: просто подвинуть, правки сохранить
                            ElementTransformUtils.MoveElement(doc, inst.Id, XYZ(dx / MM, dy / MM, 0.0))
                            counts['moved'] += 1
            if why is not None:
                doc.Delete(inst.Id)
                inst = _create(doc, view, syms[item['fam']], item, S)
                counts['recreated'] += 1
                if log:
                    log.processed(item['label'], u'recreated: ' + why)
            elif policy == 'keep_manual':
                manual = _manual_edits(inst, item)
                item['_manual'] = manual
                diff = [n for n in _needs(inst, item['params']) if n not in manual]
                if diff or manual:
                    _write(inst, item, S, skip=manual)    # подпись обновляется всегда
                if manual:
                    counts['manual'] += 1
                    if log:
                        log.processed(item['label'], u'manual edits kept: ' + u', '.join(manual)
                                      + (u'; updated: ' + u', '.join(diff) if diff else u''))
                elif diff:
                    counts['updated'] += 1
                    if log:
                        log.processed(item['label'], u'updated: ' + u', '.join(diff))
                else:
                    counts['kept'] += 1
            else:
                # overwrite — как в v0.4
                diff = _needs(inst, item['params'])
                if diff:
                    _write(inst, item, S)
                if item.get('center'):
                    moved = _center_on(doc, view, inst, item)
                else:
                    o = item['origin']
                    loc = inst.Location
                    dx = (o[0] / MM - loc.Point.X) * MM
                    dy = (o[1] / MM - loc.Point.Y) * MM
                    moved = abs(dx) > 1.0 or abs(dy) > 1.0
                    if moved:
                        ElementTransformUtils.MoveElement(
                            doc, inst.Id, XYZ(dx / MM, dy / MM, 0.0))
                if moved:
                    counts['moved'] += 1
                if diff:
                    counts['updated'] += 1
                    if log:
                        log.processed(item['label'], u'updated: ' + u', '.join(diff))
                else:
                    counts['kept'] += 1
        instances.append((inst, item))

    if mode == 'update':
        ids = List[ElementId]()
        for k, fi in existing.items():
            if k not in seen:
                ids.Add(fi.Id)
                if log:
                    log.processed(u'key %s' % k, u'deleted: no longer needed')
        for fi in orphans:
            ids.Add(fi.Id)
        if ids.Count:
            doc.Delete(ids)
            counts['deleted'] += ids.Count

    doc.Regenerate()     # точки вставки новых экземпляров валидны только после регенерации
    # Формулы семейства могут перебить записанное значение при общей регенерации (Shape 21:
    # Rebar_Diameter возвращался к 20, если вместе с ним менялись A / B / D — 06.10.2026).
    # Сверяем с планом и дописываем отличия; ручные правки и снятые этапы не трогаем.
    for _pass in range(2):
        fixed = 0
        for inst, item in instances:
            if item.get('_held'):
                continue
            keep = set(item.get('_manual') or [])
            diff = [n for n in _needs(inst, item['params']) if n not in keep]
            if not diff:
                continue
            _write(inst, item, S, skip=[n for n, v, k in item['params'] if n not in diff])
            fixed += 1
        if not fixed:
            break
        doc.Regenerate()
        if log:
            log.processed(u'parameters', u're-written after regeneration on %d element(s)' % fixed)
    if log:
        for fam, names in FAILED_PARAMS.items():
            log.error(fam, u'parameters not written: ' + u', '.join(sorted(names)))
    return instances, counts


# ----------------------------------------------------------------------
# теги
# ----------------------------------------------------------------------
def tag_symbols(doc):
    """[(семейство, тип, FamilySymbol)] всех тегов детальных элементов."""
    out = []
    for sym in FilteredElementCollector(doc).OfClass(FamilySymbol):
        try:
            cat = sym.Family.FamilyCategory
            if cat and cat.Name in (u'Detail Item Tags', u'Generic Annotations'):
                out.append((_name(sym.Family), _name(sym), sym))
        except Exception:
            continue
    return out


def _norm(s):
    return u' '.join((s or u'').split()).lower()


def tag_symbol_for(doc, fam_name, type_name, all_syms=None):
    """Тег по имени семейства и типа: точное имя типа -> по вхождению -> первый тип семейства."""
    syms = all_syms if all_syms is not None else tag_symbols(doc)
    mine = [(t, sym) for f, t, sym in syms if f == fam_name]
    if not mine:
        return None
    want = _norm(type_name)
    if want:
        for t, sym in mine:
            if _norm(t) == want:
                return sym
        for t, sym in mine:
            if want in _norm(t):
                return sym
    return mine[0][1]


def tag_symbols_by_role(doc, S, log=None):
    """{роль: FamilySymbol} по S['tags']; роль без своего тега берёт default."""
    all_syms = tag_symbols(doc)
    roles = S.get('tags') or {}
    if not roles:   # совместимость со старым пресетом
        roles = {'default': [S.get('tag_family'), S.get('tag_type')]}
    out = {}
    for role, pair in roles.items():
        fam_name, type_name = (list(pair) + [u''])[:2]
        sym = tag_symbol_for(doc, fam_name, type_name, all_syms)
        if sym is None:
            if log:
                log.error(u'Tag %s' % role, u'family "%s" not found; available: %s' % (
                    fam_name, u'; '.join(sorted(set(f for f, _, _ in all_syms)))))
            continue
        if not sym.IsActive:
            sym.Activate()
        out[role] = sym
        if log:
            log.processed(u'Tag %s' % role, u'%s : %s' % (_name(sym.Family), _name(sym)))
    return out


def find_tag_symbol(doc, S, notes=None):
    """Совместимость: тег роли default."""
    return tag_symbols_by_role(doc, S).get('default')


def detail_item_families(doc):
    """Имена семейств категории Detail Items — для выпадающих списков окна."""
    out = []
    for fam in FilteredElementCollector(doc).OfClass(Family):
        cat = fam.FamilyCategory
        if cat and cat.Name == u'Detail Items':
            n = _name(fam)
            if n not in out:
                out.append(n)
    return sorted(out)


def count_existing(doc, view, S):
    ex, orph = existing_by_key(doc, view, S)
    return len(ex) + len(orph)


def tag_families(doc):
    """Имена семейств, годных в теги детальных элементов."""
    out = []
    for fam in FilteredElementCollector(doc).OfClass(Family):
        cat = fam.FamilyCategory
        if cat and cat.Name in (u'Detail Item Tags', u'Generic Annotations'):
            n = _name(fam)
            if n not in out:
                out.append(n)
    return sorted(out)


def tags_by_host(doc, view):
    """{id элемента: тег} для всех тегов вида."""
    out = {}
    for t in FilteredElementCollector(doc, view.Id).OfClass(IndependentTag):
        try:
            for eid in t.GetTaggedLocalElementIds():
                out[eid.IntegerValue] = t
        except Exception:
            try:
                out[t.TaggedLocalElementId.IntegerValue] = t
            except Exception:
                pass
    return out


def tagged_ids(doc, view):
    return set(tags_by_host(doc, view).keys())


def _make_tag(doc, view, sym, elem, pt, leader):
    """Создаёт тег. ВНИМАНИЕ: без выноски Revit точку pt игнорирует и кладёт тело тега
    на хост, а повторная запись той же TagHeadPosition ничего не двигает (проверено
    19.09.2026). Поэтому окончательное место выставляет _settle_tags после Regenerate."""
    try:
        tag = IndependentTag.Create(doc, sym.Id, view.Id, Reference(elem), leader,
                                    TagOrientation.Horizontal, pt)
    except Exception:
        tag = IndependentTag.Create(doc, view.Id, Reference(elem), leader,
                                    TagMode.TM_ADDBY_CATEGORY, TagOrientation.Horizontal, pt)
        tag.ChangeTypeId(sym.Id)
    return tag


def _settle_tags(doc, queue):
    """queue: [(тег, (x, y) головки в мм)]. Двигает головку в два приёма с регенерацией —
    только так тело тега без выноски реально встаёт в заданное место."""
    if not queue:
        return
    doc.Regenerate()
    for tag, pt in queue:
        try:
            tag.TagHeadPosition = XYZ(pt[0] / MM + 3.0, pt[1] / MM + 3.0, 0.0)
        except Exception:
            pass
    doc.Regenerate()
    for tag, pt in queue:
        try:
            tag.TagHeadPosition = XYZ(pt[0] / MM, pt[1] / MM, 0.0)
        except Exception:
            pass
    doc.Regenerate()


def _pier_tag_targets(doc, inst, item, off):
    """Семейство простенка: два тега на краевые группы и один на внутренний ряд.
    Вложенные общие семейства — самостоятельные элементы (SubComponents).
    off — расстояние от ОСИ стены наружу (item['out'])."""
    ex = item['ex']
    u = (ex[1], -ex[0])                              # вдоль простенка (локальный -Y семейства)
    out = item.get('out') or ex
    prm = dict((n, v) for n, v, k in item['params'])
    L = prm.get('Length', 0.0)
    t = prm.get('Width', 0.0)
    P = (item['origin'][0] + ex[0] * t / 2.0, item['origin'][1] + ex[1] * t / 2.0)  # ось у торца s0
    es = inst.LookupParameter('Edge_Spacing')
    es_v = es.AsDouble() if es is not None else None
    show = inst.LookupParameter('Inner_Show')
    inner_visible = (show.AsInteger() == 1) if show is not None else True
    targets = []
    try:
        sub_ids = list(inst.GetSubComponentIds())
    except Exception:
        sub_ids = []
    for sid in sub_ids:
        sub = doc.GetElement(sid)
        if not isinstance(sub, FamilyInstance):
            continue
        sp = sub.LookupParameter('Rebar_Spacing')
        sp_v = sp.AsDouble() if sp is not None else None
        is_inner = es_v is not None and sp_v is not None and abs(sp_v - es_v) * MM > 1.0
        if is_inner:
            if not inner_visible:
                continue
            d = L / 2.0
        else:
            loc = sub.Location.Point
            d = (loc.X * MM - P[0]) * u[0] + (loc.Y * MM - P[1]) * u[1]
            d = max(0.0, min(L, d))
            d = d + (150.0 if d < L / 2.0 else -150.0)      # чуть внутрь от торца
        pt = ((P[0] + u[0] * d + out[0] * off), (P[1] + u[1] * d + out[1] * off))
        targets.append((sub, pt))
    return targets


def _tag_dims(S):
    """(ширина, высота тела тега, смещение центра тела от головки dx, dy), мм при масштабе вида.
    Замерено на «Detail items_Tag Rebar» при 1:50: тело ~780..890 x 295, центр выше головки на ~150."""
    return (float(S.get('tag_w_mm', 900)), float(S.get('tag_h_mm', 300)),
            float(S.get('tag_body_dx_mm', 40)), float(S.get('tag_body_dy_mm', 150)))


def _tag_rect(center, S):
    w, h, dx, dy = _tag_dims(S)
    return (center[0] - w / 2.0, center[1] - h / 2.0, center[0] + w / 2.0, center[1] + h / 2.0)


def _tag_is_stuck(tag, view, S):
    """Тело тега лежит не там, где головка (тег остался на хосте после создания)."""
    try:
        if tag.HasLeader:                         # с выноской габарит включает линию — судить нельзя;
            return False                          # такие теги уже прошли постановку, не трогаем
        bb = tag.get_BoundingBox(view)
        h = tag.TagHeadPosition
    except Exception:
        return False
    if bb is None:
        return False
    w, hh, dx, dy = _tag_dims(S)
    cx = (bb.Min.X + bb.Max.X) / 2.0 * MM
    cy = (bb.Min.Y + bb.Max.Y) / 2.0 * MM
    return math.hypot(cx - (h.X * MM + dx), cy - (h.Y * MM + dy)) > 250.0


def _tag_is_far(doc, tag, host_id, view, S):
    """Тег нашего элемента стоит дальше допустимого от хоста (раскладка v0.9 первой
    редакции уводила теги на 2-4 м). Такие переставляем заново."""
    try:
        host = doc.GetElement(ElementId(host_id))
        cp = host.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        if cp is None or cp.AsString() != S['marker_comment']:
            return False
        hb = host.get_BoundingBox(view)
        hp = tag.TagHeadPosition                  # по головке, а не по габариту: с выноской габарит другой
    except Exception:
        return False
    if hb is None:
        return False
    dx = hp.X * MM - (hb.Min.X + hb.Max.X) / 2.0 * MM
    dy = hp.Y * MM - (hb.Min.Y + hb.Max.Y) / 2.0 * MM
    return math.hypot(dx, dy) > float(S.get('tag_max_shift_mm', 1200)) + 1000.0


def _existing_tag_rects(doc, view, skip_ids=None):
    """Прямоугольники тел тегов, уже стоящих на виде (мм)."""
    rects = []
    skip_ids = skip_ids or set()
    for tg in FilteredElementCollector(doc, view.Id).OfClass(IndependentTag):
        if tg.Id.IntegerValue in skip_ids:
            continue
        try:
            bb = tg.get_BoundingBox(view)
        except Exception:
            bb = None
        if bb is not None:
            rects.append((bb.Min.X * MM, bb.Min.Y * MM, bb.Max.X * MM, bb.Max.Y * MM))
    return rects


def _free_spot(center, along, out, occupied, axes, S, reach=None):
    """Центр тела тега: БЛИЖАЙШЕЕ к расчётному свободное место, где прямоугольник тега
    не задевает стены, выноски хомутов и другие теги. Тег без выноски, поэтому дальше
    tag_max_shift_mm от расчётного места он не уходит — иначе непонятно, чей он.
    reach — расстояние от расчётного места до зеркального по другую сторону стены
    (None — вторую сторону не пробовать)."""
    step = float(S.get('tag_shift_step_mm', 400)) / 2.0
    gap = float(S.get('tag_gap_mm', 50))
    lim = float(S.get('tag_max_shift_mm', 1200))

    def clear(c):
        r = _tag_rect(c, S)
        for o in occupied:
            if core.rects_overlap(r, o, gap):
                return False
        return not core.rect_hits_walls(r, axes, gap)

    if clear(center):
        return center
    n = int(lim / step)
    cands = []
    for i in range(-n, n + 1):
        for j in range(0, n + 1):
            da, do = i * step, j * step
            cost = math.hypot(da, do * 1.5)              # наружу дороже, чем вдоль
            if cost <= lim:
                cands.append((cost, da, do))
            if reach:                                     # другая сторона стены — со штрафом
                cost2 = math.hypot(da, do * 1.5) + 500.0
                if cost2 <= lim + 500.0:
                    cands.append((cost2, da, -(reach + do)))
    cands.sort()
    for cost, da, do in cands:
        q = (center[0] + along[0] * da + out[0] * do,
             center[1] + along[1] * da + out[1] * do)
        if clear(q):
            return q
    return center


def _stirrup_tag_below(item, S):
    """Хомут-деталь у стены, вертикальной в плане, подписывается снизу."""
    ex = item.get('wall_u') or item.get('ex') or (1.0, 0.0)
    return (item.get('fam') in ('stirrup', 'hairpin') and S.get('stirrup_tag_below_vertical', True)
            and abs(ex[1]) > abs(ex[0]))


def _tag_anchor(inst, item, view, S):
    """Желаемый ЦЕНТР тела тега (мм): от элемента наружу от стены так, чтобы весь
    прямоугольник тега был за гранью стены с зазором tag_offset_mm."""
    off = float(S.get('tag_offset_mm', 150))
    w, h, dx, dy = _tag_dims(S)
    fam = item.get('fam')
    out = item.get('out') or _perp(item['ex'])
    ext = abs(out[0]) * w / 2.0 + abs(out[1]) * h / 2.0     # полразмера тега вдоль out
    prm = dict((n, v) for n, v, k in item['params'])
    if fam in ('stirrup', 'hairpin'):
        c = item['origin']
        half = float(item.get('half_across', 0.0))
        off = float(S.get('stirrup_tag_offset_mm', 150))
        if _stirrup_tag_below(item, S):
            # стена вертикальна в плане: тег не сбоку, а СНИЗУ выноски (пользователь, 21.09)
            out = (0.0, -1.0)
            ext = h / 2.0
            half = float(item.get('half_along', 0.0)) or half
    elif item.get('tag_role') == 'group' and item.get('tag_bars'):
        # группа: от центра габарита ВСЕХ её стержней наружу, за самый дальний стержень и грань стены
        xs = [q[0] for q in item['tag_bars']]
        ys = [q[1] for q in item['tag_bars']]
        c = ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)
        half = (abs(out[0]) * (max(xs) - min(xs)) + abs(out[1]) * (max(ys) - min(ys))) / 2.0 \
            + S['cover_cm'] * 10.0
    elif fam == 'corner':
        c = item.get('node_p') or item['origin']
        half = max(prm.get('b', 0.0), prm.get('h', 0.0)) / 2.0
    else:
        c = _geom_center(inst, view)
        if c is None:
            lp = inst.Location.Point
            c = (lp.X * MM, lp.Y * MM)
        half = prm.get('h', 0.0) / 2.0
    d = half + off + ext
    item['_tag_reach'] = 2.0 * d if fam not in ('stirrup', 'hairpin') else None
    return (c[0] + out[0] * d, c[1] + out[1] * d)


def place_tags(doc, view, instances, S, log=None, walls=None):
    """Тег на каждый поставленный элемент (кроме no_tag — вошедших в группу соседа).
    Уже стоящий тег не двигаем, кроме «залипших» на хосте и улетевших; тип тега приводим к нужному.
    Группа (tag_role = group) получает тег «Text Quantity» с суммой стержней.
    Вариант А (tag_two_sticks): от тега две «палочки» — родная выноска на первый стержень и линия
    детализации на последний (по диагонали). Линии перерисовываются при каждом прогоне этапа
    по ТЕКУЩЕМУ положению тега, поэтому ручной сдвиг тега учитывается после повторного запуска."""
    if not S.get('place_tags'):
        return 0
    roles = tag_symbols_by_role(doc, S, log)
    sym = roles.get('default')
    if sym is None:
        return 0
    have = tags_by_host(doc, view)
    # элементы, вошедшие в чужую группу: свой тег им больше не нужен
    dead = List[ElementId]()
    for inst, item in instances:
        if item.get('no_tag') and inst.Id.IntegerValue in have:
            dead.Add(have.pop(inst.Id.IntegerValue).Id)
    if dead.Count:
        doc.Delete(dead)
        doc.Regenerate()
    stuck = dict((eid, t) for eid, t in have.items()
                 if _tag_is_stuck(t, view, S) or _tag_is_far(doc, t, eid, view, S))
    occupied = _existing_tag_rects(doc, view, skip_ids=set(t.Id.IntegerValue for t in stuck.values()))
    occupied.extend(_STIRRUP_BOXES)
    axes = [core.Axis(w['p0'], w['p1'], w['t']) for w in (walls or [])]
    w_, h_, dx, dy = _tag_dims(S)
    off = float(S.get('tag_offset_mm', 150))
    queue = []
    sticks = []                                   # (тег, элемент плана) — кому рисовать палочки
    n = 0
    for inst, item in instances:
        if item.get('no_tag'):
            continue
        use_sym = roles.get(item.get('tag_role') or item.get('fam'), sym)
        out = item.get('out') or _perp(item['ex'])
        if item.get('fam') == 'pier' and S.get('pier_tags', True):
            prm = dict((nm, v) for nm, v, k in item['params'])
            ext = abs(out[0]) * w_ / 2.0 + abs(out[1]) * h_ / 2.0
            targets = _pier_tag_targets(doc, inst, item, prm.get('Width', 0.0) / 2.0 + off + ext)
            along = (item['ex'][1], -item['ex'][0])
        else:
            targets = [(inst, _tag_anchor(inst, item, view, S))]
            along = (item.get('wall_u') or item['ex']) if item.get('fam') != 'corner' else _perp(out)
            if _stirrup_tag_below(item, S):
                out, along = (0.0, -1.0), (1.0, 0.0)
        for elem, c in targets:
            eid = elem.Id.IntegerValue
            if eid in have and eid not in stuck and _stirrup_tag_below(item, S):
                # старый тег хомута стоит сбоку, а должен снизу — переставить
                try:
                    if have[eid].TagHeadPosition.Y * MM > item['origin'][1] - float(item.get('half_along', 0.0)):
                        stuck[eid] = have[eid]
                except Exception:
                    pass
            if eid in have and eid not in stuck:
                tag = have[eid]
                try:
                    if tag.GetTypeId() != use_sym.Id:
                        tag.ChangeTypeId(use_sym.Id)
                except Exception:
                    pass
                if elem is inst and item.get('tag_bars'):
                    sticks.append((tag, item))
                continue
            c = _free_spot(c, along, out, occupied, axes, S, reach=item.get('_tag_reach'))
            head = (c[0] - dx, c[1] - dy)
            try:
                if eid in stuck:
                    tag = stuck[eid]
                    if tag.GetTypeId() != use_sym.Id:
                        tag.ChangeTypeId(use_sym.Id)
                    if tag.HasLeader:
                        tag.HasLeader = False     # переставляем как тег без выноски, палочки вернём ниже
                else:
                    tag = _make_tag(doc, view, use_sym, elem, XYZ(head[0] / MM, head[1] / MM, 0.0), False)
                    n += 1
                queue.append((tag, head))
                occupied.append(_tag_rect(c, S))
                if elem is inst and item.get('tag_bars'):
                    sticks.append((tag, item))
            except Exception as ex_:
                if log:
                    log.error(u'Tag for %d' % eid, unicode(ex_))
    _settle_tags(doc, queue)                    # линии к стержням — отдельный этап, см. draw_tag_lines
    if log and stuck:
        log.processed(u'tags', u'moved back (stuck on host / flown away): %d' % len(stuck))
    return n


def draw_tag_lines(doc, view, instances, S, log=None):
    """ЭТАП «линии тегов»: теги НЕ двигает. Для каждого своего тега, как он стоит СЕЙЧАС (в том числе
    после ручной правки), рисует две палочки — на первый и на последний стержень элемента / группы.
    Повторный запуск перерисовывает линии по новому положению тегов. -> число тегов с линиями"""
    have = tags_by_host(doc, view)
    pairs = []
    for inst, item in instances:
        if item.get('no_tag') or not item.get('tag_bars') or item.get('fam') in ('stirrup', 'pier', 'hairpin'):
            continue
        tag = have.get(inst.Id.IntegerValue)
        if tag is not None:
            pairs.append((tag, item))
    return _draw_sticks(doc, view, pairs, S, log)


def _clear_sticks(doc, view, tags, S):
    """Палочки выключены: убрать линии своего стиля и выноски у своих тегов (остались от прошлых прогонов)."""
    name = S.get('tag_stick_line_style', u'PR_WallRebar2D Tag')
    old = List[ElementId]()
    for ce in FilteredElementCollector(doc, view.Id).OfClass(CurveElement):
        try:
            if ce.LineStyle.Name == name:
                old.Add(ce.Id)
        except Exception:
            continue
    if old.Count:
        doc.Delete(old)
    w_, h_, dx, dy = _tag_dims(S)
    back = []
    for tag in tags:
        try:
            if tag.HasLeader:
                back.append((tag, tag.TagHeadPosition))
                tag.HasLeader = False
        except Exception:
            continue
    if back:
        doc.Regenerate()
        for tag, h in back:                       # снятие выноски может сдвинуть головку — возвращаем
            try:
                tag.TagHeadPosition = h
            except Exception:
                pass


def _draw_sticks(doc, view, pairs, S, log=None):
    """Две прямые линии из ОДНОЙ точки у края тега: на первый и на последний (по диагонали) стержень
    элемента / группы. Родная выноска тега не используется (она даёт излом и лишний отрезок) —
    если осталась от прошлых версий, снимается. Свои старые линии узнаются по концу, стоящему на
    стержне, удаляются и рисуются заново по ТЕКУЩЕМУ положению тега."""
    style, sub = _own_line_style(doc, S.get('tag_stick_line_style', u'PR_WallRebar2D Tag'),
                                 S.get('tag_stick_line_weight', 1))
    mine = set()
    for tag, item in pairs:
        for q in (item.get('tag_bars') or item.get('bars') or []):
            mine.add((int(round(q[0] / 10.0)), int(round(q[1] / 10.0))))

    def on_bar(pt):
        cx, cy = int(round(pt.X * MM / 10.0)), int(round(pt.Y * MM / 10.0))
        for ax_ in (cx - 1, cx, cx + 1):
            for ay_ in (cy - 1, cy, cy + 1):
                if (ax_, ay_) in mine:
                    return True
        return False

    old = List[ElementId]()
    for ce in FilteredElementCollector(doc, view.Id).OfClass(CurveElement):
        try:
            if ce.LineStyle.Id != style.Id:
                continue
            crv = ce.GeometryCurve
            if on_bar(crv.GetEndPoint(0)) or on_bar(crv.GetEndPoint(1)):
                old.Add(ce.Id)
        except Exception:
            continue
    if old.Count:
        doc.Delete(old)

    # родные выноски прошлых версий — снять, головку вернуть на место
    back = []
    for tag, item in pairs:
        try:
            if tag.HasLeader:
                back.append((tag, tag.TagHeadPosition))
                tag.HasLeader = False
        except Exception:
            continue
    if back:
        doc.Regenerate()
        for tag, h in back:
            try:
                tag.TagHeadPosition = h
            except Exception:
                pass
        doc.Regenerate()

    w_, h_, dx, dy = _tag_dims(S)
    pad = float(S.get('tag_stick_pad_mm', 30))
    zs = _view_plane_z(view)
    z_ok = [None]

    def line(p0, p1):
        if math.hypot(p0[0] - p1[0], p0[1] - p1[1]) < 5.0:
            return False
        for z in ([z_ok[0]] if z_ok[0] is not None else zs):
            try:
                dc = doc.Create.NewDetailCurve(view, Line.CreateBound(XYZ(p0[0] / MM, p0[1] / MM, z),
                                                                      XYZ(p1[0] / MM, p1[1] / MM, z)))
                dc.LineStyle = style
                z_ok[0] = z
                return True
            except Exception:
                continue
        return False

    done = 0
    for tag, item in pairs:
        pts = item.get('tag_bars') or item.get('bars')
        if not pts:
            continue
        try:
            h = tag.TagHeadPosition
        except Exception:
            continue
        c = (h.X * MM + dx, h.Y * MM + dy)        # центр тела тега
        a, b = _far_pair(pts) if len(pts) > 1 else (pts[0], pts[0])
        mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
        vx, vy = mid[0] - c[0], mid[1] - c[1]
        # общая точка — середина той стороны тела тега, которая смотрит на арматуру
        if abs(vy) >= abs(vx):
            P = (c[0], c[1] + (h_ / 2.0 + pad) * (1.0 if vy > 0 else -1.0))
        else:
            P = (c[0] + (w_ / 2.0 + pad) * (1.0 if vx > 0 else -1.0), c[1])
        ok = line(P, a)
        if math.hypot(a[0] - b[0], a[1] - b[1]) > 1.0:
            ok = line(P, b) or ok
        if ok:
            done += 1
        elif log:
            log.error(u'Tag lines %d' % tag.Id.IntegerValue, u'could not be drawn')
    return done


# ----------------------------------------------------------------------
# самоотчёт: что реально стоит на виде (для проверки без коннектора)
# ----------------------------------------------------------------------
_REPORT_PARAMS = ['Rebar_A', 'Rebar_B', 'Vis_Hook', 'Rebar_Vis Dims',
                  'Length', 'Width', 'Edge_Spacing', 'Rebar_Diameter Mesh', 'Inner_On',
                  'Inner_Qty', 'Inner_Spacing', 'Inner_Show',
                  'h', 'b', 'w', 'offset', 'Cover', 'Quantity x', 'Quantity y', 'Rebar_Spacing',
                  'Rebar_Diameter', 'Rebar_Number', 'Rebar_Quantity', 'Spacing 50',
                  'Wall_Top', 'Wall_Left', 'Wall_Bottom', 'Wall_Right',
                  'Vis_WallTop', 'Vis_WallLeft', 'Vis_WallBot', 'Vis_WallRight',
                  'Corner_Quantity b', 'Corner_Quantity h']


def report_placed(doc, view, S):
    """Список всех экземпляров с маркером на виде: положение, поворот, bbox, параметры (мм)."""
    marker = S['marker_comment']
    rows = []
    for fi in FilteredElementCollector(doc, view.Id).OfClass(FamilyInstance):
        p = fi.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        if not p or p.AsString() != marker:
            continue
        loc = fi.Location
        pt = loc.Point
        bb = fi.get_BoundingBox(view)
        row = {
            'id': fi.Id.IntegerValue,
            'family': fi.get_Parameter(BuiltInParameter.ELEM_FAMILY_PARAM).AsValueString(),
            'loc_mm': [round(pt.X * MM, 1), round(pt.Y * MM, 1)],
            'rot_deg': round(math.degrees(loc.Rotation), 2),
            'bbox_mm': [round(bb.Min.X * MM), round(bb.Min.Y * MM), round(bb.Max.X * MM), round(bb.Max.Y * MM)] if bb else None,
            'params': {},
        }
        for n in _REPORT_PARAMS:
            q = fi.LookupParameter(n)
            if q is None:
                continue
            if q.StorageType == StorageType.Double:
                row['params'][n] = round(q.AsDouble() * MM, 2) if _is_length(q) else round(q.AsDouble(), 3)
            elif q.StorageType == StorageType.Integer:
                row['params'][n] = q.AsInteger()
            else:
                row['params'][n] = q.AsString()
        rows.append(row)
    return rows


def _is_length(param):
    try:
        tid = param.Definition.GetDataType().TypeId.lower()
        return any(k in tid for k in ('length', 'spacing', 'diameter', 'bardiameter'))
    except Exception:
        return False


def write_report(rows, view, counts, dry, extra=None):
    """Пишет %TEMP%/peer_revit_logs/wallrebar2d_report.json. Возвращает путь."""
    from peer_log import _log_dir
    path = os.path.join(_log_dir(), 'wallrebar2d_report.json')
    data = {'view': view.Name, 'dry_run': bool(dry), 'counts': counts, 'instances': rows}
    if extra:
        data.update(extra)
    with codecs.open(path, 'w', 'utf-8') as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True))
    return path
