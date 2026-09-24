# -*- coding: utf-8 -*-
"""kz_dress — оформление разреза балки/простенка по стандарту (Р2, Р3). v2.

Изменения v2 (по фидбеку 04.09.2026, скрин 150_S4):
    * PR_RebarSection НЕ используется. Вместо него: точки KZ_Dot по граням,
      штрихи плитной арматуры KZ_RebarLine (семейства создаются автоматически,
      lib/kz_families.py).
    * Хомут/пешки Shape 52/21 ставятся ВНУТРЬ бетона (как в эталоне 140_S13),
      без дублей рядом — автонумерация листа считает каждый экземпляр.
    * Бетонная зона = балка + плита: если балка не свисает ниже плиты,
      хомут/пешки начинаются от НИЗА плиты (правило пользователя).
    * Кроп вида авторасширяется, чтобы вместить арматуру, теги и размеры.

Состав: углы 4Ø12 (corner(1)) в пересечении с плитой, торцевые 4Ø12 (2 Line),
хомут Shape 52 (зона <= 1 м) или встречные пешки Shape 21 (перехлёст 65Ø),
погонные точки по граням, штрихи арматуры плиты, теги, размер ширины +
вертикальная цепочка, отметка (символ OK / Spot Elevation).
"""

import math

from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, BuiltInParameter, ElementId,
    Transaction, XYZ, Line, Wall, LocationCurve, Options, Solid,
    GeometryInstance, PlanarFace, Reference, ReferenceArray,
    ElementTransformUtils, FamilySymbol, Element, DimensionType,
    SpotDimensionType, IndependentTag, TagOrientation, ViewSection,
)

from AutoSections.convert import mm, to_ft
from kz_sections import _slab_layers_at
from kz_families import ensure_families, find_symbol

FT_MM = 304.8

# ------------------------------------------------------------------ настройки
COVER_MM_DEFAULT = 25.0
STIRRUP_D_MM = 8.0
STIRRUP_S_MM = 200.0
CORNER_D_MM = 12.0
END_ZONE_MM = 150.0        # зона торцевой группы 2 Line
TWO_PIN_PART_MM = 500.0    # Р2.4: часть над плитой > 500 -> две пешки
TWO_PIN_H_MM = 1000.0      # Р2.4: зона > 1000 -> две пешки
DOT_STEP_MM = 200.0        # погонные точки по граням
DOT_EDGE_MM = 250.0        # отступ первой/последней точки от торцов зоны
SLAB_LINE_MM = 800.0       # длина штриха плитной арматуры от грани балки
DIM_OFFSET_PAPER_MM = 10.0 # Р3.2: отступ размерных линий, мм бумаги
CROP_PAD_PAPER_MM = 8.0    # запас кропа вокруг содержимого, мм бумаги
TAG_OFF_MM = 450.0         # вынос тега хомута вправо от грани
PROBE_MM = 350.0           # зонд плит: отступ за грань элемента

FAM_CORNER = u'PR_Reinforcement in corner (1)'
FAM_ENDS = u'PR_Reinforcement 2 Line Quantityrfa'
FAM_SH52 = u'PEER_Rebar_Shape 52'
FAM_SH21 = u'PEER_Rebar_Shape 21'
FAM_TAG = u'Detail items_Tag Rebar'
FAM_OK = u'PEER-Annotation- OK Elevation section symbol'
FAM_DOT = u'KZ_Dot'
FAM_LINE = u'KZ_RebarLine'
DIM_TYPE = u'PEER-Linear'
SPOT_TYPE = u'PEER-Elevation Section'


def lap_mm(d_mm):
    """Перехлёст 65Ø, округление вверх до 50 мм (Р2.4)."""
    return math.ceil(65.0 * d_mm / 50.0) * 50.0


def find_dim_type(doc, name):
    for dt in FilteredElementCollector(doc).OfClass(DimensionType):
        try:
            if Element.Name.GetValue(dt) == name:
                return dt
        except Exception:
            pass
    return None


