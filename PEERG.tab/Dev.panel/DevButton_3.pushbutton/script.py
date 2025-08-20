# -*- coding: utf-8 -*-
__title__ = "Create Column"
__author__ = "Dmitry D"

from pyrevit import revit, forms
from Autodesk.Revit.DB import (
    Transaction,
    FilteredElementCollector,
    BuiltInCategory,
    FamilySymbol,
    ViewDrafting,
    XYZ,
    Line,
    ReferenceArray,
    Dimension,
    DimensionType,
    BuiltInParameter,
    TextNoteType,
    TextNote,
    IndependentTag, TagMode, TagOrientation, Reference
)
from Autodesk.Revit.DB import (
    XYZ, Reference, IndependentTag, TagMode, TagOrientation,
    ElementTransformUtils, SubTransaction
)
from Samples.Numeration import process_drafting_view
from Snippets._CreateTextType import create_TextType
import math

# Параметры для размещения тэга под хомутом
STIRRUP_TAG_FAMILY_NAME = "Detail items_Tag Rebar(Text Quantity)"  # Имя семейства тэга

STIRRUP_TAG_TYPE_NAME = "Tag Rebar + L"  # Имя типа тэга
TAG_OFFSET_DOWN_CM = 25  # см вниз от центра хомута

COL_TAG_FAMILY_NAME = "Detail items_Tag Rebar"
COL_TAG_TYPE_NAME   = "Tag Rebar 2∅10"

SECOND_REBAR_OFFSET_MM = 550      # сдвиг шпильки вправо от хомута
TAG_OFFSET_X_MM = 300             # зазор для тега по X
TAG_EXTRA_DOWN_MM = 350           # опускание тега ниже низа формы

def build_marks_and_ranges(marks):
    """
    Возвращает список dict:
    - одиночная марка: {num: str, num2: None, num_plus: False, width: 21}
    - диапазон: {num: str, num2: str, num_plus: True, width: 50} — только если подряд 3 и более!
    """
    nums = []
    others = []
    for m in marks:
        try:
            nums.append(int(m))
        except Exception:
            others.append(m)
    nums = sorted(nums)
    result = []
    i = 0
    while i < len(nums):
        start = nums[i]
        seq = [start]
        while i + 1 < len(nums) and nums[i + 1] == nums[i] + 1:
            i += 1
            seq.append(nums[i])
        if len(seq) >= 3:
            result.append({'num': str(seq[0]), 'num2': str(seq[-1]), 'num_plus': True, 'width': 50})
        else:
            for n in seq:
                result.append({'num': str(n), 'num2': None, 'num_plus': False, 'width': 21})
        i += 1
    for m in sorted(others):
        result.append({'num': m, 'num2': None, 'num_plus': False, 'width': 21})
    return result


doc = revit.doc

# 🔹 Настройки
FAMILY_NAME = "Create Column"
PARAM_B = "B"
PARAM_H = "H"
PARAM_MARK = "Mark"
PARAM_REBAR_QTY_X = "Rebar_QuantityX"
PARAM_REBAR_QTY_Y = "Rebar_QuantityY"
PARAM_LEVEL = "PR_Level"

COLUMN_NUMBER_FAMILY_NAME = "PR_Column Number"
PARAM_NUMBER = "Num"  # первое значение
PARAM_NUMBER2 = "Num2"  # второе значение (для диапазона)
PARAM_NUMBER_PLUS = "Num+"  # булевый (True, если диапазон)

STIRRUP_FAMILY_NAME = "PEER_Rebar_Shape 52"
PARAM_REBAR_A = "Rebar_A"  # ширина хомута
PARAM_REBAR_B = "Rebar_B"  # высота хомута
PARAM_REBAR_NUMBER = "Rebar_Number"  # диаметр хомута (мм)


STAPLE_FAMILY_NAME_CANDIDATES = ["PEER_Rebar Shape 61", "PEER_Rebar_Shape 61"]  # поддержка обоих вариантов имени
TEXT_NOTE_TYPE_NAME = "Structural 3.5"  # <-- Укажи здесь нужное название типа текста!
DIMENSION_TYPE_NAME = "PEER-Linear"  # Например: "1.00", "2.5mm"


