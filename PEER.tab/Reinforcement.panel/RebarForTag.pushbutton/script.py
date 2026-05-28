# -*- coding: utf-8 -*-
"""
Audit Rebar Tags (Advanced Mode)
==================================================
Description:
Validates the connection between 'PEER_Rebar TAG' components
and their target elements via the 'PR_Rebar_ID' parameter.
Includes grouped output, error highlighting, and View Type checks (ignores Sections).
"""

__title__ = "Check\nRebar Links"
__author__ = "BIM Specialist"

import clr

clr.AddReference('RevitAPI')
clr.AddReference('RevitAPIUI')

from Autodesk.Revit.DB import *
from Autodesk.Revit.UI import *
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType
from pyrevit import revit, script, forms

# --- НАСТРОЙКИ ---
doc = revit.doc
uidoc = revit.uidoc
output = script.get_output()

FAMILY_NAME_CONTAINS = "PEER_Rebar TAG"
PARAM_NAME_ID = "PR_Rebar_ID"


# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def get_universal_value(elem, param_name):
    """Извлекает значение параметра из Экземпляра или Типа."""
    if not elem: return None

    param = elem.LookupParameter(param_name)
    if not param:
        elem_type = doc.GetElement(elem.GetTypeId())
        if elem_type:
            param = elem_type.LookupParameter(param_name)

    if not param: return None

    if param.StorageType == StorageType.String:
        val = param.AsString()
        if val: return val
    val_str = param.AsValueString()
    if val_str: return val_str
    if param.StorageType == StorageType.Integer:
        return str(param.AsInteger())
    return None


def get_rebar_number(elem):
    """Ищет номер арматуры по возможным именам параметров."""
    for p_name in ["Rebar Number", "Rebar_Number", "Rebar_Nimber"]:
        val = get_universal_value(elem, p_name)
        if val: return val
    return "-"


class CustomFamilyFilter(ISelectionFilter):
    def AllowElement(self, elem):
        try:
            type_id = elem.GetTypeId()
            if type_id == ElementId.InvalidElementId: return False
            elem_type = doc.GetElement(type_id)
            return elem_type and FAMILY_NAME_CONTAINS in elem_type.FamilyName
        except:
            return False

    def AllowReference(self, ref, point):
        return False


def get_elements_from_sheet(sheet_view):
    found_elements = []
    view_ids = sheet_view.GetAllPlacedViews()
    for v_id in view_ids:
        collector = FilteredElementCollector(doc, v_id).OfClass(FamilyInstance).ToElements()
        for el in collector:
            if hasattr(el, "Symbol") and el.Symbol and FAMILY_NAME_CONTAINS in el.Symbol.FamilyName:
                found_elements.append(el)
    return found_elements


def wrap_red(text):
    """Оборачивает текст в HTML-тег для выделения красным цветом."""
    return '<span style="color:red; font-weight:bold;">{}</span>'.format(text)


def is_plan_view(view_id):
    """Проверяет, является ли вид планом (архитектурным или несущих конструкций)."""
    if view_id == ElementId.InvalidElementId: return False
    view = doc.GetElement(view_id)
    if not view: return False
    return view.ViewType in [ViewType.FloorPlan, ViewType.EngineeringPlan, ViewType.CeilingPlan]


