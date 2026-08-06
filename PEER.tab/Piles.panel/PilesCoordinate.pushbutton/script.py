# -*- coding: utf-8 -*-
__title__  = 'Piles\nCoordinates'
__author__ = 'Dima'
__doc__    = '''Version = 1.0
Date      = 2026-08-06
Description: Writes shared (project) coordinates of every Structural
             Foundation with a LocationPoint into the instance
             parameters "Coordinate X" / "Coordinate Y".
             Units are detected automatically: Length parameters get
             feet (Revit converts), text/number parameters get mm.
How-To:
    1. Make sure piles have "Coordinate X" / "Coordinate Y" params
    2. Click the button - all piles in the model are processed
'''

import clr

clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import *
from pyrevit import revit, forms, script

doc = revit.doc

PARAM_X_NAME = "Coordinate X"
PARAM_Y_NAME = "Coordinate Y"


def get_mm(val_feet):
    """Перевод футов в мм для числовых/текстовых параметров."""
    try:
        return UnitUtils.ConvertFromInternalUnits(val_feet, UnitTypeId.Millimeters)
    except:
        return UnitUtils.ConvertFromInternalUnits(val_feet, DisplayUnitType.DUT_MILLIMETERS)


def smart_set_parameter(elem, param_name, internal_value):
    """
    Записывает значение в зависимости от типа параметра.
    internal_value - значение в футах (из API).
    """
    param = elem.LookupParameter(param_name)
    if not param or param.IsReadOnly:
        return False

    # ПРОВЕРКА ТИПА ПАРАМЕТРА
    # Если это тип "Длина", Revit сам переведет футы в мм для интерфейса
    is_length = False
    try:
        # Для Revit 2022+
        if param.Definition.GetDataType() == SpecTypeId.Length:
            is_length = True
    except:
        # Для Revit 2021 и ниже
        if param.Definition.ParameterType == ParameterType.Length:
            is_length = True

    if is_length:
        # Для параметров типа 'Длина' записываем ФУТЫ (Revit сам сконвертирует)
        param.Set(internal_value)
    elif param.StorageType == StorageType.String:
        # Для текстовых параметров пишем мм строкой
        param.Set(str(round(get_mm(internal_value), 2)))
    else:
        # Для числовых параметров пишем мм числом
        param.Set(get_mm(internal_value))
    return True


# --- ОСНОВНОЙ ЦИКЛ ---
piles = FilteredElementCollector(doc) \
    .OfCategory(BuiltInCategory.OST_StructuralFoundation) \
    .WhereElementIsNotElementType() \
    .ToElements()

project_location = doc.ActiveProjectLocation

with revit.Transaction("Запись координат (фикс единиц)"):
    for pile in piles:
        loc = pile.Location
        if isinstance(loc, LocationPoint):
            # Получаем координаты в ФУТАХ (Shared Coordinates)
            pos = project_location.GetProjectPosition(loc.Point)

            # Записываем через "умную" функцию
            smart_set_parameter(pile, PARAM_X_NAME, pos.EastWest)
            smart_set_parameter(pile, PARAM_Y_NAME, pos.NorthSouth)

print("Готово! Теперь значения должны совпадать с интерфейсом Revit.")