col_tag_type = None
for tag_type in FilteredElementCollector(doc).OfClass(FamilySymbol).OfCategory(BuiltInCategory.OST_DetailComponentTags):
    name_param = tag_type.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
    tname = name_param.AsString() if name_param else None
    if tag_type.FamilyName == COL_TAG_FAMILY_NAME and tname == COL_TAG_TYPE_NAME:
        col_tag_type = tag_type
        break

if col_tag_type is None:
    forms.alert("Tag type '{}' in family '{}' not found.".format(COL_TAG_TYPE_NAME, COL_TAG_FAMILY_NAME), exitscript=True)
dimension_type = None
for dim_type in FilteredElementCollector(doc).OfClass(DimensionType):
    param = dim_type.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
    if param and param.AsString() == DIMENSION_TYPE_NAME:
        dimension_type = dim_type
        break

if not dimension_type:
    dimension_type = FilteredElementCollector(doc).OfClass(DimensionType).FirstElement()




# Ask the user for sheet width in cm
width_cm_str = forms.ask_for_string(
    prompt="Enter sheet width in cm:",
    default="59.4",  # default value
    title="Sheet Width (cm)"
)

# Validate and convert to float
try:
    width_cm = float(width_cm_str.replace(",", "."))
    MAX_ROW_WIDTH_CM = width_cm *25
except (ValueError, AttributeError):
    forms.alert("Invalid value! Using default value: 59.4 cm.")
    width_cm = 59.4
    MAX_ROW_WIDTH_CM= width_cm*25

cover_cm_str = forms.ask_for_string(
    prompt="Enter cover for columns",
    default="2.5",  # default value
    title="Cover"
)

# Validate and convert to float
try:
    cover_cm = float(cover_cm_str.replace(",", "."))
    cover_mm = cover_cm*10
except (ValueError, AttributeError):
    forms.alert("Invalid value! Using default value: 2.5 cm.")
    cover_mm = 25





# 🔹 Drafting View
view_name = forms.ask_for_string(default="Column 150", prompt="Enter a name for Drafting View")
if not view_name:
    forms.alert("Drafting View name not specified. Script stopped.", exitscript=True)





drafting_view = None
for view in FilteredElementCollector(doc).OfClass(ViewDrafting):
    if view.Name == view_name:
        drafting_view = view
        break

if not drafting_view:
    # Если вида нет — создаём новый
    with Transaction(doc, "Create Drafting View") as t:
        t.Start()
        # Получаем любой существующий тип Drafting View
        view_types = list(FilteredElementCollector(doc).OfClass(ViewDrafting))
        if view_types:
            vt = view_types[0].GetTypeId()
        else:
            vt = None
        drafting_view = ViewDrafting.Create(doc, vt)
        drafting_view.Name = view_name
        t.Commit()
else:
    with Transaction(doc, "Очистка текущего вида") as t:
        t.Start()
        for el in FilteredElementCollector(doc, drafting_view.Id).WhereElementIsNotElementType():
            if getattr(el, "Symbol", None):
                doc.Delete(el.Id)
        t.Commit()

family_symbol = None
for symbol in FilteredElementCollector(doc).OfClass(FamilySymbol):
    if symbol.FamilyName == FAMILY_NAME:
        family_symbol = symbol
        break
if family_symbol is None:
    forms.alert("Family '{}' not found.".format(FAMILY_NAME), exitscript=True)

# Поиск семейства хомута
stirrup_symbol = None
for symbol in FilteredElementCollector(doc).OfClass(FamilySymbol):
    if symbol.FamilyName == STIRRUP_FAMILY_NAME:
        stirrup_symbol = symbol
        break
if stirrup_symbol is None:
    forms.alert("Family '{}' not found.".format(STIRRUP_FAMILY_NAME), exitscript=True)

# Поиск семейства шпильки (Shape 61)
staple_symbol = None
for symbol in FilteredElementCollector(doc).OfClass(FamilySymbol):
    if symbol.FamilyName in STAPLE_FAMILY_NAME_CANDIDATES:
        staple_symbol = symbol
        break
