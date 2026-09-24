# -*- coding: utf-8 -*-
"""kz_sections — правила стандарта «КЖ — стандарт оформления» (Р1, Р4) поверх lib/AutoSections.

Что отличается от AutoSections (окна/балки, старый инструмент):
    * Ключ уникальности Р1.1: b строго (1 мм), h с допуском (бакет 5 мм),
      толщины прилегающих плит с ОБЕИХ сторон (бакет 10 мм, зеркально-инвариантно),
      вертикальная привязка к плите (бакет 10 мм). Семейство/тип в ключ не входят.
    * Тонкие плиты (<= INSULATION_MAX_MM) считаются утеплителем/отделкой и в ключ
      и контекст НЕ входят (Р2.6 обрабатывает их отдельно на этапе оформления).
    * Направление взгляда Р1.5: внутренняя часть здания справа (по центроиду стен
      уровня); если разрез внутри здания — берём +axis как есть.
    * Far clip Р1.6: 10 мм.
    * Кроме балок поддержаны ПЕРЕМЫЧКИ над проёмами в стенах ('WALLBEAM'):
      простенок над дверью/окном/отверстием — тот же ключ, та же геометрия бокса,
      поэтому балка и эквивалентная перемычка сливаются в одну группу (Р1.1).
    * Размещение на СУЩЕСТВУЮЩЕМ листе рядами (Р4), Detail Number = следующий
      свободный, имя вида = '{префикс}_S{DetailNumber}' (Р1.8).

Связи (Revit links): бетон часто лежит не в активном документе, а в связанной
структурной модели. Поэтому геометрия читается из списка ИСТОЧНИКОВ (kz_links):
хост всегда первый, дальше загруженные связи. Общий язык — координаты ХОСТА:
всё, что пришло из источника (кривая, габарит, отрезок пересечения), сразу
переводится в хост, а зонд перед запросом опускается в систему источника.
Виды, маркеры, вьюпорты и листы — по-прежнему только в документе хоста.
Вызов без списка источников оставляет прежнее поведение «только хост».
"""

import math

from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, BuiltInParameter, ElementId,
    Transaction, ViewSection, Viewport, XYZ, Wall,
    Outline, BoundingBoxIntersectsFilter, LocationCurve,
    Element, Options, Line, Solid, GeometryInstance,
    SolidCurveIntersectionOptions,
)

from AutoSections.convert import mm, to_ft
from AutoSections import geometry as G
from AutoSections import adjacency as A
from AutoSections import params as P
import kz_links as L

# ----------------------------------------------------------------- константы Р1/Р4
B_TOL_MM = 1.0            # Р1.2: ширина один в один
H_TOL_MM = 5.0            # Р1.2: высота +-2 мм -> бакет 5 мм
SLAB_TOL_MM = 10.0        # толщины плит в ключе
VOFF_TOL_MM = 10.0        # вертикальная привязка к плите
FAR_CLIP_MM = 10.0        # Р1.6
INSULATION_MAX_MM = 40.0  # тонкая плита = утеплитель/отделка, в ключ не входит
MIN_LINTEL_MM = 50.0      # перемычка ниже этого — не оформляем

SEC_MARGIN_MM = 500.0     # запас кропа над/под элементом и со стороны без плиты
SEC_SLAB_WIDEN_MM = 1000.0  # запас кропа в сторону плиты

VIEW_SCALE = 25           # Р1.12
TEMPLATE_NAME = 'PEER SEC'  # Р1.12; если нет в проекте — пропускаем с предупреждением

ROW_GAP_MM = 10.0         # Р4.3: зазор между вьюпортами
ROW_VGAP_MM = 10.0        # вертикальный зазор между рядами
ROW_MAX_W_MM = 800.0      # ширина зоны разрезов на листе до переноса ряда

# Если ВСЕ референс-маркеры смотрят в обратную сторону — поставь -1 (ср. FLIP_LOOK
# в MirrorSections). Меняет порядок head/tail при CreateReferenceSection.
MARKER_LOOK_SIGN = 1

FT_MM = 304.8


def _bucket(v_mm, tol):
    return int(round(v_mm / tol) * tol) if tol > 1.0 else int(round(v_mm))


# ----------------------------------------------------------------- источники
# Источник = (документ, трансформация в координаты хоста, экземпляр связи),
# см. lib/kz_links.py. Ниже — только то, что нужно этому модулю; сам разбор
# габаритов и Outline'ов живёт в AutoSections.adjacency (A.host_box,
# A.source_outline, A.sources_of), чтобы не дублировать код.

def _host_src(doc, src=None):
    """Источник по умолчанию — сам документ (поведение «только хост»)."""
    if src is not None:
        return src
    return L.sources(doc, include_links=False)[0]


def _geo_opts(src):
    """Опции get_Geometry: для хоста — ровно как раньше, для связи — kz_links
    (вид хоста к элементу связи неприменим, уровень детализации решает всё)."""
    if src.is_link:
        return L.source_options(src, None, False)
    opts = Options()
    opts.ComputeReferences = False
    return opts


def _label(src, el):
    """Подпись элемента для сообщений: id, у связи — с её именем.

    Id повторяются от документа к документу, поэтому «12345» без имени
    связи ничего не значит (для ключей/дедупа есть Source.key)."""
    try:
        eid = el.Id
    except Exception:
        eid = u'?'
    if src is not None and src.is_link:
        return u'{} [{}]'.format(eid, src.name)
    return u'{}'.format(eid)


def _pairs(items, host):
    """Пары (элемент, источник). Голый список элементов = всё из хоста,
    поэтому старый вызов build_groups(doc, beams, walls, centroid) жив."""
    out = []
    for it in (items or ()):
        if isinstance(it, (tuple, list)):
            out.append((it[0], it[1]))
        else:
            out.append((it, host))
    return out


# ----------------------------------------------------------------- центроид здания

CENTROID_LEVEL_TOL_MM = 1500.0   # допуск сопоставления уровня связи с уровнем хоста


def _level_z_host(el, src):
    """Отметка уровня элемента в координатах ХОСТА, или None."""
    try:
        lvl = el.Document.GetElement(el.LevelId)
        if lvl is None:
            return None
        return src.to_host(XYZ(0.0, 0.0, lvl.Elevation)).Z
    except Exception:
        return None


