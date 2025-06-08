# -*- coding: utf-8 -*-
from pyrevit import revit, DB, forms
doc, view = revit.doc, revit.doc.ActiveView
if not isinstance(view, DB.ViewSchedule):
    forms.alert(u"Активный вид — не спецификация!")
    raise SystemExit

param_name = "Rebar_Number"
start = 1

# Собираем все строки таблицы — используют API 2023+
table = view.GetTableData().GetSectionData(DB.SectionType.Body)
rows = range(1, table.NumberOfRows)          # 0 — заголовок
elements = [doc.GetElement(table.GetRowElementId(r))
            for r in rows
            if table.GetRowElementId(r) != DB.ElementId.InvalidElementId]

old_nums = [ (el.Id.IntegerValue,
              (el.LookupParameter(param_name) or None).AsString())
             for el in elements ]
forms.alert(u"Найдено {} элементов.\nСтарые номера:\n{}".format(
            len(old_nums),
            "\n".join("ID {} → {}".format(i,n) for i,n in old_nums)))

with DB.Transaction(doc, "Schedule Renumber") as t:
    t.Start()
    for i, el in enumerate(elements, start):
        p = el.LookupParameter(param_name)
        if p and not p.IsReadOnly:
            p.Set(str(i))
    t.Commit()
forms.alert(u"Готово! Пронумеровано: {}".format(len(elements)))