if staple_symbol is None:
    forms.alert("Family '{}' not found.".format(" / ".join(STAPLE_FAMILY_NAME_CANDIDATES)), exitscript=True)

# Поиск типа тэга для хомутов
stirrup_tag_type = None
for tag_type in FilteredElementCollector(doc).OfClass(FamilySymbol).OfCategory(BuiltInCategory.OST_DetailComponentTags):
    name_param = tag_type.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
    tag_type_name = name_param.AsString() if name_param else None
    if tag_type.FamilyName == STIRRUP_TAG_FAMILY_NAME and tag_type_name == STIRRUP_TAG_TYPE_NAME:
        stirrup_tag_type = tag_type
        break

if stirrup_tag_type is None:
    forms.alert("Tag type '{}' in family '{}' not found.".format(STIRRUP_TAG_TYPE_NAME, STIRRUP_TAG_FAMILY_NAME), exitscript=True)

# 🔹 Сбор уникальных уровней PR_Level
all_columns = list(FilteredElementCollector(doc)
                   .OfCategory(BuiltInCategory.OST_StructuralColumns)
                   .WhereElementIsNotElementType())
levels = set()
for col in all_columns:
    level_param = col.LookupParameter(PARAM_LEVEL)
    if level_param and level_param.HasValue:
        levels.add(level_param.AsString())
levels = sorted([lvl for lvl in levels if lvl])
if not levels:
    forms.alert("No PR_Level values found for columns.", exitscript=True)

selected_level = forms.SelectFromList.show(levels, title="Select a Level (PR_Level)")
if not selected_level:
    forms.alert("Level not selected. Script stopped.", exitscript=True)

from collections import defaultdict

low_rebar_marks = []  # Список марок колонн с малым армированием

grouped_columns = defaultdict(lambda: {"marks": [], "width": 0, "height": 0, "rebar_qty_x": 0, "rebar_qty_y": 0, "rebar_diam": 0})
for col in all_columns:
    level_param = col.LookupParameter(PARAM_LEVEL)
    if not (level_param and level_param.HasValue and level_param.AsString() == selected_level):
        continue
    mark_param = col.LookupParameter(PARAM_MARK)
    col_mark = mark_param.AsString() if mark_param and mark_param.HasValue else "N/A"
    col_type = doc.GetElement(col.GetTypeId())
    width = col_type.LookupParameter(PARAM_B)
    height = col_type.LookupParameter(PARAM_H)
    width_value = width.AsDouble() if width else 0
    height_value = height.AsDouble() if height else 0
    rebar_qty_x = col.LookupParameter(PARAM_REBAR_QTY_X)
    rebar_qty_y = col.LookupParameter(PARAM_REBAR_QTY_Y)
    qty_x = rebar_qty_x.AsDouble() if rebar_qty_x and rebar_qty_x.HasValue else 0
    qty_y = rebar_qty_y.AsDouble() if rebar_qty_y and rebar_qty_y.HasValue else 0
    rebar_diam_param = col.LookupParameter("Rebar_Diameter")
    rebar_diam_value = rebar_diam_param.AsDouble() if rebar_diam_param and rebar_diam_param.HasValue else 0


    key = (round(width_value, 6), round(height_value, 6), qty_x, qty_y)
    grouped_columns[key]["marks"].append(col_mark)
    grouped_columns[key]["width"] = width_value
    grouped_columns[key]["height"] = height_value
    grouped_columns[key]["rebar_qty_x"] = qty_x
    grouped_columns[key]["rebar_qty_y"] = qty_y
    grouped_columns[key]["rebar_diam"] = rebar_diam_value

columns_data = []
for data in grouped_columns.values():
    columns_data.append({
        "marks": data["marks"],
        "width": data["width"],
        "height": data["height"],
        "rebar_qty_x": data["rebar_qty_x"],
        "rebar_qty_y": data["rebar_qty_y"],
        "rebar_diam": data["rebar_diam"]
    })
