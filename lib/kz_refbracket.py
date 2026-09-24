# -*- coding: utf-8 -*-
"""kz_refbracket — dummy-виды для скобочных референсов «(N)». V1: M1+M2.

Схема (ТЗ пользователя 05.09.2026): похожие сечения (та же балка/отметки,
другая толщина прилегающей плиты) НЕ получают свой разрез — референс ведёт
на невидимый dummy-дубликат официального разреза, чей Detail Number = «(N)»
на том же листе. Официальный разрез несёт оформление для обоих вариантов.

Механика dummy:
    * View.Duplicate (без детализации), имя «<имя>#REF» (+_2 при коллизии);
    * шаблон «PEER-DUMMY-REF» (все категории выключены, создаётся при
      первом запуске), кроп ~2x2 см, annotation crop выкл;
    * «Hide at scales coarser than» = 1:2 -> собственный маркер dummy
      не виден на планах (держится ВНЕ шаблона — у оригиналов свои);
    * viewport на ТОМ ЖЕ листе, тип «Dummy (no title)» (Show Title=No),
      Detail Number = «(N)», запинен, в угол titleblock.

Ловушки учтены: без рекурсии, транзакции короткие, пачки <= 25, номер
валидируется до записи, после коммита изменённое выделяется.
"""

from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, BuiltInParameter, ElementId,
    Transaction, View, ViewSection, ViewDuplicateOption, Viewport, XYZ,
    ElementType, ReferenceableViewUtils,
)
from System.Collections.Generic import List

FT_MM = 304.8
DUMMY_SUFFIX = u'#REF'
TEMPLATE_NAME = u'PEER-DUMMY-REF'
VP_TYPE_NAME = u'Dummy (no title)'
DUMMY_CROP_MM = 20.0      # ~2x2 см
CORNER_OFF_MM = 5.0       # от угла titleblock
STACK_STEP_MM = 10.0      # сдвиг следующих dummy, чтобы не штабелевались
BATCH = 25


def to_ft(v):
    return v / FT_MM


# ------------------------------------------------------------------ поиск

def find_view_by_name(doc, name):
    for v in FilteredElementCollector(doc).OfClass(View):
        try:
            if not v.IsTemplate and v.Name == name:
                return v
        except Exception:
            pass
    return None


def viewport_of(doc, view):
    """Viewport вида (или None). Возвращает (viewport, sheet)."""
    for vp in FilteredElementCollector(doc).OfClass(Viewport):
        try:
            if vp.ViewId == view.Id:
                return vp, doc.GetElement(vp.SheetId)
        except Exception:
            pass
    return None, None


def detail_number(vp):
    p = vp.get_Parameter(BuiltInParameter.VIEWPORT_DETAIL_NUMBER)
    return p.AsString() if p and p.AsString() else u''


def sheet_numbers(doc, sheet):
    used = set()
    for vp_id in sheet.GetAllViewports():
        vp = doc.GetElement(vp_id)
        n = detail_number(vp)
        if n:
            used.add(n)
    return used


def dummy_of(doc, view):
    """Существующий dummy для вида (имя начинается с '<имя>#REF')."""
    base = view.Name + DUMMY_SUFFIX
    for v in FilteredElementCollector(doc).OfClass(View):
        try:
            if not v.IsTemplate and v.Name.startswith(base):
                return v
        except Exception:
            pass
    return None


def original_of(doc, dummy):
    """Оригинал по dummy: имя до '#REF'."""
    nm = dummy.Name
    i = nm.find(DUMMY_SUFFIX)
    if i < 0:
        return None
    return find_view_by_name(doc, nm[:i])


def is_dummy(view):
    return DUMMY_SUFFIX in (view.Name or u'')


# ------------------------------------------------------- первый запуск: типы

