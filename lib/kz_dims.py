# -*- coding: utf-8 -*-
"""kz_dims — размеры и отметки перекрытия на разрезах (Р3, эталон 160B). v1.2

Состав на разрез (по ПДФ PRKL-ST-01-L03-1-160B):
    1. Слева — вертикальная цепочка по ГОРИЗОНТАЛЬНЫМ граням бетона узла
       (верх/низ элемента + грани прилегающих плит): 160/30, 1120/200/580.
    2. Внизу — ширина элемента (20, 20/50).
    3. У дальнего конца каждой прилегающей плиты — размер её толщины (22).
    4. Отметка ПЕРЕКРЫТИЯ: типовой этаж — символ «O.K.» на верху плиты;
       обычный — настоящий Spot Elevation (PEER-Elevation Section).

v1.2 (24.09.2026) — «не выходить за рамку»:
    * все отступы — в мм БУМАГИ (одинаково на 1:20 и 1:50);
    * размер толщины плиты и отметка ставятся от края КРОПА, внутрь;
    * цепочка при плите слева — за левым краем кропа (не сквозь бетон плиты),
      ширина — под локальным низом бетона (не под bbox всего перекрытия);
    * annotation crop расширяется ровно настолько, чтобы влезли размеры
      снаружи кропа; модельный кроп не меняется;
    * мелкие сегменты цепочки — текст разносится, чтобы не слипался;
    * после Regenerate — проверка габаритов, вылезшее сдвигается внутрь;
    * повторный запуск удаляет свои прежние размеры/отметки (ES на виде);
    * SubTransaction на вид: сбой разреза не оставляет его полуоформленным.

Переиспользует геометрию kz_dress (поиск разрезаемого элемента, стопка,
зонды плит). Regenerate — один на весь пакет.
"""

from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, BuiltInParameter, ElementId,
    Transaction, SubTransaction, XYZ, Line, Options, Solid, GeometryInstance,
    PlanarFace, ReferenceArray, Outline, BoundingBoxIntersectsFilter,
    ElementTransformUtils,
)
from Autodesk.Revit.DB.ExtensibleStorage import (
    Schema, SchemaBuilder, Entity, AccessLevel,
)
from System import Guid, String

import re

from AutoSections.convert import mm, to_ft
from kz_dress import (
    view_frame, find_cut_element, concrete_zone, side_layers, main_slab,
    find_symbol, find_dim_type, find_spot_type,
)
from kz_sections import INSULATION_MAX_MM
from kz_refbracket import dummy_of

FT_MM = 304.8

# ---------------------------------------------------------------- настройки
# все *_P — мм БУМАГИ (умножаются на масштаб вида)
DIM_OFF_P = 10.0          # отступ размерной линии от бетона
CHAIN_OUT_P = 8.0         # цепочка за левым краем кропа
SLABDIM_IN_P = 10.0       # размер толщины плиты: от края кропа внутрь
CROP_MARGIN_P = 3.0       # запас до рамки для всего, что внутри кропа
TEXT_H_P = 3.5            # высота текста размера (с запасом)
SMALL_SEG_P = 5.0         # сегмент короче — текст разносится
OK_OFF_P = 7.5            # символ O.K.: вправо от грани элемента
SPOT_ROOM_P = 30.0        # место под отметку Spot (лидер + текст)
SPOT_LEAD1_P = 6.0        # Spot: горизонтальный лидер до излома
SPOT_LEAD2_P = 5.0        # Spot: полка под текст

SLABDIM_MIN_MM = 300.0    # размер толщины плиты: желательный отступ от грани
SLABDIM_TIGHT_MM = 150.0  # ...минимальный (тесный кроп — ставим посередине)
SLABDIM_FALLBACK_MM = 700.0  # если кроп выключен
DEDUPE_MM = 5.0           # слипание близких граней в цепочке
TOL_Z_MM = 15.0           # допуск «грань на ожидаемой отметке»
PROBE_MM = 350.0          # зонд плиты за гранью элемента

DIM_TYPE = u'PEER-Linear'
SPOT_TYPE = u'PEER-Elevation Section'
FAM_OK = u'PEER-Annotation- OK Elevation section symbol'

SCHEMA_GUID = Guid('6b0f3c2e-8a51-4c7e-9d2a-5e1f0b7c4a91')
SCHEMA_NAME = u'PEER_KzDims'