def building_centroid(doc, level_id=None, srcs=None):
    """Центроид стен (по центрам bbox) — «внутренняя часть здания» для Р1.5.

    Стены берутся из всех источников, центры габаритов — в координатах хоста.
    LevelId элемента СВЯЗИ принадлежит документу связи и с id уровня хоста
    несравним, поэтому у связей уровень сопоставляется по ОТМЕТКЕ
    (CENTROID_LEVEL_TOL_MM); стена связи без читаемого уровня остаётся.
    """
    sx = sy = n = 0.0
    lvl_z = None
    if level_id is not None:
        try:
            lvl = doc.GetElement(level_id)
            lvl_z = lvl.Elevation if lvl is not None else None
        except Exception:
            lvl_z = None
    tol = to_ft(CENTROID_LEVEL_TOL_MM)
    for src in A.sources_of(doc, srcs):
        col = (FilteredElementCollector(src.doc)
               .OfCategory(BuiltInCategory.OST_Walls)
               .WhereElementIsNotElementType())
        for w in col:
            if level_id is not None:
                if not src.is_link:
                    if getattr(w, 'LevelId', None) != level_id:
                        continue
                elif lvl_z is not None:
                    z = _level_z_host(w, src)
                    if z is not None and abs(z - lvl_z) > tol:
                        continue
            box = A.host_box(w, src)
            if box is None:
                continue
            sx += (box[0] + box[1]) * 0.5
            sy += (box[2] + box[3]) * 0.5
            n += 1.0
    if n < 1.0:
        return None
    return XYZ(sx / n, sy / n, 0.0)


def pick_view_dir(axis, origin, centroid):
    """Р1.5 (запасное): интерьер СПРАВА НА ЭКРАНЕ.

    ЭКРАННОЕ право разреза = взгляд x Z (ViewDirection Revit = -BasisZ бокса,
    отсюда RightDirection = vdir x Z). Раньше стояло Z x vdir — это ЛЕВО,
    из-за чего плиты/интерьер уходили влево (баг, пойман юзером 05.09.2026).
    """
    if centroid is None:
        return axis
    to_c = XYZ(centroid.X - origin.X, centroid.Y - origin.Y, 0.0)
    screen_r = axis.CrossProduct(XYZ.BasisZ)   # экранное право при vdir=+axis
    d = to_c.DotProduct(screen_r)
    if abs(d) < to_ft(500.0):      # центроид на оси — «внутри здания»
        return axis
    return axis if d > 0 else axis.Negate()


# ----------------------------------------------------------------- контекст плит
# Организация (переделано после фидбека «какие-то правильно, какие-то нет»):
# сторону плиты определяем НЕ по bounding box (лотерея на сплошных/Г-образных
# плитах), а зондами по реальным солидам: вертикальный луч сразу за гранью
# элемента с каждой стороны, в высотном диапазоне самого элемента. Что луч
# пересёк — та плита и есть: точная толщина и отметка верха. Эти же данные
# идут в ключ уникальности (толщина + отметка относительно верха элемента).

PROBE_NEAR_MM = 250.0     # зонд: отступ за грань (b/2 + это)
PROBE_FAR_MM = 600.0      # второй зонд, если первый ничего не нашёл (стык/гильза)
PROBE_FAR2_MM = 1000.0    # третий зонд (широкие примыкания/ниши)
PROBE_ZPAD_MM = 300.0     # запас диапазона по высоте сверху/снизу элемента


def _solids_of(geo):
    res = []
    if geo is None:
        return res
    for obj in geo:
        if isinstance(obj, Solid):
            if obj.Volume > 1e-9:
                res.append(obj)
        elif isinstance(obj, GeometryInstance):
            for o2 in obj.GetInstanceGeometry():
                if isinstance(o2, Solid) and o2.Volume > 1e-9:
                    res.append(o2)
    return res


def _slab_layers_at(doc, x, y, z_lo, z_hi, keep=u'thick', srcs=None):
    """Слои плит на вертикали (x, y) в [z_lo, z_hi]: [(top_z_ft, thickness_mm)].

    Пересечение вертикального луча с фактическими солидами полов.
    keep='thick' — несущие слои (> INSULATION_MAX_MM), тонкие отбрасываются;
    keep='thin'  — наоборот, только тонкие (утеплитель/отделка, 8..40 мм).

    (x, y, z) и возвращаемые отметки — в координатах ХОСТА; каждый источник
    сам опускает луч к себе и поднимает результат обратно.
    """
    if z_hi - z_lo < to_ft(10.0):
        return []
    layers = []
    for src in A.sources_of(doc, srcs):
        layers.extend(_slab_layers_src(src, x, y, z_lo, z_hi, keep))
    return layers


def _slab_layers_src(src, x, y, z_lo, z_hi, keep):
    """Слои плит ОДНОГО источника (см. _slab_layers_at).

    Луч вертикален в хосте; у связи с поворотом вокруг Z он остаётся прямой,
    поэтому IntersectWithCurve работает как есть — но Z вернувшегося отрезка
    до перевода в хост хостовой отметкой НЕ является.
    """
    r = to_ft(150.0)
    outline = A.source_outline(src, XYZ(x - r, y - r, z_lo),
                               XYZ(x + r, y + r, z_hi))
    floors = (FilteredElementCollector(src.doc)
              .OfCategory(BuiltInCategory.OST_Floors)
              .WhereElementIsNotElementType()
              .WherePasses(BoundingBoxIntersectsFilter(outline)).ToElements())
    if not floors:
        return []
    line = Line.CreateBound(src.to_source(XYZ(x, y, z_lo)),
                            src.to_source(XYZ(x, y, z_hi)))
    opts = _geo_opts(src)
    sco = SolidCurveIntersectionOptions()
    layers = []
    for fl in floors:
        # толщина — из ПАРАМЕТРА типа: длина отрезка луча у кромок/подрезов
        # врёт (140_S5: кромка d=22 дала лучом 200 -> слияние групп,
        # диагностика 05.09.2026); луч — только «попал/не попал» + верх
        tp = A._floor_thickness_mm(fl)
        try:
            for solid in _solids_of(fl.get_Geometry(opts)):
                sci = solid.IntersectWithCurve(line, sco)
                if sci is None:
                    continue
                for i in range(sci.SegmentCount):
                    c = sci.GetCurveSegment(i)
                    z1 = src.to_host(c.GetEndPoint(0)).Z
                    z2 = src.to_host(c.GetEndPoint(1)).Z
                    seg = mm(abs(z2 - z1))
                    if seg < 8.0:
                        continue
                    thk = tp if tp > 8.0 else seg
                    if keep == u'thin':
                        if 8.0 < thk <= INSULATION_MAX_MM:
                            layers.append((max(z1, z2), thk))
                    elif thk > INSULATION_MAX_MM:
                        layers.append((max(z1, z2), thk))
        except Exception:
            continue
    return layers


