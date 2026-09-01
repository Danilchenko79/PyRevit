# -*- coding: utf-8 -*-
"""
ColorTag by View Filters
==================================================
Description:
Красит теги (IndependentTag) на активном виде цветами, взятыми
из ФИЛЬТРОВ этого вида (View Filters).

Логика:
1) Собираем фильтры активного вида в их порядке (если V/G Filters заданы
   шаблоном вида - берём фильтры из шаблона).
2) Для каждого фильтра читаем OverrideGraphicSettings вида и достаём цвет
   (Projection Lines -> Cut Lines -> Surface Pattern -> Cut Pattern).
3) Для каждого тега находим элемент-хост и проверяем, под какой фильтр он
   попадает. Первый подошедший по порядку списка фильтров - выигрывает.
4) Ставим тегу Projection Line Color = цвет этого фильтра.
"""

__title__ = "ColorTag"
__author__ = "BIM Specialist"

import os, sys, math, datetime, time                                    # Regular Imports
from Autodesk.Revit.DB import *                                         # Import everything from DB (Very good for beginners)
from Autodesk.Revit.DB import (
    FilteredElementCollector,
    BuiltInCategory,
    OverrideGraphicSettings,
    Color,
    Transaction,
    ElementId,
    IndependentTag,
    ParameterFilterElement,
    SelectionFilterElement
)
from Autodesk.Revit.UI import TaskDialog
from Autodesk.Revit.UI.Selection import Selection
from Autodesk.Revit.UI.Selection import ObjectType

# pyRevit
from pyrevit import revit, forms                                        # import pyRevit modules. (Lots of useful features)

# .NET Imports
import clr                                  # Common Language Runtime. Makes .NET libraries accessinble
clr.AddReference("System")                  # Refference System.dll for import.
from System.Collections.Generic import List # List<ElementType>() <- it's special type of list from .NET framework that RevitAPI requires


doc   = __revit__.ActiveUIDocument.Document   #type:Document
uidoc = __revit__.ActiveUIDocument            #type:UIDocument
app   = __revit__.Application                 # Represents the Autodesk Revit Application, providing access to documents, options and other application wide data and settings.


# ============================================================ НАСТРОЙКИ
CLEAR_UNMATCHED     = True   # сбрасывать переопределения у тегов, не попавших ни в один фильтр
SKIP_HIDDEN_FILTERS = True   # игнорировать фильтры, выключенные на виде (Visibility = off)
MATCH_TAG_ITSELF    = True   # если хост не подошёл - пробуем прогнать через фильтры сам тег
LIMIT_CATEGORY      = None   # напр. BuiltInCategory.OST_DetailComponents - ограничить хосты. None = без ограничения


# ============================================================ ХЕЛПЕРЫ

def get_tagged_elements(doc, tag):
    """Возвращает список элементов, к которым привязан тег (новый и старый API)."""
    elems = []
    try:
        getter = getattr(tag, "GetTaggedLocalElementIds", None)
        if getter:
            for eid in getter():
                e = doc.GetElement(eid)
                if e is not None:
                    elems.append(e)
    except:
        pass

    if not elems:
        try:
            tagged_id = getattr(tag, "TaggedElementId", None)
            if tagged_id:
                e = doc.GetElement(tag.TaggedElementId.ElementId)
                if e is not None:
                    elems.append(e)
        except:
            pass

    return elems


def get_view_for_filters(view):
    """
    Возвращает вид, из которого читать фильтры.
    Если у вида фильтров нет, а шаблон назначен - читаем из шаблона.
    """
    try:
        if list(view.GetFilters()):
            return view
    except:
        return view

    try:
        tpl_id = view.ViewTemplateId
        if tpl_id is not None and tpl_id != ElementId.InvalidElementId:
            tpl = doc.GetElement(tpl_id)
            if tpl is not None and list(tpl.GetFilters()):
                return tpl
    except:
        pass

    return view


def get_ordered_filter_ids(view):
    """Фильтры вида в порядке списка (первый в списке имеет приоритет)."""
    try:
        ordered = getattr(view, "GetOrderedFilters", None)
        if ordered:
            return list(ordered())
    except:
        pass
    try:
        return list(view.GetFilters())
    except:
        return []


def get_color_from_ogs(ogs):
    """Достаём цвет из переопределений фильтра по приоритету."""
    if ogs is None:
        return None

    candidates = [
        "ProjectionLineColor",
        "CutLineColor",
        "SurfaceForegroundPatternColor",
        "CutForegroundPatternColor",
        "SurfaceBackgroundPatternColor",
        "CutBackgroundPatternColor",
        "ProjectionFillColor",              # старые версии API (до 2019)
        "CutFillColor",
    ]

    for name in candidates:
        try:
            col = getattr(ogs, name, None)
            if col is not None and col.IsValid:
                return col
        except:
            continue

    return None