# ---------------------------------------------------------- ES: свои элементы

def _schema():
    s = Schema.Lookup(SCHEMA_GUID)
    if s is not None:
        return s
    sb = SchemaBuilder(SCHEMA_GUID)
    sb.SetReadAccessLevel(AccessLevel.Public)
    sb.SetWriteAccessLevel(AccessLevel.Public)
    sb.SetSchemaName(SCHEMA_NAME)
    sb.AddSimpleField(u'Ids', String)
    return sb.Finish()


def _stored_ids(view):
    try:
        ent = view.GetEntity(_schema())
        if ent is None or not ent.IsValid():
            return []
        raw = ent.Get[String](u'Ids') or u''
        return [int(x) for x in raw.split(u',') if x.strip()]
    except Exception:
        return []


def _store_ids(view, ids):
    ent = Entity(_schema())
    ent.Set[String](u'Ids', u','.join(str(i) for i in ids))
    view.SetEntity(ent)


def _remove_previous(doc, view):
    """Удалить размеры/отметки, поставленные прошлым запуском в этом виде."""
    n = 0
    for i in _stored_ids(view):
        el = doc.GetElement(ElementId(i))
        if el is None:
            continue
        try:
            if el.OwnerViewId == view.Id:
                doc.Delete(el.Id)
                n += 1
        except Exception:
            pass
    return n


# ---------------------------------------------------------------- геометрия

class FaceInfo(object):
    """Снимок грани: после ЛЮБОЙ правки документа Face-объекты протухают
    (FaceNormal -> SEHException), поэтому нормаль/точку копируем сразу,
    а Project (_covers) зовём только до создания аннотаций."""
    __slots__ = ('n', 'o', 'ref', 'face')

    def __init__(self, f):
        n, o = f.FaceNormal, f.Origin
        self.n = XYZ(n.X, n.Y, n.Z)
        self.o = XYZ(o.X, o.Y, o.Z)
        self.ref = f.Reference
        self.face = f


def _faces(doc, view, elem):
    return [FaceInfo(f) for f in _solid_faces(doc, view, elem)]


def _solid_faces(doc, view, elem):
    """PlanarFace'ы элемента с валидными Reference в контексте вида."""
    opts = Options()
    opts.ComputeReferences = True
    opts.View = view
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


def _covers(fi, pt):
    """Грань накрывает точку (проекция попадает внутрь грани)."""
    try:
        return fi.face.Project(pt) is not None
    except Exception:
        return False


def _side_floor_elems(doc, c, right, b_mm, z_lo, z_hi):
    """Реальные элементы плит по сторонам (для граней/толщин): (left, right)."""
    res = {1.0: [], -1.0: []}
    for sgn in (1.0, -1.0):
        for dist in (b_mm * 0.5 + PROBE_MM, b_mm * 0.5 + 2 * PROBE_MM):
            pt = c + right * (to_ft(dist) * sgn)
            r = to_ft(150.0)
            ol = Outline(XYZ(pt.X - r, pt.Y - r, z_lo),
                         XYZ(pt.X + r, pt.Y + r, z_hi))
            found = []
            for fl in (FilteredElementCollector(doc)
                       .OfCategory(BuiltInCategory.OST_Floors)
                       .WhereElementIsNotElementType()
                       .WherePasses(BoundingBoxIntersectsFilter(ol))):
                p = fl.get_Parameter(
                    BuiltInParameter.FLOOR_ATTR_THICKNESS_PARAM)
                thk = mm(p.AsDouble()) if p and p.HasValue else 0.0
                if thk > INSULATION_MAX_MM:
                    found.append(fl)
            if found:
                res[sgn] = found
                break
    return res[-1.0], res[1.0]


def _round5(v_mm):
    return round(v_mm / 5.0) * 5.0