def _side_ins(doc, origin, dirvec, b_mm, z_lo, z_hi, z_ref, srcs=None):
    """Есть ли утеплитель с этой стороны: тонкий слой (8..40 мм), верх
    которого НИЖЕ верха элемента минимум на 100 мм (отделка поверх плиты
    лежит на уровне верха и утеплителем не считается)."""
    for dist in (b_mm * 0.5 + PROBE_NEAR_MM, b_mm * 0.5 + PROBE_FAR_MM,
                 b_mm * 0.5 + PROBE_FAR2_MM):
        pt = origin + dirvec * to_ft(dist)
        for top_z, _thk in _slab_layers_at(doc, pt.X, pt.Y, z_lo, z_hi,
                                           keep=u'thin', srcs=srcs):
            if top_z <= z_ref - to_ft(100.0):
                return True
    return False


def _side_slabs(doc, origin, dirvec, b_mm, z_lo, z_hi, z_ref, srcs=None):
    """Плиты со стороны dirvec: ((thk_bucket, off_bucket), ...) отсортированно.

    off — отметка верха плиты относительно верха элемента (z_ref), поэтому ключ
    ловит и «расстояние от плиты» из Р1.1. Три зонда: у грани и дальше.
    """
    for dist in (b_mm * 0.5 + PROBE_NEAR_MM, b_mm * 0.5 + PROBE_FAR_MM,
                 b_mm * 0.5 + PROBE_FAR2_MM):
        pt = origin + dirvec * to_ft(dist)
        layers = _slab_layers_at(doc, pt.X, pt.Y, z_lo, z_hi, srcs=srcs)
        if layers:
            out = []
            for top_z, thk in layers:
                out.append((_bucket(thk, SLAB_TOL_MM),
                            _bucket(mm(top_z - z_ref), VOFF_TOL_MM)))
            return tuple(sorted(out))
    return ()


# ----------------------------------------------------------------- мамад (искл.)

# Окна помещений ממ"ד — специальные (взрывостойкие), типовая перемычка там не
# оформляется: такие проёмы пропускаем целиком (решение пользователя 04.09.2026).
MAMAD_NAME_MARKERS = (u'ממ"ד', u'ממ״ד', u'ממד', u'MMD', u'MAMAD', u'הדף')


def _name_has_mamad(el):
    try:
        names = [Element.Name.__get__(el)]
    except Exception:
        names = []
    try:
        t = el.Document.GetElement(el.GetTypeId())
        if t is not None:
            names.append(Element.Name.__get__(t))
            fam = getattr(t, 'FamilyName', None)
            if fam:
                names.append(fam)
    except Exception:
        pass
    for n in names:
        if not n:
            continue
        up = n.upper()
        for m in MAMAD_NAME_MARKERS:
            if m.upper() in up:
                return True
    return False


def _room_is_mamad(room):
    if room is None:
        return False
    try:
        name = room.get_Parameter(BuiltInParameter.ROOM_NAME).AsString() or u''
    except Exception:
        name = u''
    up = name.upper()
    for m in MAMAD_NAME_MARKERS:
        if m.upper() in up:
            return True
    return False


def _mamad_room_at(doc, pt, srcs=None):
    """Мамад-помещение в точке: сначала свой документ, затем Revit-линки.

    pt — в координатах ХОСТА. Поведение прежнее, просто перебор идёт через
    общий список источников (хост всегда первый, у него to_source — no-op).
    """
    for src in A.sources_of(doc, srcs):
        try:
            if _room_is_mamad(src.doc.GetRoomAtPoint(src.to_source(pt))):
                return True
        except Exception:
            continue
    return False


def is_mamad_opening(doc, ins, wall_axis, src=None, srcs=None):
    """Проём мамада: спец-окно по имени ИЛИ мамад-Room по любую сторону стены.

    ins может лежать в связи: центр габарита берём в координатах хоста, там же
    считаем wall_axis, а помещения ищутся во всех источниках."""
    if _name_has_mamad(ins):
        return True
    box = A.host_box(ins, _host_src(doc, src))
    if box is None:
        return False
    c = XYZ((box[0] + box[1]) * 0.5, (box[2] + box[3]) * 0.5,
            (box[4] + box[5]) * 0.5)
    across = XYZ.BasisZ.CrossProduct(wall_axis).Normalize()
    off = to_ft(600.0)
    for sgn in (1.0, -1.0):
        if _mamad_room_at(doc, c + across * (off * sgn), srcs):
            return True
    return False


# --------------------------------------------------------- бетонная стопка

def _concrete_segments_at(doc, x, y, z_lo, z_hi, srcs=None):
    """Слои бетона (балки+плиты+стены) на вертикали (x,y): [(lo_ft, hi_ft)],
    слитые с допуском 50 мм.

    Координаты ХОСТА на входе и на выходе. Слияние идёт ПОСЛЕ обхода всех
    источников, поэтому балка хоста и плита связи собираются в одну стопку.
    """
    if z_hi - z_lo < to_ft(10.0):
        return []
    segs = []
    for src in A.sources_of(doc, srcs):
        segs.extend(_concrete_segments_src(src, x, y, z_lo, z_hi))
    segs.sort()
    merged, gap = [], to_ft(50.0)
    for lo, hi in segs:
        if merged and lo <= merged[-1][1] + gap:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    return merged


def _concrete_segments_src(src, x, y, z_lo, z_hi):
    """Отрезки бетона ОДНОГО источника, отметки уже в координатах хоста."""
    r = to_ft(150.0)
    bbf = BoundingBoxIntersectsFilter(
        A.source_outline(src, XYZ(x - r, y - r, z_lo),
                         XYZ(x + r, y + r, z_hi)))
    els = []
    for bic in (BuiltInCategory.OST_StructuralFraming,
                BuiltInCategory.OST_Floors, BuiltInCategory.OST_Walls):
        els.extend(FilteredElementCollector(src.doc).OfCategory(bic)
                   .WhereElementIsNotElementType().WherePasses(bbf)
                   .ToElements())
    if not els:
        return []
    line = Line.CreateBound(src.to_source(XYZ(x, y, z_lo)),
                            src.to_source(XYZ(x, y, z_hi)))
    opts = _geo_opts(src)
    sco = SolidCurveIntersectionOptions()
    segs = []
    for el in els:
        # тонкий пол (полиэш/утеплитель <= INSULATION_MAX_MM) — не бетон:
        # иначе он удлинял стопку на 20 мм и менял h в ключе (24.09.2026)
        if (el.Category is not None and el.Category.Id.IntegerValue ==
                int(BuiltInCategory.OST_Floors)):
            thk = A._floor_thickness_mm(el)
            if 0.0 < thk <= INSULATION_MAX_MM:
                continue
        try:
            for s in _solids_of(el.get_Geometry(opts)):
                sci = s.IntersectWithCurve(line, sco)
                if sci is None:
                    continue
                for i in range(sci.SegmentCount):
                    cs = sci.GetCurveSegment(i)
                    z1 = src.to_host(cs.GetEndPoint(0)).Z
                    z2 = src.to_host(cs.GetEndPoint(1)).Z
                    if abs(z2 - z1) > to_ft(8.0):
                        segs.append((min(z1, z2), max(z1, z2)))
        except Exception:
            continue
    return segs


