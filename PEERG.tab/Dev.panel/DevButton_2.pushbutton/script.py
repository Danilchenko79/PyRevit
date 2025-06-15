# -*- coding: utf-8 -*-
__title__ = "Create Sheets"
__author__ = "Dmitry D"
from pyrevit import revit, forms
from Autodesk.Revit.DB import (
    Transaction, FilteredElementCollector, ViewSchedule
)

doc = revit.doc
view = doc.ActiveView

if not isinstance(view, ViewSchedule):
    forms.alert("Открой спецификацию и запусти скрипт на ней!", exitscript=True)

param_name ="Rebar_Number"



sort_params = ["Rebar_Shape", "Rebar_Diameter", "Rebar_Length", "Rebar_A"]
elements = list(FilteredElementCollector(doc, view.Id).WhereElementIsNotElementType())

def get_sort_key(el):
    result = []
    for sp in sort_params:
        p = el.LookupParameter(sp)
        val = p.AsString() if p and p.StorageType.ToString() == "String" else (p.AsValueString() if p else "")
        try:
            val = float(val.replace(',', '.'))
        except Exception:
            pass
        result.append(val)
    return result

elements_sorted = sorted(elements, key=get_sort_key)

# --- Весь блок изменений только внутри этой транзакции! ---
with Transaction(doc, "Auto Numbering Schedule"):
    for idx, el in enumerate(elements_sorted, 1):
        p = el.LookupParameter(param_name)
        if p and p.StorageType.ToString() == "String":
            p.Set(str(idx))
        elif p and p.StorageType.ToString() == "Integer":
            p.Set(idx)
        else:
            print("Параметр не найден или не поддерживается для элемента с Id:", el.Id)

forms.alert("Готово! Все строки спецификации пронумерованы по сортировке.")
