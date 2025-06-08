# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
__title__   = "Rebar Shape 1"
__doc__     = """Version = 1.0
Date    = 15.06.2024"""
from pyrevit import revit, DB, forms

# Имя семейства, которое нужно разместить
FAMILY_NAME = "PEER_Rebar_Shape 1"

# Целевая категория (в зависимости от твоего семейства)
CATEGORY = DB.BuiltInCategory.OST_DetailComponents

doc = revit.doc
uidoc = revit.uidoc

# Собираем все семейства
collector = DB.FilteredElementCollector(doc).OfClass(DB.Family)

# Ищем нужное семейство
target_family = None
for fam in collector:
    if fam.Name == FAMILY_NAME:
        target_family = fam
        break

if not target_family:
    forms.alert("Семейство '{}' не найдено в проекте.".format(FAMILY_NAME), exitscript=True)

# Ищем первый FamilySymbol в категории
target_symbol = None
family_symbols = target_family.GetFamilySymbolIds()

for fsid in family_symbols:
    fs = doc.GetElement(fsid)
    if fs.Category and fs.Category.Id.IntegerValue == int(CATEGORY):
        target_symbol = fs
        break

if not target_symbol:
    forms.alert("Не удалось найти тип семейства '{}' в категории Detail Items.".format(FAMILY_NAME), exitscript=True)

# Активируем тип, если нужно
if not target_symbol.IsActive:
    with revit.Transaction("Activate Family Symbol"):
        target_symbol.Activate()

# Пытаемся разместить семейство
try:
    uidoc.PromptForFamilyInstancePlacement(target_symbol)
except Exception as e:
    if "aborted the pick operation" in str(e):
        pass
    else:
        raise