def find_spot_type(doc, name):
    for st in FilteredElementCollector(doc).OfClass(SpotDimensionType):
        try:
            if Element.Name.GetValue(st) == name:
                return st
        except Exception:
            pass
    return None


def set_len(inst, pname, val_mm):
    p = inst.LookupParameter(pname)
    if p and not p.IsReadOnly:
        try:
            p.Set(to_ft(val_mm))
            return True
        except Exception:
            pass
    return False


def set_int(inst, pname, val):
    p = inst.LookupParameter(pname)
    if p and not p.IsReadOnly:
        try:
            p.Set(int(val))
            return True
        except Exception:
            pass
    return False


# ------------------------------------------------------------------ геометрия

def view_frame(view):
    """(origin, look, right). look = -ViewDirection (свойство — К зрителю)."""
    return view.Origin, view.ViewDirection.Negate(), view.RightDirection


def find_cut_element(doc, view):
    o, look, right = view_frame(view)
    n = look
    best, best_c, best_axis, best_d = None, None, None, 1e9
    cats = (BuiltInCategory.OST_StructuralFraming, BuiltInCategory.OST_Walls)
    for cat in cats:
        for el in (FilteredElementCollector(doc, view.Id).OfCategory(cat)
                   .WhereElementIsNotElementType().ToElements()):
            loc = el.Location
            if not isinstance(loc, LocationCurve):
                continue
            crv = loc.Curve
            p0, p1 = crv.GetEndPoint(0), crv.GetEndPoint(1)
            axis = XYZ(p1.X - p0.X, p1.Y - p0.Y, 0.0)
            if axis.GetLength() < 1e-9:
                continue
            axis = axis.Normalize()
            if abs(axis.DotProduct(n)) < 0.7:
                continue
            denom = (p1 - p0).DotProduct(n)
            if abs(denom) < 1e-9:
                continue
            t = (o - p0).DotProduct(n) / denom
            if t < -0.05 or t > 1.05:
                continue
            c = p0 + (p1 - p0) * t
            d = XYZ(c.X - o.X, c.Y - o.Y, 0.0).GetLength()
            if d < best_d:
                best, best_c, best_axis, best_d = el, c, axis, d
    return best, best_c, best_axis


def _bbox_cross_width(bb, axis):
    """Ширина bbox ПОПЕРЁК оси элемента (мм): проекция габарита на right."""
    right = XYZ.BasisZ.CrossProduct(axis).Normalize()
    return mm(abs((bb.Max.X - bb.Min.X) * right.X) +
              abs((bb.Max.Y - bb.Min.Y) * right.Y))


def concrete_zone(doc, elem, c, axis):
    """(b_mm, z_top, z_bot) бетона элемента (балка или перемычка стены).

    Ширина балки: сначала параметры типа/экземпляра ('B', 'Width',
    FAMILY_WIDTH_PARAM), затем сверка с поперечным габаритом bbox — если
    параметр врёт (шире фактического габарита), берём габарит. Ловушка:
    у PEER-балок «18/43+18/62» встроенного Width нет, а bbox по мировой X
    для балки вдоль X — это её ДЛИНА (баг «широких линий» 05.09.2026).
    """
    bb = elem.get_BoundingBox(None)
    if bb is None:
        return None, None, None
    z_top, z_bot = bb.Max.Z, bb.Min.Z
    if isinstance(elem, Wall):
        b = mm(elem.Width)
        try:
            inserts = elem.FindInserts(True, False, False, True)
        except Exception:
            inserts = []
        r = to_ft(600.0)
        for iid in inserts:
            ins = doc.GetElement(iid)
            if ins is None:
                continue
            ib = ins.get_BoundingBox(None)
            if ib is None:
                continue
            icx = (ib.Min.X + ib.Max.X) * 0.5
            icy = (ib.Min.Y + ib.Max.Y) * 0.5
            if abs(icx - c.X) < r and abs(icy - c.Y) < r and ib.Max.Z > z_bot:
                z_bot = ib.Max.Z
    else:
        w_bbox = _bbox_cross_width(bb, axis)
        b = None
        sym = doc.GetElement(elem.GetTypeId())
        cands = []
        for host in (sym, elem):
            if host is None:
                continue
            for pname in (u'B', u'b', u'Width', u'ширина'):
                p = host.LookupParameter(pname)
                if p and p.HasValue:
                    try:
                        v = mm(p.AsDouble())
                        if 30.0 < v < 2500.0:
                            cands.append(v)
                    except Exception:
                        pass
            p = host.get_Parameter(BuiltInParameter.FAMILY_WIDTH_PARAM)
            if p and p.HasValue:
                try:
                    v = mm(p.AsDouble())
                    if 30.0 < v < 2500.0:
                        cands.append(v)
                except Exception:
                    pass
        for v in cands:
            if v <= w_bbox * 1.2 + 20.0:   # параметр не шире факта
                b = v
                break
        if b is None:
            b = w_bbox if 30.0 < w_bbox < 2500.0 else (cands[0] if cands
                                                       else 300.0)
    return b, z_top, z_bot