# --- ОСНОВНАЯ ФУНКЦИЯ ---
def main():
    active_view = doc.ActiveView
    target_tags = []

    # 1. СБОР ТЭГОВ
    if active_view.ViewType == ViewType.DrawingSheet:
        target_tags = get_elements_from_sheet(active_view)
        if not target_tags:
            forms.alert("No '{}' found on this Sheet.".format(FAMILY_NAME_CONTAINS), exitscript=True)
    else:
        selection_ids = uidoc.Selection.GetElementIds()
        if selection_ids:
            for eid in selection_ids:
                elem = doc.GetElement(eid)
                if CustomFamilyFilter().AllowElement(elem): target_tags.append(elem)
        if not target_tags:
            try:
                with forms.WarningBar(title="Select tags: " + FAMILY_NAME_CONTAINS):
                    picked_refs = uidoc.Selection.PickObjects(ObjectType.Element, CustomFamilyFilter(), "Select tags")
                    target_tags = [doc.GetElement(r.ElementId) for r in picked_refs]
            except:
                return

    if not target_tags: return

    # 2. ОБРАБОТКА И ВАЛИДАЦИЯ
    raw_table_data = []

    for tag in target_tags:
        # Данные тэга
        tag_link = output.linkify(tag.Id, title="Tag: {}".format(tag.Id))
        tag_rebar_num = get_rebar_number(tag)
        tag_view_id = tag.OwnerViewId

        raw_donor_id = get_universal_value(tag, PARAM_NAME_ID)

        # Данные донора (по умолчанию)
        donor_link = "Not Found"
        donor_rebar_num = "-"
        donor_view_id = ElementId.InvalidElementId
        t_elem = None
        donor_id_int = 0

        # Ошибки
        errors = []
        is_error = False

        # Поиск донора
        if raw_donor_id and raw_donor_id.isdigit():
            donor_id_int = int(raw_donor_id)
            try:
                t_elem = doc.GetElement(ElementId(donor_id_int))
                if t_elem:
                    donor_link = output.linkify(t_elem.Id, title="Donor: {}".format(t_elem.Id))
                    donor_rebar_num = get_rebar_number(t_elem)
                    donor_view_id = t_elem.OwnerViewId
            except:
                pass

        # --- ПРОВЕРКА УСЛОВИЙ (ОШИБКИ) ---

        # Условие 1: ID > 100 и донор не найден
        if donor_id_int > 100 and not t_elem:
            errors.append("Donor not found (ID>100)")
            is_error = True

        # Условие 2: Номера арматуры не равны (если донор найден)
        if t_elem and donor_rebar_num != tag_rebar_num:
            errors.append("Rebar numbers mismatch")
            is_error = True

        # Условие 3: Проверка нахождения на одном виде (с учетом планов и разрезов)
        if t_elem and tag_view_id != donor_view_id and donor_view_id != ElementId.InvalidElementId:
            tag_is_plan = is_plan_view(tag_view_id)
            donor_is_plan = is_plan_view(donor_view_id)

            if tag_is_plan and donor_is_plan:
                errors.append("Located on different floor plans")
                is_error = True

        status_text = ", ".join(errors) if is_error else "✅ OK"

        # Применяем красный цвет, если есть ошибка
        if is_error:
            c_donor_num = wrap_red(donor_rebar_num)
            c_donor_link = wrap_red(donor_link)
            c_tag_link = wrap_red(tag_link)
            c_tag_num = wrap_red(tag_rebar_num)
            c_status = wrap_red(status_text)
        else:
            c_donor_num = donor_rebar_num
            c_donor_link = donor_link
            c_tag_link = tag_link
            c_tag_num = tag_rebar_num
            c_status = status_text

        # Ключи сортировки
        try:
            sort_key_1 = (0, int(donor_rebar_num))
        except:
            sort_key_1 = (1, str(donor_rebar_num))

        sort_key_2 = donor_id_int

        row_data = {
            "sort_key_1": sort_key_1,
            "sort_key_2": sort_key_2,
            "is_error": is_error,
            "c_donor_num": c_donor_num,
            "c_donor_link": c_donor_link,
            "c_tag_link": c_tag_link,
            "c_tag_num": c_tag_num,
            "c_status": c_status,
            "raw_donor_link": donor_link
        }

        raw_table_data.append(row_data)

    # 3. СОРТИРОВКА И ГРУППИРОВКА ВЫВОДА
    if not raw_table_data: return

    raw_table_data.sort(key=lambda x: (x["sort_key_1"], x["sort_key_2"]))

    final_rows = []
    prev_donor_link = None

    for row in raw_table_data:
        is_same_donor = (row["raw_donor_link"] == prev_donor_link) and (row["raw_donor_link"] != "Not Found")

        display_donor_num = "" if is_same_donor else row["c_donor_num"]
        display_donor_link = "" if is_same_donor else row["c_donor_link"]

        final_rows.append([
            display_donor_num,
            display_donor_link,
            row["c_tag_link"],
            row["c_tag_num"],
            row["c_status"]
        ])

        prev_donor_link = row["raw_donor_link"]

    # 4. ВЫВОД РЕЗУЛЬТАТА
    output.print_table(
        table_data=final_rows,
        columns=["Rebar Number (Donor)", "Donor (ID)", "Tag (ID)", "Rebar Number (Tag)", "Status"],
        title="Rebar and Tag Links Audit"
    )


if __name__ == '__main__':
    main()