class CropFrame(object):
    """Кроп вида в его координатах: u — вправо, v — вверх (футы модели)."""

    def __init__(self, view):
        self.view = view
        self.scale = float(view.Scale)
        cb = view.CropBox
        tr = cb.Transform
        self.inv = tr.Inverse
        self.right = tr.BasisX
        self.up = tr.BasisY
        self.active = bool(view.CropBoxActive)
        self.min_u, self.min_v = cb.Min.X, cb.Min.Y
        self.max_u, self.max_v = cb.Max.X, cb.Max.Y

    def p(self, paper_mm):
        """мм бумаги -> футы модели."""
        return to_ft(paper_mm * self.scale)

    def uv(self, pt):
        q = self.inv.OfPoint(pt)
        return q.X, q.Y

    def shift(self, pt, du=0.0, dv=0.0):
        return pt + self.right * du + self.up * dv

    def bbox_uv(self, el):
        bb = el.get_BoundingBox(self.view)
        if bb is None:
            return None
        us, vs = [], []
        for x in (bb.Min.X, bb.Max.X):
            for y in (bb.Min.Y, bb.Max.Y):
                for z in (bb.Min.Z, bb.Max.Z):
                    pt = XYZ(x, y, z)
                    if bb.Transform is not None:
                        pt = bb.Transform.OfPoint(pt)
                    u, v = self.uv(pt)
                    us.append(u)
                    vs.append(v)
        return min(us), min(vs), max(us), max(vs)

    def inside_delta(self, el, margin):
        """(du, dv), чтобы габарит el встал внутрь кропа с запасом."""
        box = self.bbox_uv(el)
        if box is None or not self.active:
            return 0.0, 0.0
        umin, vmin, umax, vmax = box
        du = dv = 0.0
        if umax > self.max_u - margin:
            du = (self.max_u - margin) - umax
        if umin + du < self.min_u + margin:
            du = (self.min_u + margin) - umin
        if vmax > self.max_v - margin:
            dv = (self.max_v - margin) - vmax
        if vmin + dv < self.min_v + margin:
            dv = (self.min_v + margin) - vmin
        return du, dv


# ------------------------------------------------------------------ разметка