def side_layers(doc, c, right, b_mm, z_top, z_bot):
    pad = to_ft(300.0)
    res = {}
    for label, sgn in ((u'right', 1.0), (u'left', -1.0)):
        layers = []
        for dist in (b_mm * 0.5 + PROBE_MM, b_mm * 0.5 + PROBE_MM + 350.0):
            pt = c + right * (to_ft(dist) * sgn)
            layers = _slab_layers_at(doc, pt.X, pt.Y, z_bot - pad, z_top + pad)
            if layers:
                break
        res[label] = layers
    return res[u'left'], res[u'right']


def main_slab(left, right_l):
    combined = list(left) + list(right_l)
    if not combined:
        return None
    return sorted(combined, key=lambda x: -x[1])[0]


# ------------------------------------------------------------------ оформление

class Dresser(object):
    def __init__(self, doc, view, cover_mm=COVER_MM_DEFAULT, typical=True,
                 dot_sym=None, line_sym=None):
        self.doc = doc
        self.view = view
        self.cover = cover_mm
        self.typical = typical
        self.dot_sym = dot_sym
        self.line_sym = line_sym
        self.warn = []
        self.placed = []
        # мировые экстенты содержимого для кропа
        self.ext = None

    def w(self, msg):
        self.warn.append(u'{}: {}'.format(self.view.Name, msg))

    def _grow(self, pt, pad_mm=0.0):
        """Расширить учитываемые экстенты содержимого точкой (мир)."""
        p = to_ft(pad_mm)
        lo = XYZ(pt.X - p, pt.Y - p, pt.Z - p)
        hi = XYZ(pt.X + p, pt.Y + p, pt.Z + p)
        if self.ext is None:
            self.ext = [lo, hi]
        else:
            a, b = self.ext
            self.ext = [XYZ(min(a.X, lo.X), min(a.Y, lo.Y), min(a.Z, lo.Z)),
                        XYZ(max(b.X, hi.X), max(b.Y, hi.Y), max(b.Z, hi.Z))]

    def _place(self, symbol, pt, label, grow_mm=200.0):
        if symbol is None:
            self.w(u'нет семейства для «{}»'.format(label))
            return None
        try:
            if not symbol.IsActive:
                symbol.Activate()
            inst = self.doc.Create.NewFamilyInstance(pt, symbol, self.view)
            self.placed.append(label)
            self._grow(pt, grow_mm)
            return inst
        except Exception as e:
            self.w(u'{}: {}'.format(label, e))
            return None

    def _rotate180(self, inst, pt):
        try:
            _o, look, _r = view_frame(self.view)
            axis = Line.CreateBound(pt, pt + look)
            ElementTransformUtils.RotateElement(self.doc, inst.Id, axis, math.pi)
        except Exception as e:
            self.w(u'поворот: {}'.format(e))

    # ------------------------------------------------------------------ main
    def dress(self):
        doc, view = self.doc, self.view
        elem, c, axis = find_cut_element(doc, view)
        if elem is None:
            self.w(u'не найден разрезаемый элемент')
            return False
        b, z_top, z_bot = concrete_zone(doc, elem, c, axis)
        if b is None or (z_top - z_bot) < to_ft(80.0):
            self.w(u'не удалось определить бетонную зону')
            return False
        o, look, right = view_frame(view)
        cvr = self.cover
        left_l, right_l = side_layers(doc, c, right, b, z_top, z_bot)
        slab = main_slab(left_l, right_l)
        s_top = slab[0] if slab is not None else None
        s_bot = (slab[0] - to_ft(slab[1])) if slab is not None else None

        # --- бетонная зона армирования: балка + плита (правило пользователя)
        hangs_below = (s_bot is not None) and (z_bot < s_bot - to_ft(100.0))
        if s_bot is not None and not hangs_below:
            zone_bot = min(z_bot, s_bot)     # от низа плиты
        else:
            zone_bot = z_bot
        zone_top = z_top
        zone_mm = mm(zone_top - zone_bot)

        self._grow(XYZ(c.X, c.Y, z_top) + right * to_ft(b * 0.5), 100.0)
        self._grow(XYZ(c.X, c.Y, zone_bot) - right * to_ft(b * 0.5), 100.0)

        # --- углы 4Ø12 в пересечении с плитой (Р2.1) ------------------------
        if slab is not None:
            pt = c - right * to_ft(b * 0.5)
            pt = XYZ(pt.X, pt.Y, s_top)
            inst = self._place(find_symbol(doc, FAM_CORNER), pt,
                               u'углы 4Ø12 (corner)')
            if inst is not None:
                set_len(inst, u'w', b)
                set_len(inst, u'h', slab[1])
                set_len(inst, u'Cover', cvr)
                set_len(inst, u'Rebar_Diameter', CORNER_D_MM)
                set_int(inst, u'Quantity w', 2)
                set_int(inst, u'Quantity h', 2)

        # --- торцевые группы 4Ø12 (Р2.1) ------------------------------------
        ends_sym = find_symbol(doc, FAM_ENDS)

        def place_end(z_edge, at_top):
            pt = c + right * to_ft(b * 0.5)
            pt = XYZ(pt.X, pt.Y, z_edge)
            inst = self._place(ends_sym, pt, u'торец 4Ø12 (2 Line)')
            if inst is None:
                return
            set_len(inst, u'h', b)
            set_len(inst, u'w', END_ZONE_MM)
            set_len(inst, u'Cover', cvr)
            set_len(inst, u'Rebar_Diameter', CORNER_D_MM)
            set_int(inst, u'Quantity x', 2)
            set_int(inst, u'Quantity y', 2)
            if not at_top:
                mid = XYZ(c.X, c.Y, z_edge + to_ft(END_ZONE_MM * 0.5))
                self._rotate180(inst, mid)

        top_free = (s_top is None) or (z_top > s_top + to_ft(100.0))
        if top_free:
            place_end(z_top, True)
        if hangs_below or slab is None:
            place_end(z_bot, False)

        # --- хомут / пешки Shape 52/21 В БЕТОНЕ (Р2.3, Р2.4) ----------------
        sh52 = find_symbol(doc, FAM_SH52)
        sh21 = find_symbol(doc, FAM_SH21)
        tag_sym = find_symbol(doc, FAM_TAG)
        lap = lap_mm(STIRRUP_D_MM)
        a_mm = b - 2.0 * cvr

        def tag_it(inst, z):
            if tag_sym is None or inst is None:
                return
            try:
                pt = c + right * to_ft(b * 0.5 + TAG_OFF_MM)
                pt = XYZ(pt.X, pt.Y, z)
                IndependentTag.Create(doc, tag_sym.Id, view.Id,
                                      Reference(inst), False,
                                      TagOrientation.Horizontal, pt)
                self._grow(pt, 350.0)
            except Exception as e:
                self.w(u'тег: {}'.format(e))

        def place_shape(sym, label, b2_mm, z_low, flip):
            """Вставка: правая грань минус cover, середина по высоте формы
            (конвенция эталона 140_S13); flip — форма открыта вниз."""
            z_mid = z_low + to_ft(b2_mm * 0.5)
            pt = c + right * to_ft(b * 0.5 - cvr)
            pt = XYZ(pt.X, pt.Y, z_mid)
            inst = self._place(sym, pt, label, grow_mm=b2_mm * 0.5 + 100.0)
            if inst is None:
                return None
            set_len(inst, u'Rebar_Diameter', STIRRUP_D_MM)
            set_len(inst, u'Rebar_Spacing', STIRRUP_S_MM)
            set_len(inst, u'Rebar_A', a_mm)
            set_len(inst, u'Rebar_B', b2_mm)
            if flip:
                self._rotate180(inst, XYZ(c.X, c.Y, z_mid))
            tag_it(inst, z_mid)
            return inst

        crosses = (s_bot is not None and hangs_below and
                   z_top > s_top + to_ft(100.0))
        if crosses:
            # часть ниже: от верха плиты вниз; часть выше: от низа плиты вверх
            part_dn = mm(s_top - z_bot)
            part_up = mm(z_top - s_bot)
            above = mm(z_top - s_top)
            b_dn = min(part_dn + lap, zone_mm - 2.0 * cvr)
            place_shape(sh21, u'пешка низ Shape 21', b_dn,
                        z_bot + to_ft(cvr), False)
            if above > TWO_PIN_PART_MM or part_up > TWO_PIN_H_MM:
                b_up = min(part_up + lap, zone_mm - 2.0 * cvr)
                place_shape(sh21, u'пешка верх Shape 21', b_up,
                            z_top - to_ft(cvr + b_up), True)
        else:
            if zone_mm <= TWO_PIN_H_MM:
                place_shape(sh52, u'хомут Shape 52', zone_mm - 2.0 * cvr,
                            zone_bot + to_ft(cvr), False)
            else:
                b2 = math.ceil((zone_mm + lap) / 2.0 / 50.0) * 50.0
                b2 = min(b2, zone_mm - 2.0 * cvr)
                place_shape(sh21, u'пешка низ Shape 21', b2,
                            zone_bot + to_ft(cvr), False)
                place_shape(sh21, u'пешка верх Shape 21', b2,
                            z_top - to_ft(cvr + b2), True)

        # --- погонные точки по граням (KZ_Dot) ------------------------------
        if self.dot_sym is not None:
            z0 = zone_bot + to_ft(DOT_EDGE_MM)
            z1 = zone_top - to_ft(DOT_EDGE_MM)
            n_dots = 0
            z = z0
            while z <= z1 + 1e-9 and n_dots < 60:
                for sgn in (1.0, -1.0):
                    pt = c + right * (to_ft(b * 0.5 - cvr) * sgn)
                    self._place(self.dot_sym, XYZ(pt.X, pt.Y, z),
                                u'точка', grow_mm=50.0)
                    n_dots += 1
                z += to_ft(DOT_STEP_MM)
            if n_dots:
                self.placed = [p for p in self.placed if p != u'точка']
                self.placed.append(u'точки x{}'.format(n_dots))
        else:
            self.w(u'KZ_Dot недоступен — погонные точки пропущены')

        # --- штрихи арматуры плиты (KZ_RebarLine) ---------------------------
        if self.line_sym is not None:
            for layers, sgn in ((right_l, 1.0), (left_l, -1.0)):
                if not layers:
                    continue
                topz, thk = layers[0]
                x0 = c + right * (to_ft(b * 0.5) * sgn)
                for zz in (topz - to_ft(cvr), topz - to_ft(thk) + to_ft(cvr)):
                    if sgn > 0:
                        pt = XYZ(x0.X, x0.Y, zz)
                    else:
                        pt = XYZ(x0.X, x0.Y, zz) - right * to_ft(SLAB_LINE_MM)
                    inst = self._place(self.line_sym, pt, u'штрих плиты',
                                       grow_mm=100.0)
                    if inst is not None:
                        set_len(inst, u'Length', SLAB_LINE_MM)
                        self._grow(pt + right * to_ft(SLAB_LINE_MM), 100.0)
            self.placed = ([p for p in self.placed if p != u'штрих плиты'] +
                           [u'штрихи плиты'])
        else:
            self.w(u'KZ_RebarLine недоступен — штрихи плиты пропущены')

        # --- размеры (Р3.1, Р3.2) -------------------------------------------
        self._dimensions(elem, c, right, b, z_top, zone_bot)

        # --- отметка (Р3.3) --------------------------------------------------
        self._elevation(elem, c, right, b, z_top)

        # --- кроп: вместить всё (правило пользователя) ----------------------
        self._fit_crop()
        return True

    # ------------------------------------------------------------- размеры
    def _faces(self, elem):
        opts = Options()
        opts.ComputeReferences = True
        opts.View = self.view
        faces = []
        geo = elem.get_Geometry(opts)
        if geo is None:
            return faces
        for obj in geo:
            solids = []
            if isinstance(obj, Solid):
                solids.append(obj)
            elif isinstance(obj, GeometryInstance):
                for o2 in obj.GetInstanceGeometry():
                    if isinstance(o2, Solid):
                        solids.append(o2)
            for s in solids:
                if s.Volume < 1e-9:
                    continue
                for f in s.Faces:
                    if isinstance(f, PlanarFace) and f.Reference is not None:
                        faces.append(f)
        return faces

    def _dimensions(self, elem, c, right, b_mm, z_top, z_bot):
        doc, view = self.doc, self.view
        dt = find_dim_type(doc, DIM_TYPE)
        off = to_ft(DIM_OFFSET_PAPER_MM * view.Scale)
        faces = self._faces(elem)
        vert = []
        for f in faces:
            if abs(f.FaceNormal.DotProduct(right)) > 0.7:
                vert.append((f.Origin.DotProduct(right), f))
        if len(vert) >= 2:
            vert.sort(key=lambda x: x[0])
            ra = ReferenceArray()
            ra.Append(vert[0][1].Reference)
            ra.Append(vert[-1][1].Reference)
            zl = z_bot - off
            p1 = XYZ(c.X, c.Y, zl) - right * to_ft(b_mm)
            p2 = XYZ(c.X, c.Y, zl) + right * to_ft(b_mm)
            try:
                d = doc.Create.NewDimension(view, Line.CreateBound(p1, p2), ra)
                if dt is not None and d is not None:
                    try:
                        d.ChangeTypeId(dt.Id)
                    except Exception:
                        pass
                self.placed.append(u'размер ширины')
                self._grow(XYZ(c.X, c.Y, zl - to_ft(150.0)), 100.0)
            except Exception as e:
                self.w(u'размер ширины: {}'.format(e))
        horiz = []
        for f in faces:
            if abs(f.FaceNormal.Z) > 0.7:
                horiz.append((f.Origin.Z, f))
        if len(horiz) >= 2:
            horiz.sort(key=lambda x: x[0])
            seen, ra = set(), ReferenceArray()
            for zf, f in horiz:
                key = int(round(zf * FT_MM / 5.0))
                if key in seen:
                    continue
                seen.add(key)
                ra.Append(f.Reference)
            if ra.Size >= 2:
                xl = c - right * (to_ft(b_mm * 0.5) + off)
                p1 = XYZ(xl.X, xl.Y, z_bot - to_ft(200.0))
                p2 = XYZ(xl.X, xl.Y, z_top + to_ft(200.0))
                try:
                    d = doc.Create.NewDimension(view, Line.CreateBound(p1, p2),
                                                ra)
                    if dt is not None and d is not None:
                        try:
                            d.ChangeTypeId(dt.Id)
                        except Exception:
                            pass
                    self.placed.append(u'вертикальная цепочка')
                    self._grow(XYZ(xl.X, xl.Y, z_top) -
                               right * to_ft(150.0), 100.0)
                except Exception as e:
                    self.w(u'вертикальная цепочка: {}'.format(e))

    # ------------------------------------------------------------- отметка
    def _elevation(self, elem, c, right, b_mm, z_top):
        doc, view = self.doc, self.view
        pt = XYZ(c.X, c.Y, z_top) + right * to_ft(b_mm * 0.5 + 300.0)
        pt = XYZ(pt.X, pt.Y, z_top + to_ft(250.0))
        if self.typical:
            sym = find_symbol(doc, FAM_OK)
            if sym is None:
                self.w(u'символ отметки «{}» не найден'.format(FAM_OK))
                return
            self._place(sym, pt, u'символ отметки OK', grow_mm=350.0)
        else:
            st = find_spot_type(doc, SPOT_TYPE)
            top_face = None
            for f in self._faces(elem):
                if f.FaceNormal.Z > 0.7:
                    if top_face is None or f.Origin.Z > top_face.Origin.Z:
                        top_face = f
            if top_face is None or st is None:
                self.w(u'Spot Elevation: нет верхней грани или типа')
                return
            try:
                fp = XYZ(c.X, c.Y, z_top)
                bend = fp + right * to_ft(300.0) + XYZ(0, 0, to_ft(200.0))
                end = bend + right * to_ft(200.0)
                spot = doc.Create.NewSpotElevation(
                    view, top_face.Reference, fp, bend, end, fp, True)
                if spot is not None:
                    try:
                        spot.ChangeTypeId(st.Id)
                    except Exception:
                        pass
                self.placed.append(u'Spot Elevation')
                self._grow(end, 300.0)
            except Exception as e:
                self.w(u'Spot Elevation: {}'.format(e))

    # ------------------------------------------------------------- кроп
    def _fit_crop(self):
        """Расширить кроп вида, чтобы всё размещённое попало в кадр."""
        if self.ext is None:
            return
        view = self.view
        try:
            cb = view.CropBox
            inv = cb.Transform.Inverse
            pad = to_ft(CROP_PAD_PAPER_MM * view.Scale)
            lo, hi = self.ext
            pts = [XYZ(lo.X, lo.Y, lo.Z), XYZ(hi.X, hi.Y, hi.Z),
                   XYZ(lo.X, hi.Y, lo.Z), XYZ(hi.X, lo.Y, hi.Z),
                   XYZ(lo.X, lo.Y, hi.Z), XYZ(hi.X, hi.Y, lo.Z)]
            mnx, mny = cb.Min.X, cb.Min.Y
            mxx, mxy = cb.Max.X, cb.Max.Y
            for p in pts:
                q = inv.OfPoint(p)
                mnx = min(mnx, q.X - pad)
                mny = min(mny, q.Y - pad)
                mxx = max(mxx, q.X + pad)
                mxy = max(mxy, q.Y + pad)
            cb.Min = XYZ(mnx, mny, cb.Min.Z)
            cb.Max = XYZ(mxx, mxy, cb.Max.Z)
            view.CropBox = cb
            self.placed.append(u'кроп расширен')
        except Exception as e:
            self.w(u'кроп: {}'.format(e))


def dress_views(doc, views, cover_mm, typical):
    """Оформить набор разрезов. Возвращает (done, warnings, placed)."""
    done, warns, placed = 0, [], []
    dot_sym, line_sym = ensure_families(doc, warns)
    t = Transaction(doc, u'KZ - армирование и размеры разрезов')
    t.Start()
    try:
        for v in views:
            dr = Dresser(doc, v, cover_mm, typical, dot_sym, line_sym)
            try:
                if dr.dress():
                    done += 1
            except Exception as e:
                warns.append(u'{}: СБОЙ {}'.format(v.Name, e))
            warns.extend(dr.warn)
            placed.append((v.Name, dr.placed))
        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise
    return done, warns, placed