def stack_range(doc, x, y, seed_lo, seed_hi, srcs=None):
    """Связный бетонный столб, содержащий диапазон-затравку: (z_lo, z_hi).

    Универсальный ответ на «балка ниже перекрытия + балка выше» — узел
    определяется всей стопкой, а не одним элементом (фидбек 05.09.2026)."""
    win = to_ft(2500.0)
    segs = _concrete_segments_at(doc, x, y, seed_lo - win, seed_hi + win, srcs)
    mid = (seed_lo + seed_hi) * 0.5
    for lo, hi in segs:
        if lo - to_ft(30.0) <= mid <= hi + to_ft(30.0):
            return min(lo, seed_lo), max(hi, seed_hi)
    return seed_lo, seed_hi


def _elem_width_mm(elem, axis, box):
    """Ширина поперёк оси: параметры B/Width с проверкой по габариту bbox
    (FAMILY_WIDTH у PEER-балок врёт, bbox по мировой оси — ловушка длины).

    box — габарит в координатах ХОСТА (A.host_box), axis — тоже хостовая;
    тип берётся из СВОЕГО документа элемента (у связи это документ связи).
    У связи, повёрнутой на некратный 90° угол, хостовый габарит шире
    фактического, поэтому проверка «параметр не шире факта» там мягче."""
    right = XYZ.BasisZ.CrossProduct(axis).Normalize()
    w_bbox = mm(abs((box[1] - box[0]) * right.X) +
                abs((box[3] - box[2]) * right.Y))
    cands = []
    sym = elem.Document.GetElement(elem.GetTypeId())
    for host in (sym, elem):
        if host is None:
            continue
        for pname in (u'B', u'b', u'Width'):
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
        if v <= w_bbox * 1.2 + 20.0:
            return v
    if 30.0 < w_bbox < 2500.0:
        return w_bbox
    return cands[0] if cands else 300.0


# ----------------------------------------------------------------- узлы (Р1.1)

def _fallback_slab_thk(doc, origin, b_mm, z_lo, z_hi, srcs=None):
    """Страховка: толщина БЛИЖАЙШЕЙ плиты по параметру типа, когда лучевые
    зонды не дотянулись (плита с вырезом, нестандартное примыкание).
    Без неё две одинаковые балки с РАЗНЫМИ плитами слипались в одну группу
    (фидбек 05.09.2026: референс на 4 вместо 5).

    origin — в координатах хоста; расстояние до плиты тоже меряется в хосте,
    поэтому плиты всех источников сравниваются между собой честно."""
    r = to_ft(b_mm * 0.5 + 1500.0)
    lo = XYZ(origin.X - r, origin.Y - r, z_lo)
    hi = XYZ(origin.X + r, origin.Y + r, z_hi)
    best, best_d = 0, 1e9
    for src in A.sources_of(doc, srcs):
        for fl in (FilteredElementCollector(src.doc)
                   .OfCategory(BuiltInCategory.OST_Floors)
                   .WhereElementIsNotElementType()
                   .WherePasses(BoundingBoxIntersectsFilter(
                       A.source_outline(src, lo, hi)))):
            thk = A._floor_thickness_mm(fl)
            if thk <= INSULATION_MAX_MM:
                continue
            box = A.host_box(fl, src)
            if box is None:
                continue
            nx = min(max(origin.X, box[0]), box[1])
            ny = min(max(origin.Y, box[2]), box[3])
            d = XYZ(nx - origin.X, ny - origin.Y, 0.0).GetLength()
            if d < best_d:
                best, best_d = _bucket(thk, SLAB_TOL_MM), d
    return best


def _side_rank(side):
    """Ранг стороны для правила «выше — справа, при равенстве — толще».

    side = ((thk_bucket, off_bucket), ...), off — верх плиты относительно
    верха элемента: больше off = выше плита."""
    return (max(off for _thk, off in side),
            max(thk for thk, _off in side))