class DimsMarker(object):
    def __init__(self, doc, view, typical=True, dim_type=None, spot_type=None,
                 ok_sym=None):
        self.doc = doc
        self.view = view
        self.typical = typical
        self.dim_type = dim_type
        self.spot_type = spot_type
        self.ok_sym = ok_sym
        self.warn = []
        self.placed = []
        self.created = []     # ElementId всего, что поставлено
        self.fit_in = []      # то, что обязано быть ВНУТРИ кропа
        self.chains = []      # размеры-цепочки для разноса текста
        self.anno_need = {}   # сторона -> нужный отступ annotation crop, мм бум.
        self.crop = None

    def w(self, msg):
        self.warn.append(u'{}: {}'.format(self.view.Name, msg))

    def _need_anno(self, side, paper_mm):
        if paper_mm > self.anno_need.get(side, 0.0):
            self.anno_need[side] = paper_mm

    def _new_dim(self, line, refs, label, below=None, inside=False,
                 chain_side=None):
        """Размер; below — текст «(22)» под размерной строкой (скобочный
        вариант из dummy, фидбек 05.09.2026)."""
        try:
            d = self.doc.Create.NewDimension(self.view, line, refs)
        except Exception as e:
            self.w(u'{}: {}'.format(label, e))
            return None
        if d is None:
            self.w(u'{}: not created'.format(label))
            return None
        if self.dim_type is not None:
            try:
                d.ChangeTypeId(self.dim_type.Id)
            except Exception:
                pass
        if below:
            try:
                if d.NumberOfSegments > 0:
                    for seg in d.Segments:
                        seg.Below = below
                        break
                else:
                    d.Below = below
            except Exception as e:
                self.w(u'{} (text below dimension): {}'.format(label, e))
        self.created.append(d.Id)
        if inside:
            self.fit_in.append((d.Id, label))
        if chain_side is not None:
            self.chains.append((d.Id, chain_side))
        self.placed.append(label + (u' +({})'.format(below) if below else u''))
        return d

    # ------------------------------------------------------------- run
    def run(self):
        doc, view = self.doc, self.view
        elem, c, axis = find_cut_element(doc, view)
        if elem is None:
            self.w(u'cut element not found')
            return False
        b, z_top, z_bot = concrete_zone(doc, elem, c, axis)
        if b is None:
            self.w(u'no concrete zone')
            return False
        b = _round5(b)
        o, look, right = view_frame(view)
        cf = self.crop = CropFrame(view)
        if not cf.active:
            self.w(u'crop is off - placement not limited by frame')
        off = cf.p(DIM_OFF_P)
        margin = cf.p(CROP_MARGIN_P)
        faces_e = _faces(doc, view, elem)
        if cf.active:
            z_top, z_bot = self._zone_in_crop(cf, c, faces_e, z_top, z_bot)
        pad = to_ft(300.0)
        left_fl, right_fl = _side_floor_elems(doc, c, right, b,
                                              z_bot - pad, z_top + pad)
        left_l, right_l = side_layers(doc, c, right, b, z_top, z_bot)
        slab = main_slab(left_l, right_l)

        u_c = cf.uv(c)[0]
        u_lf = u_c - to_ft(b * 0.5)     # левая грань элемента
        u_rf = u_c + to_ft(b * 0.5)     # правая грань элемента

        plate_map, b_map = self._bracket_maps()
        b_below = None
        b_cm = u'{:g}'.format(b / 10.0)
        if b_cm in b_map:
            b_below = u'({})'.format(b_map[b_cm])

        # ожидаемые отметки узла: только к ним привязываем размеры
        # (лечит «размеры не туда» от граней подрезов/джойнов, 05.09.2026)
        tol_z = to_ft(TOL_Z_MM)
        expected_z = [z_top, z_bot]
        for layers in (left_l, right_l):
            for topz, thk in layers:
                expected_z.append(topz)
                expected_z.append(topz - to_ft(thk))

        def near_expected(z):
            for ez in expected_z:
                if abs(z - ez) < tol_z:
                    return True
            return False

        faces_l = [fi for fl in left_fl for fi in _faces(doc, view, fl)]
        faces_r = [fi for fl in right_fl for fi in _faces(doc, view, fl)]
        # фактические верх/низ по граням в пределах зоны (bbox врёт при
        # джойне с плитой, 180_S5: bbox 46814, грань 46564)
        zin = lambda z: z_bot - tol_z <= z <= z_top + tol_z
        ups = [fi.o.Z for fi in faces_e if fi.n.Z > 0.7 and zin(fi.o.Z)]
        dns = [fi.o.Z for fi in faces_e if fi.n.Z < -0.7 and zin(fi.o.Z)]
        z_top_f = max(ups) if ups else z_top
        if ups:
            expected_z.append(z_top_f)
        if dns:
            expected_z.append(min(dns))
        # ВСЯ геометрия (включая _covers) — ДО первой правки документа;
        # создание аннотаций — списком jobs в конце
        jobs = []

        # --- 1. ширина внизу -------------------------------------------------
        # только грани на ожидаемых позициях +-b/2 (допуск 30 мм)
        tol_x = to_ft(30.0)
        left_face, right_face = None, None
        for fi in faces_e:
            if abs(fi.n.DotProduct(right)) < 0.7:
                continue
            pos = cf.uv(fi.o)[0]
            if abs(pos - u_lf) < tol_x:
                if left_face is None or pos < left_face[0]:
                    left_face = (pos, fi)
            elif abs(pos - u_rf) < tol_x:
                if right_face is None or pos > right_face[0]:
                    right_face = (pos, fi)
        # локальный низ бетона узла (не bbox всего перекрытия)
        z_lowest = z_bot
        for layers in (left_l, right_l):
            for topz, thk in layers:
                z_lowest = min(z_lowest, topz - to_ft(thk))
        if left_face and right_face:
            ra = ReferenceArray()
            ra.Append(left_face[1].ref)
            ra.Append(right_face[1].ref)
            z_w = z_lowest - off
            if cf.active:
                room = cf.uv(XYZ(c.X, c.Y, z_lowest))[1] - cf.min_v
                if room < margin:
                    # кроп режет элемент выше его низа — у нижней кромки
                    # кропа, внутри (190_S7)
                    z_w = z_lowest - room + margin + cf.p(1.0)
                elif room < off + margin:
                    if room >= cf.p(5.0):
                        z_w = z_lowest - (room - cf.p(1.0))
                    else:
                        self.w(u'width: crop too tight below, dim outside')
            base = XYZ(c.X, c.Y, z_w)
            line = Line.CreateBound(base - right * to_ft(b),
                                    base + right * to_ft(b))
            jobs.append((line, ra, u'width', b_below, False, None))
            if cf.active:
                below_p = (cf.min_v - cf.uv(base)[1]) / cf.p(1.0) + \
                    (TEXT_H_P + 2.0 if b_below else 2.0)
                if below_p > 0:
                    self._need_anno(u'bottom', below_p)
        else:
            self.w(u'width: faces at +-b/2 not found')

        # --- 2. вертикальная цепочка ----------------------------------------
        # только грани на ОЖИДАЕМЫХ отметках узла (без граней подрезов);
        # грани плит — только те, что реально есть у элемента (зонд)
        horiz = []
        for fi in faces_e:
            if abs(fi.n.Z) > 0.7 and near_expected(fi.o.Z):
                horiz.append((fi.o.Z, fi))
        for fis, sgn in ((faces_l, -1.0), (faces_r, 1.0)):
            probe = c + right * (to_ft(b * 0.5 + PROBE_MM) * sgn)
            for fi in fis:
                if abs(fi.n.Z) < 0.7 or not near_expected(fi.o.Z):
                    continue
                if _covers(fi, XYZ(probe.X, probe.Y, fi.o.Z)):
                    horiz.append((fi.o.Z, fi))
        if len(horiz) >= 2:
            horiz.sort(key=lambda x: x[0])
            ra, last = ReferenceArray(), None
            for zf, fi in horiz:
                if last is not None and (zf - last) * FT_MM < DEDUPE_MM:
                    continue
                last = zf
                ra.Append(fi.ref)
            if ra.Size >= 2:
                u_chain = u_lf - off
                outside = bool(left_fl) or \
                    (cf.active and u_chain < cf.min_u + margin)
                if outside and cf.active:
                    # за левым краем кропа, снаружи обреза плиты
                    u_chain = cf.min_u - cf.p(CHAIN_OUT_P)
                    self._need_anno(u'left', CHAIN_OUT_P + TEXT_H_P + 2.0)
                xl = cf.shift(c, du=u_chain - u_c)
                line = Line.CreateBound(XYZ(xl.X, xl.Y, z_lowest),
                                        XYZ(xl.X, xl.Y, z_top))
                jobs.append((line, ra, u'height chain', None, False, -1.0))

        # --- 3. толщина плиты у дальнего конца ------------------------------
        # позиция — от края кропа внутрь; грани — ближайшие к слою И
        # реально лежащие под линией размера (или у грани элемента)
        for fis, layers, sgn in ((faces_r, right_l, 1.0),
                                 (faces_l, left_l, -1.0)):
            if not fis or not layers:
                continue
            topz, thk = layers[0]
            botz = topz - to_ft(thk)
            u_face = u_rf if sgn > 0 else u_lf
            if cf.active:
                edge = cf.max_u if sgn > 0 else cf.min_u
                u_d = edge - sgn * cf.p(SLABDIM_IN_P)
                if (u_d - u_face) * sgn < to_ft(SLABDIM_MIN_MM):
                    # тесно: посередине между гранью и рамкой
                    u_d = (u_face + edge) * 0.5
                if (u_d - u_face) * sgn < to_ft(SLABDIM_TIGHT_MM):
                    self.w(u'slab thickness ({}): no room inside crop'
                           .format(u'right' if sgn > 0 else u'left'))
                    continue
            else:
                u_d = u_face + sgn * to_ft(SLABDIM_FALLBACK_MM)
            xd = cf.shift(c, du=u_d - u_c)
            probe = c + right * (to_ft(b * 0.5 + PROBE_MM) * sgn)
            top_f, bot_f = None, None
            for fi in fis:
                if abs(fi.n.Z) < 0.7:
                    continue
                dz_t = abs(fi.o.Z - topz)
                dz_b = abs(fi.o.Z - botz)
                if dz_t >= tol_z and dz_b >= tol_z:
                    continue
                if not (_covers(fi, XYZ(xd.X, xd.Y, fi.o.Z)) or
                        _covers(fi, XYZ(probe.X, probe.Y, fi.o.Z))):
                    continue
                if dz_t < tol_z and (top_f is None or
                                     dz_t < abs(top_f.o.Z - topz)):
                    top_f = fi
                elif dz_b < tol_z and (bot_f is None or
                                       dz_b < abs(bot_f.o.Z - botz)):
                    bot_f = fi
            if top_f is None or bot_f is None:
                self.w(u'slab thickness: layer faces not found')
                continue
            below = None
            thk_cm = u'{:g}'.format(_round5(thk) / 10.0)
            if thk_cm in plate_map:
                below = u'({})'.format(plate_map[thk_cm])
            ra = ReferenceArray()
            ra.Append(top_f.ref)
            ra.Append(bot_f.ref)
            line = Line.CreateBound(XYZ(xd.X, xd.Y, botz),
                                    XYZ(xd.X, xd.Y, topz))
            jobs.append((line, ra, u'slab thickness', below, True, None))

        # --- 4. отметка перекрытия (выбор грани — тоже до правок) -----------
        # сторона — где есть плита (приоритет правая)
        sgn = 1.0 if (right_l or not left_l) else -1.0
        s_layers = right_l if sgn > 0 else left_l
        s_top = s_layers[0][0] if s_layers else \
            (slab[0] if slab is not None else z_top_f)
        u_face = u_rf if sgn > 0 else u_lf
        spot = None
        if not self.typical:
            # точка на плите у грани -> дальше в плите -> на верху элемента
            fis = faces_r if sgn > 0 else faces_l
            inner = min(to_ft(50.0), to_ft(b * 0.25))
            tries = [(fis, u_face + sgn * to_ft(100.0)),
                     (fis, u_face + sgn * to_ft(PROBE_MM)),
                     (faces_e, u_face - sgn * inner)]
            for cand, u_fp in tries:
                fi = self._pick_spot_face(c, u_c, u_fp, s_top, cand)
                if fi is not None:
                    spot = (fi, u_fp)
                    break

        # --- создание ---------------------------------------------------------
        for line, ra, label, below, inside, chain_side in jobs:
            self._new_dim(line, ra, label, below=below, inside=inside,
                          chain_side=chain_side)
        if self.typical:
            self._place_ok(c, u_c, u_face, sgn, s_top)
        else:
            self._place_spot(c, u_c, sgn, spot)
        return True

    # ------------------------------------------------------------- helpers
    def _zone_in_crop(self, cf, c, faces_e, z_top, z_bot):
        """Зона элемента в основном вне кропа (многоэтажная стена: bbox +
        проём ВЕРХНЕГО этажа, 160_S5) — пересчитать по горизонтальным
        граням элемента внутри кропа (разрез вертикален: v = z + const)."""
        dz = cf.uv(XYZ(c.X, c.Y, 0.0))[1]
        lo, hi = cf.min_v - dz, cf.max_v - dz
        h = z_top - z_bot
        ovl = min(z_top, hi) - max(z_bot, lo)
        if h <= 0 or ovl >= 0.5 * h:
            return z_top, z_bot
        ups = [fi.o.Z for fi in faces_e if fi.n.Z > 0.7 and lo <= fi.o.Z <= hi]
        dns = [fi.o.Z for fi in faces_e
               if fi.n.Z < -0.7 and lo <= fi.o.Z <= hi]
        if not ups and not dns:
            self.w(u'element zone is outside crop')
            return z_top, z_bot
        nt = max(ups) if ups else hi
        nb = min(dns) if dns else lo
        if nt - nb < to_ft(80.0):
            return z_top, z_bot
        self.placed.append(u'zone by crop {:.0f}..{:.0f}'.format(
            mm(nb), mm(nt)))
        return nt, nb

    def _bracket_maps(self):
        """Скобочные пары «мастер>вариант» из dummy этого разреза; «(22)»
        встаёт ТОЛЬКО под размер плиты, чья толщина = источнику пары."""
        plate_map, b_map = {}, {}
        dmy = dummy_of(self.doc, self.view)
        if dmy is None:
            return plate_map, b_map
        dp = dmy.get_Parameter(BuiltInParameter.VIEW_DESCRIPTION)
        desc = dp.AsString() if dp else None
        if not desc:
            return plate_map, b_map
        for pat, dst in ((u'(?:slab|плита) '
                          u'd=([0-9./>,]+)', plate_map),
                         (u'b=([0-9./>,]+)', b_map)):
            m = re.search(pat, desc)
            if m:
                for tok in m.group(1).split(u','):
                    if u'>' in tok:
                        a, d2 = tok.split(u'>', 1)
                        dst[a] = d2
        return plate_map, b_map

    def _place_ok(self, c, u_c, u_face, sgn, s_top):
        cf = self.crop
        sym = self.ok_sym
        if sym is None:
            self.w(u'symbol "{}" not found'.format(FAM_OK))
            return
        u_ok = u_face + sgn * cf.p(OK_OFF_P)
        pt = cf.shift(c, du=u_ok - u_c)
        pt = XYZ(pt.X, pt.Y, s_top)
        try:
            if not sym.IsActive:
                sym.Activate()
            inst = self.doc.Create.NewFamilyInstance(pt, sym, self.view)
            self.created.append(inst.Id)
            self.fit_in.append((inst.Id, u'O.K.'))
            self.placed.append(u'O.K.')
        except Exception as e:
            self.w(u'O.K.: {}'.format(e))

    def _pick_spot_face(self, c, u_c, u_fp, s_top, fis):
        """Верхняя грань, накрывающая точку u_fp, ближайшая к s_top.
        Зовётся ДО правок документа."""
        cf = self.crop
        fp0 = cf.shift(c, du=u_fp - u_c)
        top_face, best = None, None
        for fi in fis:
            if fi.n.Z <= 0.7:
                continue
            if not _covers(fi, XYZ(fp0.X, fp0.Y, fi.o.Z)):
                continue
            dz = abs(fi.o.Z - s_top)
            if best is None or dz < best:
                top_face, best = fi, dz
        return top_face

    def _place_spot(self, c, u_c, sgn, spot):
        cf = self.crop
        st = self.spot_type
        if st is None:
            self.w(u'spot type "{}" not found'.format(SPOT_TYPE))
            return
        if spot is None:
            self.w(u'Spot: no top face')
            return
        top_face, u_fp = spot
        fp0 = cf.shift(c, du=u_fp - u_c)
        # лидер наружу от элемента; нет места до рамки — разворот к элементу
        d = sgn
        if cf.active:
            edge = cf.max_u if sgn > 0 else cf.min_u
            room_p = (edge - u_fp) * sgn / cf.p(1.0)
            if room_p < SPOT_ROOM_P:
                d = -sgn
        fp = XYZ(fp0.X, fp0.Y, top_face.o.Z)
        bend = cf.shift(fp, du=d * cf.p(SPOT_LEAD1_P))
        end = cf.shift(bend, du=d * cf.p(SPOT_LEAD2_P))
        try:
            spot = self.doc.Create.NewSpotElevation(
                self.view, top_face.ref, fp, bend, end, fp, True)
            if spot is None:
                self.w(u'Spot: not created')
                return
            try:
                spot.ChangeTypeId(st.Id)
            except Exception:
                pass
            self.created.append(spot.Id)
            self.fit_in.append((spot.Id, u'Spot'))
            self.spot_data = (top_face.ref, fp, bend, end)
            self.placed.append(u'Spot Elevation')
        except Exception as e:
            self.w(u'Spot: {}'.format(e))

    # ------------------------------------------------ фаза 2 (после Regenerate)
    def finish(self):
        """Разнос текста, подгонка в рамку, annotation crop, запись ES."""
        if self.crop is None:
            return
        doc, cf = self.doc, self.crop
        for did, side in self.chains:
            self._spread_text(doc.GetElement(did), side)
        margin = cf.p(CROP_MARGIN_P)
        for eid, label in self.fit_in:
            el = doc.GetElement(eid)
            if el is None:
                continue
            du, dv = cf.inside_delta(el, margin)
            if abs(du) < 1e-6 and abs(dv) < 1e-6:
                continue
            if label == u'Spot':
                # Spot привязан к грани — пересоздаём с полкой, сдвинутой
                # внутрь (точка на грани остаётся)
                self._respot(eid, du, dv)
                continue
            try:
                ElementTransformUtils.MoveElement(
                    doc, eid, cf.right * du + cf.up * dv)
                self.placed.append(u'{} moved inside'.format(label))
            except Exception as e:
                self.w(u'{} {} out of crop: {}'.format(
                    label, eid.IntegerValue, e))
        self._fit_annotation_crop()
        try:
            _store_ids(self.view, [i.IntegerValue for i in self.created])
        except Exception as e:
            self.w(u'ES store: {}'.format(e))

    def _respot(self, eid, du, dv):
        doc, cf = self.doc, self.crop
        data = getattr(self, 'spot_data', None)
        if data is None:
            self.w(u'Spot {} goes out of crop'.format(eid.IntegerValue))
            return
        ref, fp, bend, end = data
        delta = cf.right * du + cf.up * dv
        try:
            doc.Delete(eid)
            self.created = [i for i in self.created if i != eid]
            spot = doc.Create.NewSpotElevation(
                self.view, ref, fp, bend + delta, end + delta, fp, True)
            try:
                spot.ChangeTypeId(self.spot_type.Id)
            except Exception:
                pass
            self.created.append(spot.Id)
            self.placed.append(u'Spot moved inside')
        except Exception as e:
            self.w(u'Spot {} out of crop: {}'.format(eid.IntegerValue, e))

    def _spread_text(self, d, side):
        """Мелкие сегменты цепочки: текст крайних — вдоль линии наружу,
        внутренних — в сторону от бетона лесенкой."""
        if d is None or d.NumberOfSegments < 2:
            return
        cf = self.crop
        try:
            ln = d.Curve
            dirv = ln.Direction
        except Exception:
            return
        segs = list(d.Segments)
        # сегменты по возрастанию вдоль линии
        segs.sort(key=lambda s: s.Origin.DotProduct(dirv))
        n = len(segs)
        step = 0
        for i, s in enumerate(segs):
            try:
                val_p = mm(s.Value) / cf.scale
            except Exception:
                continue
            if val_p >= SMALL_SEG_P:
                step = 0
                continue
            try:
                pos = s.TextPosition
                half = to_ft(mm(s.Value) * 0.5)
                txt = cf.p(SMALL_SEG_P * 0.5 + 1.0)
                if i == 0:
                    s.TextPosition = pos - dirv * (half + txt)
                elif i == n - 1:
                    s.TextPosition = pos + dirv * (half + txt)
                else:
                    step += 1
                    s.TextPosition = pos + cf.right * \
                        (side * cf.p(TEXT_H_P) * step)
                    self._need_anno(u'left', CHAIN_OUT_P + TEXT_H_P *
                                    (step + 1) + 2.0)
            except Exception as e:
                self.w(u'text shift: {}'.format(e))

    def _fit_annotation_crop(self):
        """Annotation crop: только увеличить нужные стороны (модельный кроп
        не трогаем). Отступы annotation crop — в футах БУМАГИ."""
        view = self.view
        if not self.anno_need:
            return
        try:
            p = view.get_Parameter(
                BuiltInParameter.VIEWER_ANNOTATION_CROP_ACTIVE)
            if p is None or p.AsInteger() != 1:
                return
            mgr = view.GetCropRegionShapeManager()
        except Exception:
            return
        props = {u'left': u'LeftAnnotationCropOffset',
                 u'right': u'RightAnnotationCropOffset',
                 u'top': u'TopAnnotationCropOffset',
                 u'bottom': u'BottomAnnotationCropOffset'}
        for side, need_p in self.anno_need.items():
            pname = props[side]
            try:
                cur = getattr(mgr, pname)
                need = to_ft(need_p)
                if cur < need:
                    setattr(mgr, pname, need)
                    self.placed.append(u'anno crop {} {:.0f}mm'.format(
                        side, need_p))
            except Exception as e:
                self.w(u'annotation crop {}: {}'.format(side, e))


