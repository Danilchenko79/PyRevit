# -*- coding: utf-8 -*-
__title__ = "New View"
__author__ = "Dmitry D"


from pyrevit import forms
from Autodesk.Revit.DB import FilteredElementCollector, BuiltInCategory, ViewFamilyType, ViewFamily, ViewPlan

doc = __revit__.ActiveUIDocument.Document

# 1. Собираем все уровни
levels = list(FilteredElementCollector(doc)
              .OfCategory(BuiltInCategory.OST_Levels)
              .WhereElementIsNotElementType()
              .ToElements())

if not levels:
    forms.alert("В проекте нет уровней.")
    script.exit()

# 2. Выводим список названий уровней для выбора
level_dict = {lvl.Name: lvl for lvl in levels}
level_names = sorted(level_dict.keys())
selected_level_name = forms.SelectFromList.show(level_names,
                                                title="Выберите уровень",
                                                button_name='Создать Structural Plan RE')

if not selected_level_name:
    script.exit()

selected_level = level_dict[selected_level_name]

# 3. Находим тип вида "Structural Plan RE"
view_family_types = FilteredElementCollector(doc).OfClass(ViewFamilyType)
structural_plan_re_type = None

from Autodesk.Revit.DB import BuiltInParameter

for vft in view_family_types:
    try:
        type_name = vft.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM).AsString()
        if (vft.ViewFamily == ViewFamily.StructuralPlan) and (type_name == "Structural Plan RE"):
            structural_plan_re_type = vft
            break
    except Exception as e:
        forms.alert("Ошибка при обработке ViewFamilyType: {}".format(e))

# 4. Проверяем, есть ли уже вид на этом уровне такого типа
existing_views = FilteredElementCollector(doc).OfClass(ViewPlan).ToElements()
for vp in existing_views:
    if (vp.ViewType == ViewFamily.StructuralPlan
        and vp.ViewFamilyType.Name == "Structural Plan RE"
        and vp.GenLevel.Id == selected_level.Id):
        forms.alert("Вид 'Structural Plan RE' для этого уровня уже существует: '{}'.".format(vp.Name))
        script.exit()

# 5. Создаём вид
from Autodesk.Revit.DB import Transaction

t = Transaction(doc, "Создать Structural Plan RE")
t.Start()
try:
    new_view = ViewPlan.Create(doc, structural_plan_re_type.Id, selected_level.Id)
    new_view.Name = ("{}RE.".format(selected_level.Name ))
    forms.alert("Вид успешно создан: '{}'.".format(new_view.Name))
    t.Commit()
except Exception as e:
    t.RollBack()
    forms.alert("Ошибка: {}".format(e))