def collect_filters(view):
    """
    Список словарей {'name', 'element', 'color'} -
    только фильтры, у которых задан валидный цвет.
    """
    src_view = get_view_for_filters(view)
    result   = []

    for fid in get_ordered_filter_ids(src_view):
        f_elem = doc.GetElement(fid)
        if f_elem is None:
            continue

        if SKIP_HIDDEN_FILTERS:
            try:
                if not src_view.GetFilterVisibility(fid):
                    continue
            except:
                pass

        try:
            ogs = src_view.GetFilterOverrides(fid)
        except:
            ogs = None

        color = get_color_from_ogs(ogs)
        if color is None:
            continue                        # фильтр без цвета - нечем красить

        result.append({
            "name":    f_elem.Name,
            "element": f_elem,
            "color":   color,
        })

    return result


def element_passes_filter(f_elem, elem):
    """Попадает ли элемент под фильтр (категории + правила)."""
    if elem is None:
        return False

    # Фильтр по выбору (Selection Filter)
    if isinstance(f_elem, SelectionFilterElement):
        try:
            for eid in f_elem.GetElementIds():
                if eid == elem.Id:
                    return True
        except:
            pass
        return False

    if not isinstance(f_elem, ParameterFilterElement):
        return False

    # Категории фильтра
    try:
        cats = list(f_elem.GetCategories())
        if cats:
            if elem.Category is None:
                return False
            ok_cat = False
            for c in cats:
                if c == elem.Category.Id:
                    ok_cat = True
                    break
            if not ok_cat:
                return False
    except:
        pass

    # Правила фильтра
    try:
        el_filter = f_elem.GetElementFilter()
    except:
        el_filter = None

    if el_filter is None:
        return True                         # фильтр без правил = вся категория

    try:
        return el_filter.PassesFilter(elem)
    except:
        try:
            return el_filter.PassesFilter(doc, elem.Id)
        except:
            return False


def find_filter_for_element(filters, elem):
    """Первый по порядку фильтр, под который попадает элемент."""
    for f in filters:
        if element_passes_filter(f["element"], elem):
            return f
    return None


# ============================================================ ОСНОВНОЙ КОД

active_view  = revit.active_view
view_filters = collect_filters(active_view)

if not view_filters:
    TaskDialog.Show(
        "pyRevit",
        "На активном виде нет фильтров с заданным цветом.\n"
        "Добавьте фильтры (Visibility/Graphics > Filters) и задайте им цвет линий."
    )
    sys.exit()

tags_in_view = FilteredElementCollector(doc, active_view.Id) \
    .OfClass(IndependentTag) \
    .WhereElementIsNotElementType() \
    .ToElements()

if not tags_in_view:
    TaskDialog.Show("pyRevit", "На активном виде нет тегов (IndependentTag).")
    sys.exit()

limit_cat_id = None
if LIMIT_CATEGORY is not None:
    limit_cat_id = ElementId(LIMIT_CATEGORY)

t = Transaction(doc, "Раскрасить теги по фильтрам вида")
t.Start()

count_colored = 0
count_cleared = 0
count_skipped = 0
per_filter    = {}

empty_ogs = OverrideGraphicSettings()

for tag in tags_in_view:
    matched = None

    for host in get_tagged_elements(doc, tag):
        if host.Category is None:
            continue
        if limit_cat_id is not None and host.Category.Id != limit_cat_id:
            continue

        matched = find_filter_for_element(view_filters, host)
        if matched:
            break

    if matched is None and MATCH_TAG_ITSELF:
        matched = find_filter_for_element(view_filters, tag)

    if matched is None:
        if CLEAR_UNMATCHED:
            try:
                active_view.SetElementOverrides(tag.Id, empty_ogs)
                count_cleared += 1
            except:
                count_skipped += 1
        else:
            count_skipped += 1
        continue

    ogs = OverrideGraphicSettings()
    ogs.SetProjectionLineColor(matched["color"])

    try:
        active_view.SetElementOverrides(tag.Id, ogs)
        count_colored += 1
        per_filter[matched["name"]] = per_filter.get(matched["name"], 0) + 1
    except:
        count_skipped += 1

t.Commit()

lines = []
lines.append("Фильтров с цветом: {0}".format(len(view_filters)))
lines.append("Обработано тегов: {0}".format(len(tags_in_view)))
lines.append("Раскрашено: {0}".format(count_colored))
lines.append("Сброшено (без фильтра): {0}".format(count_cleared))
lines.append("Пропущено: {0}".format(count_skipped))

if per_filter:
    lines.append("")
    lines.append("По фильтрам:")
    for f in view_filters:
        n = per_filter.get(f["name"], 0)
        if n:
            c = f["color"]
            lines.append("  {0} - {1} шт. (RGB {2},{3},{4})".format(
                f["name"], n, c.Red, c.Green, c.Blue))

TaskDialog.Show("pyRevit", "\n".join(lines))