def annotate_views(doc, views, typical):
    """Размеры+отметки на набор разрезов. (done, warns, placed_per_view)."""
    done, warns, placed = 0, [], []
    dim_type = find_dim_type(doc, DIM_TYPE)
    spot_type = find_spot_type(doc, SPOT_TYPE)
    ok_sym = find_symbol(doc, FAM_OK) if typical else None
    if dim_type is None:
        warns.append(u'dimension type "{}" not found - default used'
                     .format(DIM_TYPE))
    markers = []
    t = Transaction(doc, u'Section dimensions and marks')
    t.Start()
    try:
        _schema()
        # фаза 1: удалить прежнее и поставить заново (SubTransaction на вид)
        for v in views:
            dm = DimsMarker(doc, v, typical, dim_type, spot_type, ok_sym)
            st = SubTransaction(doc)
            st.Start()
            try:
                removed = _remove_previous(doc, v)
                ok = dm.run()
                st.Commit()
                if removed:
                    dm.placed.insert(0, u'removed old {}'.format(removed))
                if ok:
                    done += 1
                    markers.append(dm)
            except Exception as e:
                if st.HasStarted() and not st.HasEnded():
                    st.RollBack()
                dm.w(u'FAILED {}'.format(e))
                dm.placed = []
            warns.extend(dm.warn)
            placed.append((v.Name, dm.placed))
        # фаза 2: один Regenerate на пакет, потом подгонка
        doc.Regenerate()
        for dm in markers:
            n0 = len(dm.warn)
            try:
                dm.finish()
            except Exception as e:
                dm.w(u'finish: {}'.format(e))
            warns.extend(dm.warn[n0:])
        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise
    return done, warns, placed
