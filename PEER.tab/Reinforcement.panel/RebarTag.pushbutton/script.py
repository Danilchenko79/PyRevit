# -*- coding: utf-8 -*-
__title__ = "Rebar Tag"
__doc__ = "Places a tag on Sections, Elevations, and Plans. Automatically sets up the Work Plane and transfers parameters."

import traceback
from pyrevit import revit, DB, forms
from Autodesk.Revit.DB import *
from Autodesk.Revit.Exceptions import OperationCanceledException

doc = revit.doc
uidoc = revit.uidoc

# -----------------------------------------------------
# КОНСТАНТЫ
# -----------------------------------------------------
TAG_FAMILY_NAME = "PEER_Rebar TAG"
SHAPE_PREFIX = "PEER_Rebar_Shape"

# Параметры для копирования (Имя параметра в доноре и марке должно совпадать)
PARAM_MAP = [
    'Rebar_Number',
    'Rebar_Diameter',
    'Rebar_Length',
    'Rebar_Quantity Text',
    'Rebar_Spacing'
]


# -----------------------------------------------------
# УТИЛИТЫ И ЛОГИКА
# -----------------------------------------------------
def setup_view_workplane(view):
    """
    Создает SketchPlane по нормали вида и устанавливает ее как рабочую плоскость.
    """
    try:
        plane = Plane.CreateByNormalAndOrigin(view.ViewDirection, view.Origin)
        with revit.Transaction("Fix WorkPlane"):
            view.SketchPlane = SketchPlane.Create(doc, plane)
        return True
    except Exception as e:
        print("Error setting work plane: {}".format(e))
        return False


def get_sheet_from_view(view):
    """
    Определяет лист, на котором размещен вид.
    Если активный вид уже является листом, возвращает его.
    """
    if isinstance(view, ViewSheet):
        return view

    viewports = FilteredElementCollector(doc).OfClass(Viewport).ToElements()
    for vp in viewports:
        if vp.ViewId == view.Id:
            return doc.GetElement(vp.SheetId)

    return None


def find_donor_on_sheet(sheet, rebar_no):
    """
    Ищет элемент-донор ТОЛЬКО на видах, размещенных на переданном листе.
    """
    view_ids = sheet.GetAllPlacedViews()

    for v_id in view_ids:
        # Собираем только экземпляры семейств в категории DetailComponents для конкретного вида (v_id)
        elements = FilteredElementCollector(doc, v_id) \
            .OfCategory(BuiltInCategory.OST_DetailComponents) \
            .OfClass(FamilyInstance) \
            .WhereElementIsNotElementType() \
            .ToElements()

        for elem in elements:
            # Защита hasattr предотвращает ошибки с системными элементами
            if hasattr(elem, "Symbol") and elem.Symbol and elem.Symbol.Family and elem.Symbol.Family.Name.startswith(
                    SHAPE_PREFIX):
                param = elem.LookupParameter("Rebar_Number")
                if param and param.HasValue:
                    val = param.AsString() or param.AsValueString()
                    if val == rebar_no:
                        return elem  # Возвращаем первый найденный элемент
    return None


def copy_parameter(source_elem, target_elem, param_name):
    """
    Копирует параметр 'один в один' по его StorageType.
    """
    src_p = source_elem.LookupParameter(param_name)
    tgt_p = target_elem.LookupParameter(param_name)

    if not src_p or not src_p.HasValue: return
    if not tgt_p or tgt_p.IsReadOnly: return

    st_type = src_p.StorageType
    if st_type == StorageType.Double:
        tgt_p.Set(src_p.AsDouble())
    elif st_type == StorageType.Integer:
        tgt_p.Set(src_p.AsInteger())
    elif st_type == StorageType.String:
        tgt_p.Set(src_p.AsString())
    elif st_type == StorageType.ElementId:
        tgt_p.Set(src_p.AsElementId())


# -----------------------------------------------------
# ОСНОВНОЙ СКРИПТ
# -----------------------------------------------------
def run():
    active_view = doc.ActiveView

    if active_view.ViewType == ViewType.ThreeD:
        forms.alert("Cannot place 2D tags in a 3D view.")
        return

    # 1. Поиск листа для ограничения зоны поиска
    sheet = get_sheet_from_view(active_view)
    if not sheet:
        forms.alert("This view is not placed on a Sheet! Please place the view on a sheet first to find the donor.")
        return

    # 2. Анализ выделения пользователя
    selection = [doc.GetElement(eid) for eid in uidoc.Selection.GetElementIds()]
    selected_tags = [e for e in selection if isinstance(e, FamilyInstance) and e.Symbol.Family.Name == TAG_FAMILY_NAME]

    mode = "UPDATE" if selected_tags else "CREATE"
    target_elements = selected_tags

    # 3. Подготовка режима создания
    if mode == "CREATE":
        tag_symbol = None
        symbols = FilteredElementCollector(doc).OfClass(FamilySymbol).OfCategory(BuiltInCategory.OST_DetailComponents)
        for s in symbols:
            if s.Family.Name == TAG_FAMILY_NAME:
                tag_symbol = s
                break

        if not tag_symbol:
            forms.alert("Family '{}' not found in the project!".format(TAG_FAMILY_NAME))
            return

        if not setup_view_workplane(active_view):
            forms.alert("Failed to set up the work plane.")
            return

        try:
            point = uidoc.Selection.PickPoint("Left-click to place the tag")
        except OperationCanceledException:
            return

    # 4. Запрос номера позиции
    rebar_no = forms.ask_for_string(prompt="Rebar Number:", title="Smart Tag")
    if not rebar_no: return

    # 5. Поиск донора ТОЛЬКО НА ТЕКУЩЕМ ЛИСТЕ
    source_item = find_donor_on_sheet(sheet, rebar_no)
    if not source_item:
        forms.alert("Source element {} with number {} not found on Sheet '{}'.".format(SHAPE_PREFIX, rebar_no,
                                                                                       sheet.SheetNumber))
        return

    # 6. Транзакция (Создание и перенос данных)
    try:
        with revit.Transaction("Place Smart Tag"):

            if mode == "CREATE":
                if not tag_symbol.IsActive:
                    tag_symbol.Activate()
                new_tag = doc.Create.NewFamilyInstance(point, tag_symbol, active_view)
                target_elements = [new_tag]

            for tag in target_elements:
                for p_name in PARAM_MAP:
                    copy_parameter(source_item, tag, p_name)

                # ЖЕСТКО ЗАПИСЫВАЕМ ID ДОНОРА
                id_param = tag.LookupParameter("PR_Rebar_ID")
                if id_param and not id_param.IsReadOnly:
                    if id_param.StorageType == StorageType.String:
                        id_param.Set(str(source_item.Id.IntegerValue))
                    elif id_param.StorageType == StorageType.Integer:
                        id_param.Set(source_item.Id.IntegerValue)

    except Exception as e:
        print(traceback.format_exc())
        forms.alert("Transaction error occurred. Check the console for details.")


if __name__ == "__main__":
    run()