columns_data.sort(key=lambda c: (-c["width"] * c["height"], -c["rebar_qty_x"]-c["rebar_qty_y"],-c["rebar_diam"]))

spacing_ft = 200 * 0.0328084
max_row_width_ft = MAX_ROW_WIDTH_CM / 100.0 * 3.28084  # из см в футы
current_row_width = 0
current_row_y = 0




def mm_to_ft(mm):
    return mm / 304.8


def ft_to_mm(ft):
    return ft * 304.8



def place_column_tag_force(doc, view, family_instance, tag_type, dx_mm=0.0, dy_mm=0.0):
    """
    Ставит тэг для Create Column и жёстко переносит его в правый-верхний угол рамки
    (bbox.Max) + зазоры dx_mm/dy_mm. Работает даже если Revit игнорирует точку создания.
    """
    try:
        doc.Regenerate()
        bbox = family_instance.get_BoundingBox(view)
        if not bbox:
            return

        # Целевая точка: верхний-правый угол + зазоры
        target = XYZ(bbox.Max.X + mm_to_ft(dx_mm), bbox.Max.Y + mm_to_ft(dy_mm), 0)

        # Создаём тэг (точка при создании может проигнорироваться — не страшно)
        base_pt = XYZ((bbox.Min.X + bbox.Max.X)/2.0, (bbox.Min.Y + bbox.Max.Y)/2.0, 0)
        tag = IndependentTag.Create(
            doc, view.Id, Reference(family_instance), False,
            TagMode.TM_ADDBY_CATEGORY, TagOrientation.Horizontal, base_pt
        )
        tag.ChangeTypeId(tag_type.Id)

        doc.Regenerate()

        # На всякий случай снимем pin
        try:
            if tag.Pinned:
                tag.Pinned = False
        except:
            pass

        # 1) Пытаемся сместить через TagHeadPosition (самый надёжный способ)
        set_ok = False
        try:
            # В некоторых версиях проще сначала включить выноску
            try:
                tag.HasLeader = True
                doc.Regenerate()
            except:
                pass

            tag.TagHeadPosition = target
            doc.Regenerate()

            try:
                tag.HasLeader = False
                doc.Regenerate()
            except:
                pass

            set_ok = True
        except:
            set_ok = False

        # 2) Fallback: двигаем элемент на разницу координат
        if not set_ok:
            cur = None
            try:
                cur = tag.TagHeadPosition
            except:
                loc = getattr(tag, "Location", None)
                cur = getattr(loc, "Point", None) if loc else None

            if cur:
                ElementTransformUtils.MoveElement(doc, tag.Id, target - cur)
                doc.Regenerate()

    except Exception as e:
        print("❌ Tag place/move error: {}".format(e))


def rotate_element_around_z(doc, element, angle_deg, base_point=None):
    """
    Поворачивает элемент вокруг оси Z на указанный угол в градусах.

    doc         — текущий документ Revit
    element     — элемент Revit (instance или symbol)
    angle_deg   — угол в градусах (+ против часовой стрелки, - по часовой)
    base_point  — точка вращения (XYZ), если None — берётся LocationPoint элемента
    """
    # Получаем точку вращения
    if base_point is None:
        loc = element.Location
        if hasattr(loc, "Point"):
            base_point = loc.Point
        else:
            raise ValueError("Элемент не имеет LocationPoint. Укажи base_point вручную.")

    # Создаём ось вращения (линия по оси Z)
    axis = Line.CreateBound(base_point, base_point + XYZ(0, 0, 1))

    # Преобразуем угол в радианы
    angle_rad = math.radians(angle_deg)

    # Вращаем элемент
    ElementTransformUtils.RotateElement(doc, element.Id, axis, angle_rad)


