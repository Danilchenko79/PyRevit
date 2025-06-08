# -*- coding: utf-8 -*-
__title__ = "Mark Detail Items"
__author__ = "ChatGPT and You"

from Autodesk.Revit.DB import FilteredElementCollector, BuiltInCategory, Transaction
from pyrevit import revit, forms
from Autodesk.Revit.UI import TaskDialog

doc = revit.doc

try:
    # 1. Получаем все листы
    sheets = FilteredElementCollector(doc)\
        .OfCategory(BuiltInCategory.OST_Sheets)\
        .WhereElementIsNotElementType()\
        .ToElements()

    # 2. Собираем список номеров листов
    sheet_numbers = [sheet.SheetNumber for sheet in sheets]
    sheet_numbers.sort()

    # 3. Запрос выбора листов
    selected_sheet_numbers = forms.SelectFromList.show(sheet_numbers,
                                                       multiselect=True,
                                                       title='Выберите листы для обновления',
                                                       width=500)

    if not selected_sheet_numbers:
        TaskDialog.Show("Assign Sheet Number to Mark", "Вы не выбрали ни одного листа.")
    else:
        # 4. Фильтруем выбранные листы
        selected_sheets = [sheet for sheet in sheets if sheet.SheetNumber in selected_sheet_numbers]

        # 5. Получаем все Viewports
        viewports = FilteredElementCollector(doc)\
            .OfCategory(BuiltInCategory.OST_Viewports)\
            .WhereElementIsNotElementType()\
            .ToElements()

        # 6. Создаём словарь ViewId → SheetNumber
        view_to_sheet = {}
        for vp in viewports:
            sheet = doc.GetElement(vp.SheetId)
            if sheet and sheet.SheetNumber in selected_sheet_numbers:
                view_to_sheet[vp.ViewId.IntegerValue] = sheet.SheetNumber

        # 7. Получаем все Detail Items
        detail_items = FilteredElementCollector(doc)\
            .OfCategory(BuiltInCategory.OST_DetailComponents)\
            .WhereElementIsNotElementType()\
            .ToElements()

        # 8. Обновляем параметр Mark
        t = Transaction(doc, "Assign Sheet Number to Mark")
        t.Start()

        updated_count = 0
        skipped_count = 0

        for item in detail_items:
            try:
                owner_view_id = item.OwnerViewId
                sheet_number = view_to_sheet.get(owner_view_id.IntegerValue)
                if sheet_number:
                    param = item.LookupParameter("Mark")
                    if param and not param.IsReadOnly:
                        current_value = param.AsString()
                        if current_value != sheet_number:
                            param.Set(sheet_number)
                            updated_count += 1
                        else:
                            skipped_count += 1
            except Exception as e:
                continue

        t.Commit()

        TaskDialog.Show("Assign Sheet Number to Mark",
                        "Обновлено элементов: {}\nПропущено (уже совпадает): {}".format(updated_count, skipped_count))

except Exception as e:
    TaskDialog.Show("Ошибка выполнения", str(e))
