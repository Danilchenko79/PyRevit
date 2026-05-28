# -*- coding: utf-8 -*-
"""
Audit Rebar Tags (Advanced Mode)
==================================================
Description:
Validates the connection between 'PEER_Rebar TAG' components
and their target elements via the 'PR_Rebar_ID' parameter.
Includes grouped output, error highlighting, and View Type checks (ignores Sections).
"""

__title__ = "ColorTag"
__author__ = "BIM Specialist"

import clr

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    BuiltInCategory,
    OverrideGraphicSettings,
    Color
)

from Autodesk.Revit.UI import TaskDialog

import os, sys, math, datetime, time                                    # Regular Imports
from Autodesk.Revit.DB import *                                         # Import everything from DB (Very good for beginners)
from Autodesk.Revit.DB import Transaction, FilteredElementCollector     # or Import only classes that are used.
from Autodesk.Revit.UI.Selection import Selection
from Autodesk.Revit.UI.Selection import ObjectType




# pyRevit
from pyrevit import revit, forms                                        # import pyRevit modules. (Lots of useful features)



# .NET Imports
import clr                                  # Common Language Runtime. Makes .NET libraries accessinble
clr.AddReference("System")                  # Refference System.dll for import.
from System.Collections.Generic import List # List<ElementType>() <- it's special type of list from .NET framework that RevitAPI requires
# List_example = List[ElementId]()          # use .Add() instead of append or put python list of ElementIds in parentesis.


doc   = __revit__.ActiveUIDocument.Document   #type:Document
uidoc = __revit__.ActiveUIDocument            #type:UIDocument
app   = __revit__.Application                 # Represents the Autodesk Revit Application, providing access to documents, options and other application wide data and settings.


# Настройки цветов
COLOR_GREEN = Color(0, 128, 0)    # Y
COLOR_BLUE  = Color(0, 0, 255)    # B
COLOR_RED   = Color(225, 0, 0)    # ADD

PARAM_NAME = "Rebar_Type"

def get_tagged_element(doc, tag):
    """
    Возвращает элемент, к которому привязан тег.
    Поддержка старого и нового API.
    """
    try:
        # Новый API: GetTaggedLocalElementIds (может быть несколько)
        ids = getattr(tag, "GetTaggedLocalElementIds", None)
        if ids:
            elem_ids = list(ids())
            if elem_ids:
                return doc.GetElement(elem_ids[0])
    except:
        pass

    try:
        # Старый API: TaggedElementId
        elem_id = getattr(tag, "TaggedElementId", None)
        if elem_id:
            eid = tag.TaggedElementId.ElementId
            return doc.GetElement(eid)
    except:
        pass

    return None


def get_rebar_type_value(elem):
    if elem is None:
        return None
    p = elem.LookupParameter(PARAM_NAME)
    if p is None:
        return None
    try:
        return p.AsString()
    except:
        return None


def get_color_for_value(value):
    """
    Приоритет:
    1) ADD - красный
    2) Y - зеленый
    3) B - синий
    """
    if not value:
        return None

    text = value.upper()

    if "נוסף" in text:
        return COLOR_RED
    if "ע" in text:
        return COLOR_GREEN
    if "ת" in text:
        return COLOR_BLUE

    return None

active_view = revit.active_view
# Собираем теги на активном виде
# Теги для Detail Items обычно в категории OST_DetailComponentTags,
# но на всякий случай возьмем все IndependentTag из вида
from Autodesk.Revit.DB import IndependentTag

tags_in_view = FilteredElementCollector(doc, active_view.Id) \
    .OfClass(IndependentTag) \
    .ToElements()

if not tags_in_view:
    TaskDialog.Show("pyRevit", "На активном виде нет тегов (IndependentTag).")
else:
    from Autodesk.Revit.DB import Transaction
    t = Transaction(doc, "Раскрасить теги по Rebar_Type")
    t.Start()

    count_colored = 0
    count_skipped = 0

    for tag in tags_in_view:
        tagged_elem = get_tagged_element(doc, tag)
        if not tagged_elem:
            count_skipped += 1
            continue

        # Фильтруем только Detail Items
        if tagged_elem.Category is None:
            count_skipped += 1
            continue

        if tagged_elem.Category.Id.IntegerValue != int(BuiltInCategory.OST_DetailComponents):
            count_skipped += 1
            continue

        val = get_rebar_type_value(tagged_elem)
        color = get_color_for_value(val)

        if color is None:
            # Можем при желании сбрасывать override, но пока пропускаем
            count_skipped += 1
            continue

        ogs = OverrideGraphicSettings()
        ogs.SetProjectionLineColor(color)

        doc.ActiveView.SetElementOverrides(tag.Id, ogs)
        count_colored += 1

    t.Commit()

    msg = "Обработано тегов: {0}\nРаскрашено: {1}\nПропущено: {2}".format(
        len(tags_in_view),
        count_colored,
        count_skipped
    )
    TaskDialog.Show("pyRevit", msg)