def place_tag_forced(doc, view, ref_el, tag_type, desired_head_pt, leader_end_pt=None):
    """
    Создаёт тег по категории и насильно ставит голову в desired_head_pt.
    Работает на старых и новых API:
      - пробуем SetTagHeadPosition
      - если недоступно — MoveElement по дельте
    Делаем с лидером (Revit послушнее), затем отключаем при необходимости.
    """
    st = SubTransaction(doc)
    st.Start()

    # 1) Создаём с лидером
    tag = IndependentTag.Create(
        doc, view.Id, Reference(ref_el), True,
        TagMode.TM_ADDBY_CATEGORY, TagOrientation.Horizontal, desired_head_pt
    )
    tag.ChangeTypeId(tag_type.Id)
    doc.Regenerate()

    # 2) Задаём конец/локоть лидера (по желанию) — помогает зафиксировать якорь
    try:
        if leader_end_pt is not None:
            tag.SetLeaderEnd(leader_end_pt)   # доступно в новых версиях
        # Можно ещё: tag.SetLeaderElbow(XYZ(...)) — если нужно «колено»
    except:
        pass
    doc.Regenerate()

    # 3) Ставим голову тега именно туда, где хотим
    try:
        tag.SetTagHeadPosition(desired_head_pt)  # новые версии API
    except:
        # fallback: двигаем весь тег на дельту до нужной головы
        try:
            current = tag.TagHeadPosition
            ElementTransformUtils.MoveElement(doc, tag.Id, desired_head_pt - current)
        except:
            # крайний случай — просто сдвиг по Y на фиксированную величину
            # (если TagHeadPosition недоступен в API твоей версии)
            ElementTransformUtils.MoveElement(doc, tag.Id, XYZ(0, desired_head_pt.Y, 0))
    doc.Regenerate()

    # 4) Отключаем лидер, если он не нужен
    try:
        tag.HasLeader = False
    except:
        pass
    doc.Regenerate()

    st.Commit()
    return tag