def _node(doc, raw, centroid, srcs=None):
    """Р1.5 (уточнение 04.09.2026): главное — ПЛИТА СПРАВА на самом разрезе.

    raw — бетонная СТОПКА (см. stack_range/кластеризацию): origin в центре
    стопки, z_top/z_bot — весь связный столб, всё в координатах ХОСТА. Плита
    с одной стороны -> взгляд так, чтобы она попала на +right; обе/нет ->
    интерьер справа. Референсы считаются этим же правилом по своему экземпляру.
    """
    origin = raw['origin']
    axis = raw['axis'].Normalize()
    b_mm = raw['b']
    z_top, z_bot = raw['z_top'], raw['z_bot']
    h_mm = mm(z_top - z_bot)
    elem_id = raw['elem_id']
    # ЭКРАННОЕ право при взгляде вдоль +axis = axis x Z (не Z x axis!)
    screen_r = axis.CrossProduct(XYZ.BasisZ).Normalize()
    pad = to_ft(PROBE_ZPAD_MM)
    z_lo, z_hi = z_bot - pad, z_top + pad
    sa = _side_slabs(doc, origin, screen_r, b_mm, z_lo, z_hi, z_top, srcs)
    sb = _side_slabs(doc, origin, screen_r.Negate(), b_mm, z_lo, z_hi, z_top,
                     srcs)
    if sa and not sb:
        view_dir = axis                                # плита уже справа
    elif sb and not sa:
        view_dir = axis.Negate()
        sa, sb = sb, sa                                # стороны в системе взгляда
    elif sa and sb:
        # плиты с ДВУХ сторон (05.09.2026): более ВЫСОКАЯ — справа, при
        # равной высоте — более толстая; правило считается по своим плитам
        # каждого экземпляра, поэтому зеркальные референсы разворачиваются
        ra, rb = _side_rank(sa), _side_rank(sb)
        if rb > ra:
            view_dir = axis.Negate()
            sa, sb = sb, sa
        elif rb == ra:
            view_dir = pick_view_dir(axis, origin, centroid)  # симметрия
            if not view_dir.IsAlmostEqualTo(axis):
                sa, sb = sb, sa
        else:
            view_dir = axis
    else:
        view_dir = pick_view_dir(axis, origin, centroid)
        if not view_dir.IsAlmostEqualTo(axis):
            sa, sb = sb, sa
    if not sa and not sb:
        # зонды пусты — страхуемся толщиной ближайшей плиты по параметру
        ctx = (u'F', _fallback_slab_thk(doc, origin, b_mm, z_lo, z_hi, srcs))
    else:
        ctx = A.canonical_context(sa, sb)
    # утеплитель/полиэш — признак МЕСТА, а не ключа (24.09.2026): из-за него
    # одинаковые узлы делились на пары «с полиэшем / без» и получали лишний
    # разрез. Теперь группа одна; build_groups режет её там, где полиэш есть.
    ins = (_side_ins(doc, origin, screen_r, b_mm, z_lo, z_hi, z_top, srcs) or
           _side_ins(doc, origin, screen_r.Negate(), b_mm, z_lo, z_hi,
                     z_top, srcs))
    # толщины+отметки плит уже в ctx, отдельный v_key не нужен
    key = ('KZ', _bucket(b_mm, B_TOL_MM), _bucket(h_mm, H_TOL_MM), ctx)
    # расширение кропа: +BasisX бокса = Z x view_dir = ЭКРАННОЕ ЛЕВО,
    # поэтому widen_pos отвечает за плиты слева (sb), widen_neg — справа (sa)
    # elem_id — как раньше, ElementId своего документа (сообщения об ошибках);
    # уникальный ключ через документы — 'uid' = Source.key (см. build_groups)
    desc = {'origin': origin, 'view_dir': view_dir, 'axis': axis,
            'b': b_mm, 'h': h_mm, 'ins': ins,
            'y_up': h_mm * 0.5, 'y_down': h_mm * 0.5,
            'widen_pos': bool(sb), 'widen_neg': bool(sa),
            'sides': (sa, sb), 'key': key, 'elem_id': elem_id,
            'uid': raw.get('uid'), 'src': raw.get('src'),
            'label': raw.get('label', u'{}'.format(elem_id))}
    return key, desc


def beam_raw(doc, beam, src=None, srcs=None):
    """Сырой узел балки: стопка бетона в середине пролёта (Р1.4).

    src — источник самой балки (None = хост). Кривая расположения и габарит
    приходят в координатах СВОЕГО документа, поэтому переводятся в хост
    первым же действием; дальше всё считается только в хосте."""
    src = _host_src(doc, src)
    loc = beam.Location
    if not isinstance(loc, LocationCurve):
        return None
    crv = loc.Curve
    p0 = src.to_host(crv.GetEndPoint(0))
    p1 = src.to_host(crv.GetEndPoint(1))
    axis = XYZ(p1.X - p0.X, p1.Y - p0.Y, 0.0)
    if axis.GetLength() < 1e-9:
        return None
    axis = axis.Normalize()
    origin = src.to_host(crv.Evaluate(0.5, True))
    box = A.host_box(beam, src)
    if box is None:
        return None
    b = _elem_width_mm(beam, axis, box)
    # стопка: балка + плита + возможная вторая балка над/под
    z_bot, z_top = stack_range(doc, origin.X, origin.Y, box[4], box[5], srcs)
    return {'origin': XYZ(origin.X, origin.Y, (z_top + z_bot) * 0.5),
            'axis': axis, 'b': b, 'z_top': z_top, 'z_bot': z_bot,
            'elem_id': beam.Id, 'src': src, 'uid': src.key(beam),
            'label': _label(src, beam)}


def wall_lintel_raws(doc, wall, src=None, srcs=None):
    """Сырые узлы перемычек над проёмами стены (центр проёма, Р1.4).

    b = толщина стены; стопка тянется от головы проёма вверх (плита/парапет
    над стеной вливаются через stack_range).

    src — источник стены (None = хост). Ось и габариты переводятся в хост;
    id проёмов из FindInserts принадлежат документу СТЕНЫ, поэтому элемент
    достаётся из wall.Document, а не из хоста."""
    res = []
    src = _host_src(doc, src)
    loc = wall.Location
    if not isinstance(loc, LocationCurve):
        return res
    crv = loc.Curve
    p0 = src.to_host(crv.GetEndPoint(0))
    p1 = src.to_host(crv.GetEndPoint(1))
    axis = XYZ(p1.X - p0.X, p1.Y - p0.Y, 0.0)
    if axis.GetLength() < 1e-9:
        return res
    axis = axis.Normalize()
    wall_box = A.host_box(wall, src)
    if wall_box is None:
        return res
    wall_top = wall_box[5]
    try:
        b = mm(wall.Width)
    except Exception:
        return res
    try:
        inserts = wall.FindInserts(True, False, False, True)
    except Exception:
        inserts = []
    for iid in inserts:
        ins = wall.Document.GetElement(iid)
        if ins is None:
            continue
        if is_mamad_opening(doc, ins, axis, src, srcs):
            continue    # спец-окна ממ"ד — разрез не ставим (решение 04.09.2026)
        box = A.host_box(ins, src)
        if box is None:
            continue
        head_z = box[5]
        if mm(wall_top - head_z) < MIN_LINTEL_MM:
            continue
        cx, cy = (box[0] + box[1]) * 0.5, (box[2] + box[3]) * 0.5
        z_bot, z_top = stack_range(doc, cx, cy, head_z, wall_top, srcs)
        z_bot = max(z_bot, head_z)   # под проём не спускаемся
        res.append({'origin': XYZ(cx, cy, (z_top + z_bot) * 0.5),
                    'axis': axis, 'b': b, 'z_top': z_top, 'z_bot': z_bot,
                    'elem_id': wall.Id, 'src': src, 'uid': src.key(wall),
                    'label': _label(src, wall)})
    return res


