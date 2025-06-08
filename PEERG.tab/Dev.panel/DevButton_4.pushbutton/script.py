# -*- coding: utf-8 -*-
__title__ = "Create Sheets"
__author__ = "Dmitry D"

from pyrevit import revit, DB
from pyrevit.forms import alert, SelectFromList
import re

uidoc = revit.uidoc
doc = revit.doc

# Какие номера искать в названиях уровней:
allowed_bases = [str(x) for x in range(100, 230, 10)]  # 100, 110, ..., 220

levels = DB.FilteredElementCollector(doc).OfClass(DB.Level).ToElements()
levels_sorted = sorted(levels, key=lambda l: l.Elevation)

if len(levels_sorted) < 2:
    alert("Недостаточно уровней в проекте для создания листов.")
    exit()

# Выбор уровней (кроме самого нижнего)
selected_levels = SelectFromList.show(
    levels_sorted[1:],
    multiselect=True,
    name_attr='Name',
    title="Выберите уровни для создания листов"
)


def ft_to_m(number):
    return number * 0.3048


if not selected_levels:
    alert("Не выбран ни один уровень.")
    exit()

sheet_type_id = DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol).OfCategory(
    DB.BuiltInCategory.OST_TitleBlocks).FirstElementId()


def extract_base_from_name(level_name):
    for base in allowed_bases:
        # строгое совпадение числа (не части другого числа)
        if re.search(r'(?<!\d){}(?!\d)'.format(base), level_name):
            return int(base)
    return None


def create_sheet(sheet_name, sheet_number):
    with DB.Transaction(doc, "Create Sheet") as t:
        t.Start()
        new_sheet = DB.ViewSheet.Create(doc, sheet_type_id)
        new_sheet.Name = sheet_name
        new_sheet.SheetNumber = sheet_number
        t.Commit()


for current_level in selected_levels:
    idx = levels_sorted.index(current_level)
    if idx == 0:
        continue  # на всякий случай, если выбрали первый уровень

    lower_level = levels_sorted[idx - 1]
    base_number = extract_base_from_name(current_level.Name)
    if base_number is None:
        alert(u"В названии уровня '{}' не найден базовый номер из списка {}. Листы не будут созданы.".format(
            current_level.Name, allowed_bases))
        continue

    relative_elevation = ft_to_m(current_level.Elevation)
    lower_relative_elevation = ft_to_m(lower_level.Elevation)


    def ft_to_m(number):
        return number * 0.3048


    def elevation_str(elev):
        m = round(elev, 2)
        return u"{:+.2f} ".format(m)


    sheet_data = [
        (u"תכנית תבניות במפלס {}".format(elevation_str(relative_elevation)), str(base_number)),
        (u"{}תכנית זיון תקרה במפלס".format(elevation_str(relative_elevation)), str(base_number + 2)),
        (u"תכנית זיון קירות ועמודים ממפלס {} עד {}".format(
             elevation_str(relative_elevation),elevation_str(lower_relative_elevation)), str(base_number + 5))
    ]

    for sheet_name, sheet_number in sheet_data:
        create_sheet(sheet_name, sheet_number)

alert("Листы успешно созданы.")