with Transaction(doc, "Place Columns") as t:
    t.Start()
    if not family_symbol.IsActive:
        family_symbol.Activate()
    if not stirrup_symbol.IsActive:
        stirrup_symbol.Activate()
    if not staple_symbol.IsActive:
        staple_symbol.Activate()
    if not stirrup_tag_type.IsActive:
        stirrup_tag_type.Activate()
    if not col_tag_type.IsActive:
        col_tag_type.Activate()
    stirrups_to_place = []
    for col_data in columns_data:
        width = col_data["width"]
        height = col_data["height"]
        if width > 0 and height > 0:
            if current_row_width + width > max_row_width_ft:
                current_row_width = 0
                current_row_y -= (height + spacing_ft)
            location_point = XYZ(current_row_width, current_row_y, 0)
            instance = doc.Create.NewFamilyInstance(location_point, family_symbol, drafting_view,)
            eid = instance.Id
            # Устанавливаем B и H
            p_b = instance.LookupParameter(PARAM_B)
            if p_b:
                p_b.Set(width)

            p_h = instance.LookupParameter(PARAM_H)
            if p_h:
                p_h.Set(height)
            # тэг в правый-верхний угол без зазоров (или, например, +50 мм по X/Y)
            place_column_tag_force(doc, drafting_view, instance, col_tag_type, dx_mm=0.0, dy_mm=0.0)

            # Получаем Reference границ из семейства
            ref_left = instance.GetReferenceByName("Left")
            ref_right = instance.GetReferenceByName("Right")
            ref_top = instance.GetReferenceByName("Top")
            ref_bottom = instance.GetReferenceByName("Bottom")
            # Горизонтальный размер (ширина)
            if ref_left and ref_right:
                ref_array_h = ReferenceArray()
                ref_array_h.Append(ref_left)
                ref_array_h.Append(ref_right)
                offset_horizontal = XYZ(0, -0.5, 0)
                pt1 = location_point + offset_horizontal
                pt2 = XYZ(location_point.X + width, location_point.Y, 0) + offset_horizontal
                dim_line_h = Line.CreateBound(pt1, pt2)
                doc.Create.NewDimension(drafting_view, dim_line_h, ref_array_h,dimension_type)
            # Вертикальный размер (высота)
            if ref_top and ref_bottom:
                ref_array_v = ReferenceArray()
                ref_array_v.Append(ref_bottom)
                ref_array_v.Append(ref_top)
                offset_vertical = XYZ(-0.5, 0, 0)
                pt3 = location_point + offset_vertical
                pt4 = XYZ(location_point.X, location_point.Y + height, 0) + offset_vertical
                dim_line_v = Line.CreateBound(pt3, pt4)
                doc.Create.NewDimension(drafting_view, dim_line_v, ref_array_v,dimension_type)

            # Новый параметр армирования
            p_rebar_qty_x = instance.LookupParameter(PARAM_REBAR_QTY_X)
            if p_rebar_qty_x:
                try:
                    p_rebar_qty_x.Set(col_data["rebar_qty_x"])
                except Exception as e:
                    print("Error setting {}: {}".format(PARAM_REBAR_QTY_X, e))

            p_rebar_qty_y = instance.LookupParameter(PARAM_REBAR_QTY_Y)
            if p_rebar_qty_y:
                try:
                    p_rebar_qty_y.Set(col_data["rebar_qty_y"])
                except Exception as e:
                    print("Error setting {}: {}".format(PARAM_REBAR_QTY_Y, e))
            # Устанавливаем Rebar_Diameter
            p_rebar_diam = instance.LookupParameter("Rebar_Diameter")
            if p_rebar_diam:
                try:
                    p_rebar_diam.Set(col_data["rebar_diam"])
                except Exception as e:
                    print("Error setting Rebar_Diameter: {}".format(e))

            #Устанавливаем защитный слой

            p_cover = instance.LookupParameter("Cover")
            if p_cover:
                try:
                    p_cover.Set(mm_to_ft(cover_mm))
                except Exception as e:
                    print("Error setting Cover: {}".format(e))
            # Добавляем текст на иврите только с размерами колонны


            text_type = None
            for ttype in FilteredElementCollector(doc).OfClass(TextNoteType):
                type_name = ttype.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM).AsString()
                if type_name == TEXT_NOTE_TYPE_NAME:
                    text_type = ttype.Id
                    break
            if not text_type:
                text_type=create_TextType(doc,
                                          TEXT_NOTE_TYPE_NAME,
                                          size_mm=3.5,
                                          font="TN_CalibriL_Structural",
                                          width_factor=1)


            b_int = int(round(width * 30.48))  # футы -> см
            h_int = int(round(height * 30.48))  # футы -> см
            hebrew_text = u"עמוד {}/{}".format(b_int, h_int)
            text_location = location_point + XYZ(0, -1.2, 0)
            text_note = TextNote.Create(doc, drafting_view.Id, text_location,
                                        hebrew_text, text_type)
            # Размещаем семейства с номерами марок (PR_Column Number)
            column_number_symbol = None
            for symbol in FilteredElementCollector(doc).OfClass(FamilySymbol):
                if symbol.FamilyName == COLUMN_NUMBER_FAMILY_NAME:
                    column_number_symbol = symbol
                    break
            if column_number_symbol is not None:
                if not column_number_symbol.IsActive:
                    column_number_symbol.Activate()
                marks_sorted = sorted(col_data["marks"], key=lambda m: int(m) if m.isdigit() else m)
                marks_for_inserts = build_marks_and_ranges(marks_sorted)
                row = 0
                items_in_row = 0
                cur_x = text_location.X - 21 * 0.0328084  # стартовая позиция по X (слева от подписи)
                cur_y = text_location.Y - 5.5 * 0.0328084
                for idx, mark_dict in enumerate(marks_for_inserts):
                    if (items_in_row >= 5) or (items_in_row >= 2 and mark_dict['num_plus']):
                        row += 1
                        cur_x = text_location.X - 21 * 0.0328084
                        cur_y = cur_y - row * 21 * 0.0328084
                        items_in_row = 0
                    mark_location = XYZ(cur_x, cur_y, 0)
                    mark_instance = doc.Create.NewFamilyInstance(mark_location, column_number_symbol, drafting_view)
                    p_number = mark_instance.LookupParameter(PARAM_NUMBER)
                    p_number2 = mark_instance.LookupParameter(PARAM_NUMBER2)
                    p_num_plus = mark_instance.LookupParameter(PARAM_NUMBER_PLUS)
                    if p_number:
                        p_number.Set(str(mark_dict['num']))
                    if p_number2:
                        if mark_dict['num2']:
                            p_number2.Set(str(mark_dict['num2']))
                        else:
                            p_number2.Set("")
                    if p_num_plus:
                        p_num_plus.Set(1 if mark_dict['num_plus'] else 0)
                    cur_x -= (mark_dict['width'] * 0.0328084)
                    items_in_row += 1
            else:
                print("Family PR_Column Number not found")


            # Данные для размещения хомута сохраняем для второго прохода
            doc.Regenerate()
            inst = doc.GetElement(eid)
            hasHorizontalSpacer_param = inst.LookupParameter("HasHorizontalSpacer")
            hasHorizontalSpacer = hasHorizontalSpacer_param.AsInteger()

            hasVerticalSpacer_param = inst.LookupParameter("HasVerticalSpacer")
            hasVerticalSpacer= hasVerticalSpacer_param.AsInteger()
            stirrups_to_place.append({
                "location_point": location_point,
                "width": width,
                "height": height,
                "hasVerticalSpacer":hasVerticalSpacer,
                "hasHorizontalSpacer":hasHorizontalSpacer
            })

            current_row_width += width + spacing_ft

    # После расстановки всех колонн и аннотаций — расставляем хомуты



    for stirrup_info in stirrups_to_place:
        loc = stirrup_info["location_point"]
        width = stirrup_info["width"]
        height = stirrup_info["height"]
        hasVerticalSpacer = stirrup_info["hasVerticalSpacer"]
        hasHorizontalSpacer = stirrup_info["hasHorizontalSpacer"]
        # Смещение: центр хомута на 30 см правее ПРАВОГО края колонны
        center_x = loc.X+width/2
        center_y = loc.Y + height / 2
        stirrup_x = center_x + width
        stirrup_location = XYZ(stirrup_x, center_y, 0)
        stirrup_instance = doc.Create.NewFamilyInstance(stirrup_location, stirrup_symbol, drafting_view)

        # Автоматическое определение единиц: если width > 10 — это мм, иначе футы


        if width > 10:
            stirrup_a = width - (2*cover_cm)*10
            stirrup_b = height - (2*cover_cm)*10
        else:
            stirrup_a = width * 304.8 - (2*cover_cm)*10
            stirrup_b = height * 304.8 - (2*cover_cm)*10
        p_stirrup_a = stirrup_instance.LookupParameter(PARAM_REBAR_A)
        p_stirrup_b = stirrup_instance.LookupParameter(PARAM_REBAR_B)
        if p_stirrup_a:
            p_stirrup_a.Set(mm_to_ft(stirrup_a))
        if p_stirrup_b:
            p_stirrup_b.Set(mm_to_ft(stirrup_b))
        p_rebar_number = stirrup_instance.LookupParameter("Rebar_Diameter")
        if p_rebar_number:
            p_rebar_number.Set(mm_to_ft(8))
        p_rebar_spacing = stirrup_instance.LookupParameter("Rebar_Spacing")
        if p_rebar_spacing:
            p_rebar_spacing.Set(mm_to_ft(200))

        # --- ДОБАВЛЕНИЕ ТЭГА под хомутом ---
        # stirrup_b — высота хомута в мм
        stirrup_b_ft = mm_to_ft(stirrup_b+350)  # в футах
        Space_x=mm_to_ft(300)
        tag_y = stirrup_location.Y - stirrup_b_ft / 2  # низ хомута = верх тэга
        tag_x = stirrup_location.X + Space_x  # низ хомута = верх тэга
        tag_location = XYZ(tag_x, tag_y, 0)
        stirrup_tag = IndependentTag.Create(
            doc,
            drafting_view.Id,
            Reference(stirrup_instance),
            False,  # isLeader
            TagMode.TM_ADDBY_CATEGORY,
            TagOrientation.Horizontal,
            tag_location
        )
        stirrup_tag.ChangeTypeId(stirrup_tag_type.Id)

        # ============================
        # ВТОРАЯ ФОРМА: ШПИЛЬКА (Shape 61)
        # ============================

        if hasVerticalSpacer==1:

            staple_x = stirrup_location.X + mm_to_ft(SECOND_REBAR_OFFSET_MM)+mm_to_ft(stirrup_a/2)  # правее хомута
            staple_y = stirrup_location.Y
            staple_pt = XYZ(staple_x, staple_y, 0)

            staple_instance = doc.Create.NewFamilyInstance(staple_pt, staple_symbol, drafting_view)

            # Размеры шпильки: по высоте H - 50 мм, по ширине B - 50 мм (как у хомута)
            # width/height тут в футах; переводим в мм → вычитаем 50 → обратно в футы

            staple_b_mm = max(0.0, ft_to_mm(height) - (2*cover_cm)*10)  # высота по Y

            pA_s = staple_instance.LookupParameter(PARAM_REBAR_B)

            if pA_s: pA_s.Set(mm_to_ft(staple_b_mm))


            p_diam_s = staple_instance.LookupParameter("Rebar_Diameter")
            if p_diam_s: p_diam_s.Set(mm_to_ft(8))
            p_step_s = staple_instance.LookupParameter("Rebar_Spacing")
            if p_step_s: p_step_s.Set(mm_to_ft(200))

            # Тег под шпилькой (тот же тип тэга)
            staple_tag_y = tag_y + mm_to_ft(staple_b_mm/2)
            staple_tag_x = staple_pt.X + mm_to_ft(200)
            staple_tag_pt = XYZ(staple_tag_x, staple_tag_y, 0)

            staple_tag = IndependentTag.Create(
                doc,
                drafting_view.Id,
                Reference(staple_instance),
                False,
                TagMode.TM_ADDBY_CATEGORY,
                TagOrientation.Horizontal,
                staple_tag_pt
            )
            staple_tag.ChangeTypeId(stirrup_tag_type.Id)

        if hasHorizontalSpacer == 1:
            distance = mm_to_ft(220)
            staple_y = loc.Y + height + distance  # к центру колонны
            staple_x = loc.X + width / 2
            staple_pt = XYZ(staple_x, staple_y, 0)

            staple_instance = doc.Create.NewFamilyInstance(staple_pt, staple_symbol, drafting_view)

            # --- параметры шпильки ---
            staple_b_mm = max(0.0, ft_to_mm(width) - (2*cover_cm)*10)  # высота по Y
            pA_s = staple_instance.LookupParameter(PARAM_REBAR_B)
            if pA_s:
                pA_s.Set(mm_to_ft(staple_b_mm))

            p_diam_s = staple_instance.LookupParameter("Rebar_Diameter")
            if p_diam_s: p_diam_s.Set(mm_to_ft(8))
            p_step_s = staple_instance.LookupParameter("Rebar_Spacing")
            if p_step_s: p_step_s.Set(mm_to_ft(200))

            # Вращаем вокруг своей точки вставки
            rotate_element_around_z(doc, staple_instance, 90, staple_pt)

            # ⚠️ Зафиксировать геометрию шпильки перед созданием тега
            doc.Regenerate()

            # --- создаём тег немного выше ---
            staple_tag_y = staple_y + mm_to_ft(220)
            staple_tag_x = staple_x
            doc.Regenerate()

            desired_head_pt = XYZ(staple_tag_x , staple_tag_y, 0)
            leader_end_pt = staple_pt  # логично привязать конец лидера к шпильке

            staple_tag = place_tag_forced(
                doc=doc,
                view=drafting_view,
                ref_el=staple_instance,
                tag_type=stirrup_tag_type,
                desired_head_pt=desired_head_pt,
                leader_end_pt=leader_end_pt
            )

    t.Commit()

t=Transaction(doc,"Numeration")
t.Start()
process_drafting_view(doc,drafting_view)
t.Commit()
if low_rebar_marks:
    msg = "No rebar found in columns with marks: {}. Please correct this.".format(", ".join(low_rebar_marks))
    forms.alert(msg)
else:
    forms.alert("Script completed successfully. Families placed and parameters set.")