def build_groups(doc, beams, walls, centroid, srcs=None):
    """Группировка по ключу Р1.1. Возвращает (groups: key->{desc,members}, errors).

    Сначала сырые узлы-стопки, затем кластеризация совпадающих по месту
    (две балки одной стопки = ОДИН узел, одна марка — фидбек 05.09.2026),
    затем ключи и группы. members — desc'и для референсов.

    beams/walls — либо элементы ХОСТА (старый вызов), либо пары
    (элемент, источник): каждый элемент читается своим источником и сразу
    переводится в координаты хоста, так что кластеризация и ключи мешают
    хост и связи в одном пространстве.
    """
    srcs = A.sources_of(doc, srcs)
    host = srcs[0]
    groups, errors = {}, []
    order = []
    raws = []
    for b, bsrc in _pairs(beams, host):
        try:
            r = beam_raw(doc, b, bsrc, srcs)
            if r is None:
                errors.append(u'{}: beam without a location line / extents'
                              .format(_label(bsrc, b)))
            else:
                raws.append(r)
        except Exception as e:
            errors.append(u'{}: {}'.format(_label(bsrc, b), e))
    for w, wsrc in _pairs(walls, host):
        try:
            raws.extend(wall_lintel_raws(doc, w, wsrc, srcs))
        except Exception as e:
            errors.append(u'{}: {}'.format(_label(wsrc, w), e))
    # кластеризация: один узел на стопку (совпадает ось, XY < 400 мм,
    # диапазоны высот пересекаются с допуском 300 мм)
    clusters = []
    for r in raws:
        hit = None
        for cl in clusters:
            if abs(r['axis'].DotProduct(cl['axis'])) < 0.95:
                continue
            dxy = XYZ(r['origin'].X - cl['origin'].X,
                      r['origin'].Y - cl['origin'].Y, 0.0).GetLength()
            if dxy >= to_ft(400.0):
                continue
            if r['z_bot'] > cl['z_top'] + to_ft(300.0):
                continue
            if r['z_top'] < cl['z_bot'] - to_ft(300.0):
                continue
            hit = cl
            break
        if hit is None:
            clusters.append(dict(r))
        else:
            hit['b'] = max(hit['b'], r['b'])
            hit['z_top'] = max(hit['z_top'], r['z_top'])
            hit['z_bot'] = min(hit['z_bot'], r['z_bot'])
    nodes = []
    for cl in clusters:
        o = cl['origin']
        cl['origin'] = XYZ(o.X, o.Y, (cl['z_top'] + cl['z_bot']) * 0.5)
        try:
            nodes.append(_node(doc, cl, centroid, srcs))
        except Exception as e:
            errors.append(u'{}: {}'.format(cl.get('label', cl['elem_id']), e))
    for key, desc in nodes:
        if key not in groups:
            groups[key] = {'desc': desc, 'members': [desc]}
            order.append(key)
        else:
            groups[key]['members'].append(desc)
    # полиэш: отдельного разреза НЕ даёт, но если он есть хоть у одного члена
    # группы — единственный разрез группы ставим в таком месте, чтобы полиэш
    # попал на чертёж; остальные места (с ним и без) — референсы
    for key in order:
        g = groups[key]
        g['ins_count'] = len([m for m in g['members'] if m.get('ins')])
        if g['ins_count'] and not g['desc'].get('ins'):
            rep = [m for m in g['members'] if m.get('ins')][0]
            g['members'].remove(rep)
            g['members'].insert(0, rep)
            g['desc'] = rep
    return groups, order, errors


# ------------------------------------------------------- похожие (RefBracket)

def similarity_plan(groups, order):
    """{similar_key: master_key} по ТЗ M4 (05.09.2026): SIMILAR = равно всё
    (высота стопки, отметки плит), КРОМЕ ширины балки и/или толщин
    прилегающих плит. Мастер кластера — наименьшая толщина плиты,
    затем наименьшая ширина; похожие получают dummy «(N)» вместо разреза.
    Полиэш/утеплитель в ключ не входит с 24.09.2026."""
    def strip(key):
        ctx = key[3]
        if len(ctx) == 2 and ctx[0] == u'F':
            offs = (u'F',)
        else:
            offs = tuple(tuple(off for _t, off in side) for side in ctx)
        return (key[2], offs)

    def thick_rank(key):
        ctx = key[3]
        th = []
        if len(ctx) == 2 and ctx[0] == u'F':
            th = [ctx[1]]
        else:
            for side in ctx:
                th.extend(t for t, _o in side)
        return (tuple(sorted(th)), key[1])

    clusters, corder = {}, []
    for k in order:
        s = strip(k)
        if s not in clusters:
            clusters[s] = []
            corder.append(s)
        clusters[s].append(k)
    plan = {}
    for s in corder:
        ks = clusters[s]
        if len(ks) < 2:
            continue
        master = min(ks, key=thick_rank)
        for k in ks:
            if k != master:
                plan[k] = master
    return plan


def sim_diff_data(master_key, sim_keys):
    """Различия похожих групп: (plate_txt, b_txt) в СМ, для текста «(…)»
    под размерами мастера (фидбек 05.09.2026: скобочное значение — в самом
    размере: плита «20», под ней «(22)»). None — если не отличается."""
    def thks(key):
        ctx = key[3]
        if len(ctx) == 2 and ctx[0] == u'F':
            return [ctx[1]]
        out = []
        for side in ctx:
            out.extend(t for t, _o in side)
        return sorted(out)

    mt, mb = thks(master_key), master_key[1]
    plate_pairs, b_pairs = [], []
    for sk in sim_keys:
        st = thks(sk)
        if st != mt:
            ms = sorted([t for t in mt if t not in st])
            ss = sorted([t for t in st if t not in mt])
            for a, b2 in zip(ms, ss):
                pr = (u'{:g}'.format(a / 10.0), u'{:g}'.format(b2 / 10.0))
                if pr not in plate_pairs:
                    plate_pairs.append(pr)
        if sk[1] != mb:
            pr = (u'{:g}'.format(mb / 10.0), u'{:g}'.format(sk[1] / 10.0))
            if pr not in b_pairs:
                b_pairs.append(pr)
    plate_txt = (u','.join(u'{}>{}'.format(a, b2) for a, b2 in plate_pairs)
                 if plate_pairs else None)
    b_txt = (u','.join(u'{}>{}'.format(a, b2) for a, b2 in b_pairs)
             if b_pairs else None)
    return plate_txt, b_txt


# ----------------------------------------------------------- повторный запуск

def existing_kz_sections(doc, prefix):
    """Существующие разрезы этого инструмента: имя начинается с '{prefix}_S'."""
    res = []
    pat = u'{}_S'.format(prefix)
    for v in FilteredElementCollector(doc).OfClass(ViewSection):
        try:
            if not v.IsTemplate and v.Name.startswith(pat):
                res.append(v)
        except Exception:
            pass
    return res