def ensure_template(doc, sample_view, log):
    """Шаблон PEER-DUMMY-REF: все категории модели и аннотаций выключены."""
    for v in FilteredElementCollector(doc).OfClass(View):
        try:
            if v.IsTemplate and v.Name == TEMPLATE_NAME:
                return v
        except Exception:
            pass
    res = sample_view.CreateViewTemplate()
    # в Revit 2024 CreateViewTemplate возвращает сам View-шаблон,
    # в других версиях — ElementId
    tmpl = res if isinstance(res, View) else doc.GetElement(res)
    try:
        tmpl.Name = TEMPLATE_NAME
    except Exception:
        pass
    hidden = 0
    for cat in doc.Settings.Categories:
        try:
            if tmpl.CanCategoryBeHidden(cat.Id):
                tmpl.SetCategoryHidden(cat.Id, True)
                hidden += 1
        except Exception:
            pass
    log.append(u'created template {} (categories hidden: {})'.format(
        TEMPLATE_NAME, hidden))
    return tmpl


def ensure_vp_type(doc, sample_vp, log):
    """Тип видового экрана «Dummy (no title)»: заголовок и линия выключены."""
    for t in FilteredElementCollector(doc).OfClass(ElementType):
        try:
            if t.FamilyName == u'Viewport' and \
                    t.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM) and \
                    t.get_Parameter(
                        BuiltInParameter.SYMBOL_NAME_PARAM).AsString() == \
                    VP_TYPE_NAME:
                return t
        except Exception:
            pass
    base = doc.GetElement(sample_vp.GetTypeId())
    new_t = base.Duplicate(VP_TYPE_NAME)
    ok = False
    p = new_t.get_Parameter(BuiltInParameter.VIEWPORT_ATTR_SHOW_LABEL)
    if p and not p.IsReadOnly:
        for val in (2, 0):        # enum Show Title: пробуем «No»
            try:
                p.Set(val)
                ok = True
                break
            except Exception:
                pass
    p = new_t.get_Parameter(
        BuiltInParameter.VIEWPORT_ATTR_SHOW_EXTENSION_LINE)
    if p and not p.IsReadOnly:
        try:
            p.Set(0)
        except Exception:
            pass
    log.append(u'created viewport type {}{}'.format(
        VP_TYPE_NAME, u'' if ok else u' (check Show Title manually - P2)'))
    return new_t


# ------------------------------------------------------------------ M1

