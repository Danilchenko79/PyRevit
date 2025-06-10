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
    BuiltInParameter,
    TextNoteType,
    TextNote,
    IndependentTag, TagMode, TagOrientation, Reference
)

# Параметры для размещения тэга под хомутом
STIRRUP_TAG_FAMILY_NAME = "Detail items_Tag Rebar(Text Quantity)"  # Имя семейства тэга
STIRRUP_TAG_TYPE_NAME = "Tag Rebar"  # Имя типа тэга
TAG_OFFSET_DOWN_CM = 25  # см вниз от центра хомута

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

STIRRUP_FAMILY_NAME = "PEER_Rebar_Shape 52(x)"
PARAM_REBAR_A = "Rebar_A"  # ширина хомута
PARAM_REBAR_B = "Rebar_B"  # высота хомута
PARAM_REBAR_NUMBER = "Rebar_Number"  # диаметр хомута (мм)

TEXT_NOTE_TYPE_NAME = "Stractural 2.6"  # <-- Укажи здесь нужное название типа текста!

MAX_ROW_WIDTH_CM = 2300  # Максимальная ширина ряда в см на самом виде

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
    forms.alert("View '{}' not found.".format(view_name), exitscript=True)

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
columns_data.sort(key=lambda c: (-c["width"] * c["height"], -c["rebar_qty_x"]-c["rebar_qty_y"]))

spacing_ft = 200 * 0.0328084
max_row_width_ft = MAX_ROW_WIDTH_CM / 100.0 * 3.28084  # из см в футы
current_row_width = 0
current_row_y = 0

with Transaction(doc, "Place Columns") as t:
    t.Start()
    if not family_symbol.IsActive:
        family_symbol.Activate()
    if not stirrup_symbol.IsActive:
        stirrup_symbol.Activate()
    if not stirrup_tag_type.IsActive:
        stirrup_tag_type.Activate()
    stirrups_to_place = []
    for col_data in columns_data:
        width = col_data["width"]
        height = col_data["height"]
        if width > 0 and height > 0:
            if current_row_width + width > max_row_width_ft:
                current_row_width = 0
                current_row_y -= (height + spacing_ft)
            location_point = XYZ(current_row_width, current_row_y, 0)
            instance = doc.Create.NewFamilyInstance(location_point, family_symbol, drafting_view)
            # Устанавливаем B и H
            p_b = instance.LookupParameter(PARAM_B)
            if p_b: p_b.Set(width)
            p_h = instance.LookupParameter(PARAM_H)
            if p_h: p_h.Set(height)
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
                doc.Create.NewDimension(drafting_view, dim_line_h, ref_array_h)
            # Вертикальный размер (высота)
            if ref_top and ref_bottom:
                ref_array_v = ReferenceArray()
                ref_array_v.Append(ref_bottom)
                ref_array_v.Append(ref_top)
                offset_vertical = XYZ(-0.5, 0, 0)
                pt3 = location_point + offset_vertical
                pt4 = XYZ(location_point.X, location_point.Y + height, 0) + offset_vertical
                dim_line_v = Line.CreateBound(pt3, pt4)
                doc.Create.NewDimension(drafting_view, dim_line_v, ref_array_v)

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
            # Добавляем текст на иврите только с размерами колонны

            text_type = None
            for ttype in FilteredElementCollector(doc).OfClass(TextNoteType):
                type_name = ttype.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM).AsString()
                if type_name == TEXT_NOTE_TYPE_NAME:
                    text_type = ttype
                    break
            if not text_type:
                text_type = FilteredElementCollector(doc).OfClass(TextNoteType).FirstElement()

            b_int = int(round(width * 30.48))  # футы -> см
            h_int = int(round(height * 30.48))  # футы -> см
            hebrew_text = u"עמוד {}/{}".format(b_int, h_int)
            text_location = location_point + XYZ(0, -1.2, 0)
            text_note = TextNote.Create(doc, drafting_view.Id, text_location,
                                        hebrew_text, text_type.Id)
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
            stirrups_to_place.append({
                "location_point": location_point,
                "width": width,
                "height": height
            })

            current_row_width += width + spacing_ft

    # После расстановки всех колонн и аннотаций — расставляем хомуты
    def mm_to_ft(mm):
        return mm / 304.8

    for stirrup_info in stirrups_to_place:
        loc = stirrup_info["location_point"]
        width = stirrup_info["width"]
        height = stirrup_info["height"]
        # Смещение: центр хомута на 30 см правее ПРАВОГО края колонны
        center_x = loc.X+width/2
        center_y = loc.Y + height / 2
        stirrup_x = center_x + width
        stirrup_location = XYZ(stirrup_x, center_y, 0)
        stirrup_instance = doc.Create.NewFamilyInstance(stirrup_location, stirrup_symbol, drafting_view)

        # Автоматическое определение единиц: если width > 10 — это мм, иначе футы
        def mm_to_ft(mm):
            return mm / 304.8

        if width > 10:
            stirrup_a = width - 50
            stirrup_b = height - 50
        else:
            stirrup_a = width * 304.8 - 50
            stirrup_b = height * 304.8 - 50
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

    t.Commit()

if low_rebar_marks:
    msg = "No rebar found in columns with marks: {}. Please correct this.".format(", ".join(low_rebar_marks))
    forms.alert(msg)
else:
    forms.alert("Script completed successfully. Families placed and parameters set.")