def group_covered_by(existing, members):
    """Вид, уже покрывающий группу: какой-то её член лежит в плоскости реза
    существующего разреза (норм. расстояние < 300 мм, оси параллельны,
    смещение вдоль плоскости < 4 м). Иначе None."""
    for v in existing:
        try:
            vo = v.Origin
            n = v.ViewDirection      # нормаль плоскости реза (знак не важен)
        except Exception:
            continue
        for m in members:
            o = m['origin']
            dv = XYZ(o.X - vo.X, o.Y - vo.Y, o.Z - vo.Z)
            if abs(dv.DotProduct(n)) > to_ft(300.0):
                continue
            if abs(m['axis'].DotProduct(n)) < 0.9:
                continue
            flat = XYZ(dv.X, dv.Y, 0.0)
            lat = (flat - n * flat.DotProduct(n)).GetLength()
            if lat < to_ft(4000.0):
                return v
    return None


def delete_views(doc, views, prefix=None):
    """Удалить виды И их референс-маркеры.

    Ловушка (05.09.2026): реф-маркер на плане — отдельный элемент категории
    Views с валидным OwnerViewId; при удалении вида Revit его НЕ удаляет —
    оставались сироты со старыми номерами («по 2 обозначения, причём
    разных»). Чистим маркеры по имени вида / префиксу до удаления видов.
    Собственный маркер вида имеет OwnerViewId = Invalid и умирает с видом.
    """
    count, errors = 0, []
    names, vids = set(), set()
    for v in views:
        try:
            names.add(v.Name)
            vids.add(v.Id.IntegerValue)
        except Exception:
            pass
    t = Transaction(doc, u'Delete old sections')
    t.Start()
    try:
        ref_ids = []
        for el in (FilteredElementCollector(doc)
                   .OfCategory(BuiltInCategory.OST_Views)
                   .WhereElementIsNotElementType()):
            try:
                if el.Id.IntegerValue in vids:
                    continue
                if el.OwnerViewId == ElementId.InvalidElementId:
                    continue          # собственный маркер вида
                nm = getattr(el, 'Name', u'') or u''
                if nm in names or (prefix and
                                   nm.startswith(u'{}_S'.format(prefix))):
                    ref_ids.append(el.Id)
            except Exception:
                pass
        for rid in ref_ids:
            try:
                doc.Delete(rid)
                count += 1
            except Exception:
                pass
        for v in views:
            try:
                doc.Delete(v.Id)
                count += 1
            except Exception as e:
                errors.append(u'delete {}: {}'.format(v.Id, e))
        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise
    return count, errors


# ----------------------------------------------------------------- создание видов

def _find_template(doc, name):
    for v in FilteredElementCollector(doc).OfClass(ViewSection):
        try:
            if v.IsTemplate and v.Name == name:
                return v
        except Exception:
            pass
    return None


def create_sections(doc, vft_id, groups, order, template_name=TEMPLATE_NAME):
    """Один настоящий разрез на группу (Р1.4-Р1.6, Р1.12). Возвращает (created, errors).

    created: [{'view', 'desc', 'members'}] в порядке появления групп.
    """
    created, errors = [], []
    tpl = _find_template(doc, template_name)
    t = Transaction(doc, u'Create unique sections')
    t.Start()
    try:
        for key in order:
            info = groups[key]
            d = info['desc']
            try:
                b_half = d['b'] * 0.5
                x_pos = b_half + (SEC_SLAB_WIDEN_MM if d['widen_pos'] else SEC_MARGIN_MM)
                x_neg = b_half + (SEC_SLAB_WIDEN_MM if d['widen_neg'] else SEC_MARGIN_MM)
                y_up = d.get('y_up', d['h'] * 0.5) + SEC_MARGIN_MM
                y_down = d.get('y_down', d['h'] * 0.5) + SEC_MARGIN_MM
                box = G.make_section_box(d['origin'], d['view_dir'],
                                         x_neg, x_pos, y_down, y_up,
                                         FAR_CLIP_MM * 0.5)
                view = ViewSection.CreateSection(doc, vft_id, box)
                try:
                    view.Scale = VIEW_SCALE
                except Exception:
                    pass
                fp = view.get_Parameter(BuiltInParameter.VIEWER_BOUND_OFFSET_FAR)
                if fp and not fp.IsReadOnly:
                    fp.Set(to_ft(FAR_CLIP_MM))
                if tpl is not None:
                    try:
                        view.ViewTemplateId = tpl.Id
                    except Exception as e:
                        errors.append(u'template {}: {}'.format(view.Id, e))
                created.append({'view': view, 'desc': d,
                                'members': info['members']})
            except Exception as e:
                errors.append(u'group {}: {}'.format(d['elem_id'], e))
        if tpl is None:
            errors.append(u'view template "{}" not found - no template assigned'
                          .format(template_name))
        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise
    return created, errors


# ----------------------------------------------------------------- референсы (Р1.7)

def create_references(doc, plan_view, created):
    """Референс-маркер на каждом дубликате, направление — по правилу Р1.5
    самого дубликата (зеркальные случаи получают противоположный взгляд)."""
    z = plan_view.GenLevel.Elevation if plan_view.GenLevel else None
    count, errors = 0, []
    t = Transaction(doc, u'Reference sections')
    t.Start()
    try:
        for entry in created:
            rep = entry['desc']
            for m in entry['members']:
                if m is rep:
                    continue
                try:
                    o = m['origin']
                    zz = z if z is not None else o.Z
                    c = XYZ(o.X, o.Y, zz)
                    # Конвенция API (выведена на 150_S23, 04.09.2026):
                    # взгляд маркера = Z x (tail - head)  =>  tail - head = look x Z.
                    along = m['view_dir'].CrossProduct(XYZ.BasisZ).Normalize()
                    half = to_ft(m['b'] * 0.5 + 400.0) * MARKER_LOOK_SIGN
                    head = c - along * half
                    tail = c + along * half
                    ViewSection.CreateReferenceSection(
                        doc, plan_view.Id, entry['view'].Id, head, tail)
                    count += 1
                except Exception as e:
                    errors.append(u'reference {}: {}'.format(m['elem_id'], e))
        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise
    return count, errors


# ----------------------------------------------------------------- лист (Р4)

def _detail_numbers(doc, sheet):
    nums = set()
    for vp_id in sheet.GetAllViewports():
        vp = doc.GetElement(vp_id)
        p = vp.get_Parameter(BuiltInParameter.VIEWPORT_DETAIL_NUMBER)
        if p and p.AsString():
            try:
                nums.add(int(p.AsString()))
            except Exception:
                pass
    return nums


FORBIDDEN_NUMS = (6, 9)   # не используются: переворачиваются на листе


def _next_free(nums, start=1):
    n = start
    while n in nums or n in FORBIDDEN_NUMS:
        n += 1
    nums.add(n)
    return n