def create_dummy(doc, view, log):
    """M1: dummy для реального разреза view. Возвращает (dummy, viewport)."""
    vp, sheet = viewport_of(doc, view)
    if vp is None:
        log.append(u'{}: view is not placed on a sheet'.format(view.Name))
        return None, None
    n = detail_number(vp)
    if not n:
        log.append(u'{}: viewport has no Detail Number'.format(view.Name))
        return None, None
    existing = dummy_of(doc, view)
    if existing is not None:
        log.append(u'{}: dummy already exists - {}'.format(view.Name,
                                                     existing.Name))
        return existing, None
    target_num = u'({})'.format(n)
    if target_num in sheet_numbers(doc, sheet):
        log.append(u'{}: number {} is taken on the sheet'.format(view.Name,
                                                         target_num))
        return None, None

    dummy = doc.GetElement(view.Duplicate(ViewDuplicateOption.Duplicate))
    base = view.Name + DUMMY_SUFFIX
    name, suf = base, 2
    while True:
        try:
            dummy.Name = name
            break
        except Exception:
            name = u'{}_{}'.format(base, suf)
            suf += 1
            if suf > 20:
                break
    # кроп ~2x2 см, annotation crop выкл — ДО шаблона (шаблон не держит кроп)
    try:
        cb = dummy.CropBox
        c = to_ft(DUMMY_CROP_MM * 0.5)
        zc = (cb.Min.Y + cb.Max.Y) * 0.5
        cb.Min = XYZ(-c, zc - c, cb.Min.Z)
        cb.Max = XYZ(c, zc + c, cb.Max.Z)
        dummy.CropBox = cb
        dummy.CropBoxActive = True
        dummy.CropBoxVisible = False
    except Exception as e:
        log.append(u'dummy crop: {}'.format(e))
    p = dummy.get_Parameter(BuiltInParameter.VIEWER_ANNOTATION_CROP_ACTIVE)
    if p and not p.IsReadOnly:
        try:
            p.Set(0)
        except Exception:
            pass
    # Hide at scales coarser than 1:2 — ВНЕ шаблона (ловушка 7, проверка П1)
    for bip in (BuiltInParameter.SECTION_COARSER_SCALE_PULLDOWN_METRIC,
                BuiltInParameter.SECTION_COARSER_SCALE_PULLDOWN_IMPERIAL):
        p = dummy.get_Parameter(bip)
        if p and not p.IsReadOnly:
            try:
                p.Set(2)
                break
            except Exception:
                pass
    tmpl = ensure_template(doc, dummy, log)
    try:
        dummy.ViewTemplateId = tmpl.Id
    except Exception as e:
        log.append(u'dummy template: {}'.format(e))
    # viewport в угол titleblock того же листа
    pt = XYZ(to_ft(CORNER_OFF_MM), to_ft(CORNER_OFF_MM), 0)
    for tb in (FilteredElementCollector(doc, sheet.Id)
               .OfCategory(BuiltInCategory.OST_TitleBlocks)
               .WhereElementIsNotElementType()):
        bb = tb.get_BoundingBox(sheet)
        if bb is not None:
            k = 0
            for v2 in FilteredElementCollector(doc).OfClass(View):
                try:
                    if not v2.IsTemplate and DUMMY_SUFFIX in v2.Name:
                        k += 1
                except Exception:
                    pass
            pt = XYZ(bb.Min.X + to_ft(CORNER_OFF_MM + k * STACK_STEP_MM),
                     bb.Min.Y + to_ft(CORNER_OFF_MM), 0)
        break
    dvp = Viewport.Create(doc, sheet.Id, dummy.Id, pt)
    vpt = ensure_vp_type(doc, vp, log)
    try:
        dvp.ChangeTypeId(vpt.Id)
    except Exception as e:
        log.append(u'viewport type: {}'.format(e))
    p = dvp.get_Parameter(BuiltInParameter.VIEWPORT_DETAIL_NUMBER)
    if p and not p.IsReadOnly:
        try:
            p.Set(target_num)
        except Exception as e:
            log.append(u'number {}: {}'.format(target_num, e))
    try:
        dvp.Pinned = True
    except Exception:
        pass
    log.append(u'{}: dummy {} -> "{}" on sheet {}'.format(
        view.Name, dummy.Name, target_num, sheet.SheetNumber))
    return dummy, dvp


# ------------------------------------------------------------------ M2

def is_ref_marker(el):
    p = el.get_Parameter(BuiltInParameter.VIEWER_IS_REFERENCE)
    return bool(p and p.HasValue and p.AsInteger() == 1)


def toggle_markers(doc, markers, log):
    """M2: референс на оригинал -> на dummy «(N)»; на dummy -> обратно.
    Возвращает (toggled_ids, need_dummy: [вид]) — dummy создаёт вызывающий."""
    toggled = []
    for el in markers:
        nm = getattr(el, 'Name', u'') or u''
        target = find_view_by_name(doc, nm)
        if target is None:
            log.append(u'marker {}: view "{}" not found'.format(
                el.Id.IntegerValue, nm))
            continue
        if is_dummy(target):
            orig = original_of(doc, target)
            if orig is None:
                log.append(u'marker {}: original for {} not found'.format(
                    el.Id.IntegerValue, nm))
                continue
            new_view = orig
        else:
            dmy = dummy_of(doc, target)
            if dmy is None:
                log.append(u'marker {}: "{}" has no dummy - create it (M1)'.format(
                    el.Id.IntegerValue, nm))
                continue
            new_view = dmy
        try:
            ReferenceableViewUtils.ChangeReferencedView(doc, el.Id,
                                                        new_view.Id)
            toggled.append(el.Id)
            log.append(u'marker {}: -> {}'.format(el.Id.IntegerValue,
                                                  new_view.Name))
        except Exception as e:
            log.append(u'marker {}: {}'.format(el.Id.IntegerValue, e))
    return toggled
