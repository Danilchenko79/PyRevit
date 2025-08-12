# -*- coding: utf-8 -*-
# ╦╔╦╗╔═╗╔═╗╦═╗╔╦╗╔═╗
# ║║║║╠═╝║ ║╠╦╝ ║ ╚═╗
# ╩╩ ╩╩  ╚═╝╩╚═ ╩ ╚═╝ IMPORTS
# ==================================================
from pyrevit import forms
from Autodesk.Revit.DB import *

# ╦  ╦╔═╗╦═╗╦╔═╗╔╗ ╦  ╔═╗╔═╗
# ╚╗╔╝╠═╣╠╦╝║╠═╣╠╩╗║  ║╣ ╚═╗
#  ╚╝ ╩ ╩╩╚═╩╩ ╩╚═╝╩═╝╚═╝╚═╝ VARIABLES
# ==================================================
uidoc    = __revit__.ActiveUIDocument
doc      = __revit__.ActiveUIDocument.Document
app      = __revit__.Application


# ╔═╗╦ ╦╔╗╔╔═╗╔╦╗╦╔═╗╔╗╔╔═╗
# ╠╣ ║ ║║║║║   ║ ║║ ║║║║╚═╗
# ╚  ╚═╝╝╚╝╚═╝ ╩ ╩╚═╝╝╚╝╚═╝ FUNCTIONS
# ==================================================
# -*- coding: utf-8 -*-
from Autodesk.Revit.DB import (
    FilteredElementCollector, TextNoteType, BuiltInParameter,
    BuiltInCategory, UnitUtils, UnitTypeId, Transaction, SubTransaction
)

from Autodesk.Revit.DB import (
    FilteredElementCollector, TextNoteType, BuiltInParameter,
    BuiltInCategory, UnitUtils, UnitTypeId
)

def create_TextType(doc, name,
                                  size_mm=3.5,
                                  font="Arial",
                                  background="Transparent",  # "Transparent" | "Opaque"
                                  width_factor=1.0,
                                  arrow_name=None,
                                  bold=None, italic=None):
    """Дублирует первый TextNoteType и настраивает его. Транзакций НЕ открывает."""
    base = FilteredElementCollector(doc).OfClass(TextNoteType).FirstElement()
    if base is None:
        raise Exception("В проекте нет ни одного TextNoteType для дублирования.")


    tnt = base.Duplicate(name)

    # Размер
    size_ft = UnitUtils.ConvertToInternalUnits(float(size_mm), UnitTypeId.Millimeters)
    p = tnt.get_Parameter(BuiltInParameter.TEXT_SIZE);               p and p.Set(size_ft)
    # Шрифт
    p = tnt.get_Parameter(BuiltInParameter.TEXT_FONT);               p and font and p.Set(font)
    # Фон
    bg_val = 0 if str(background).lower().startswith("t") else 1
    p = tnt.get_Parameter(BuiltInParameter.TEXT_BACKGROUND);         p and p.Set(bg_val)
    # Коэфф. ширины
    p = tnt.get_Parameter(BuiltInParameter.TEXT_WIDTH_SCALE);        p and p.Set(float(width_factor))
    # Жирный/Курсив (если поддерживается версией)
    try:
        if bold   is not None: tnt.get_Parameter(BuiltInParameter.TEXT_STYLE_BOLD).Set(1 if bold else 0)
        if italic is not None: tnt.get_Parameter(BuiltInParameter.TEXT_STYLE_ITALIC).Set(1 if italic else 0)
    except: pass
    # Стрелка лидера
    if arrow_name:
        arrows = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Arrowheads).ToElements()
        target = next((a for a in arrows if a.Name == arrow_name), None)
        if target:
            p = tnt.get_Parameter(BuiltInParameter.TEXT_LEADER_ARROWHEAD); p and p.Set(target.Id)

    return tnt.Id