def _existing_outline(doc, sheet):
    """(min_x, min_y, max_x, max_y) существующих вьюпортов в футах, или None."""
    lo_x = lo_y = hi_x = hi_y = None
    for vp_id in sheet.GetAllViewports():
        vp = doc.GetElement(vp_id)
        try:
            o = vp.GetBoxOutline()
        except Exception:
            continue
        mn, mx = o.MinimumPoint, o.MaximumPoint
        if lo_x is None or mn.X < lo_x:
            lo_x = mn.X
        if lo_y is None or mn.Y < lo_y:
            lo_y = mn.Y
        if hi_x is None or mx.X > hi_x:
            hi_x = mx.X
        if hi_y is None or mx.Y > hi_y:
            hi_y = mx.Y
    if lo_x is None:
        return None
    return lo_x, lo_y, hi_x, hi_y


LABEL_GAP_MM = 5.0     # от низа самого глубокого разреза ряда до подписи
LABEL_BAND_MM = 10.0   # высота зоны подписи (для шага к следующему ряду)


ALIGN_LABELS = True   # False = вообще не трогать подписи (аварийный тумблер)


def _align_labels_all(doc, jobs, errors):
    """Подписи ВСЕХ вьюпортов листа за ОДНУ регенерацию + один проход.

    jobs: [{'vp','view','w','cx','label_y'}]. Пер-вьюпортные Regenerate
    вешали Revit («подвис» 05.09.2026) — теперь одна на весь лист."""
    if not ALIGN_LABELS or not jobs:
        return
    for it in jobs:
        try:
            it['vp'].LabelLineLength = it['w']
        except Exception:
            pass
    try:
        doc.Regenerate()
    except Exception:
        return
    for it in jobs:
        vp = it['vp']
        try:
            lo = vp.GetLabelOutline()
            cur_cx = (lo.MinimumPoint.X + lo.MaximumPoint.X) * 0.5
            cur_y = lo.MaximumPoint.Y
        except Exception as e:
            errors.append(u'{}: label: {}'.format(it['view'].Name, e))
            continue
        dx = it['cx'] - cur_cx
        dy = it['label_y'] - cur_y
        if abs(dx) < to_ft(0.5) and abs(dy) < to_ft(0.5):
            continue
        try:
            off = vp.LabelOffset
            vp.LabelOffset = XYZ(off.X + dx, off.Y + dy, 0)
        except Exception as e:
            errors.append(u'{}: LabelOffset: {}'.format(it['view'].Name, e))


def place_on_sheet(doc, sheet, created, prefix, datum_z=None):
    """Р4 + выравнивание (05.09.2026): в ряду все разрезы стоят так, что
    ОТМЕТКА УРОВНЯ (datum_z, верх перекрытия) лежит на одной линии листа,
    а подписи вьюпортов — на другой общей линии под самым глубоким
    разрезом ряда. Detail Number = следующий свободный; имя '{prefix}_S{n}'."""
    placed, errors = [], []
    gap = to_ft(ROW_GAP_MM)
    vgap = to_ft(ROW_VGAP_MM)
    max_w = to_ft(ROW_MAX_W_MM)
    lbl_gap = to_ft(LABEL_GAP_MM)
    lbl_band = to_ft(LABEL_BAND_MM)

    ext = _existing_outline(doc, sheet)
    if ext is not None:
        start_x, start_y = ext[0], ext[1] - vgap   # под самым нижним контентом
    else:
        start_x, start_y = to_ft(100.0), to_ft(500.0)

    t = Transaction(doc, u'Sections on sheet')
    t.Start()
    try:
        nums = _detail_numbers(doc, sheet)
        # фаза 1: создать вьюпорты, номера/имена, метрики выравнивания
        items = []
        for entry in created:
            view = entry['view']
            if not Viewport.CanAddViewToSheet(doc, sheet.Id, view.Id):
                errors.append(u'{}: cannot be placed on the sheet'.format(view.Name))
                continue
            vp = Viewport.Create(doc, sheet.Id, view.Id, XYZ(0, 0, 0))
            o = vp.GetBoxOutline()
            w = o.MaximumPoint.X - o.MinimumPoint.X
            cb = view.CropBox
            scale = float(view.Scale)
            yc = (cb.Min.Y + cb.Max.Y) * 0.5
            if datum_z is not None:
                T = cb.Transform
                yd = T.Inverse.OfPoint(
                    XYZ(T.Origin.X, T.Origin.Y, datum_z)).Y
            else:
                yd = yc
            n = _next_free(nums)
            p = vp.get_Parameter(BuiltInParameter.VIEWPORT_DETAIL_NUMBER)
            if p and not p.IsReadOnly:
                try:
                    p.Set(str(n))
                except Exception as e:
                    errors.append(u'{}: detail number: {}'.format(view.Name, e))
            base = u'{}_S{}'.format(prefix, n)
            name, suffix = base, 1
            while True:
                try:
                    view.Name = name
                    break
                except Exception:
                    name = u'{}_{}'.format(base, suffix)
                    suffix += 1
                    if suffix > 50:
                        break
            items.append({'vp': vp, 'view': view, 'w': w,
                          'above': (cb.Max.Y - yd) / scale,
                          'below': (yd - cb.Min.Y) / scale,
                          'yc': yc, 'yd': yd, 'scale': scale, 'num': n})
        # фаза 2: разбить на ряды по ширине
        rows, cur, cw = [], [], 0.0
        for it in items:
            if cur and cw + it['w'] > max_w:
                rows.append(cur)
                cur, cw = [], 0.0
            cur.append(it)
            cw += it['w'] + gap
        if cur:
            rows.append(cur)
        # фаза 3: позиции — датум ряда и линия подписей общие
        y_cursor = start_y
        label_jobs = []
        for row in rows:
            max_above = max(it['above'] for it in row)
            max_below = max(it['below'] for it in row)
            datum_y = y_cursor - max_above
            label_y = datum_y - max_below - lbl_gap
            x = start_x
            for it in row:
                cx = x + it['w'] * 0.5
                it['cx'] = cx
                it['label_y'] = label_y
                cy = datum_y + (it['yc'] - it['yd']) / it['scale']
                try:
                    it['vp'].SetBoxCenter(XYZ(cx, cy, 0))
                except Exception as e:
                    errors.append(u'{}: position: {}'.format(
                        it['view'].Name, e))
                x += it['w'] + gap
                placed.append({'view': it['view'], 'number': it['num']})
                label_jobs.append(it)
            y_cursor = label_y - lbl_band - vgap
        _align_labels_all(doc, label_jobs, errors)
        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise
    return placed, errors
