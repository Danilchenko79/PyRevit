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
if not selected_levels:
    alert("Не выбран ни один уровень.")
    raise SystemExit

# Получить все типы рамок (TitleBlocks)
titleblocks = list(DB.FilteredElementCollector(doc)
    .OfClass(DB.FamilySymbol)
    .OfCategory(DB.BuiltInCategory.OST_TitleBlocks))

if not titleblocks:
    alert(u"В проекте не найдено ни одного шаблона рамки!")
    raise SystemExit


selected_titleblock = SelectFromList.show(
    titleblocks,
    name_attr="FamilyName",  # Или "Name" если нужно полное имя типа
    title="Выберите тип рамки для новых листов",
    multiselect=False
)

if not selected_titleblock:
    alert(u"Не выбран ни один тип рамки.")
    raise SystemExit

sheet_type_id = selected_titleblock.Id





def ft_to_m(number):
    return number * 0.3048


def elevation_str(elev):
    m = round(elev, 2)
    # Сначала число, потом знак, чтобы получить 5.10+ или 3.60-
    return u"{}{}".format(abs(m), "+" if m >= 0 else "-")






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

## --- ПОДГОТОВКА СПИСКОВ СУЩЕСТВУЮЩИХ ЛИСТОВ И ВИДОВ ---

all_sheet_numbers = set([s.SheetNumber for s in DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet)])

# Получить имена всех существующих видов
all_view_names = set([v.Name for v in DB.FilteredElementCollector(doc).OfClass(DB.View) if hasattr(v, 'Name')])

# --- СОЗДАНИЕ ЛИСТОВ ---
# Соберём только уровни из allowed_bases, отсортированные по Elevation
allowed_levels = sorted(
    [lvl for lvl in levels if extract_base_from_name(lvl.Name) is not None],
    key=lambda l: l.Elevation
)

# Мапа: base_number -> уровень
base_to_level = {extract_base_from_name(lvl.Name): lvl for lvl in allowed_levels}

for current_level in selected_levels:
    base_number = extract_base_from_name(current_level.Name)
    if base_number is None:
        continue

    relative_elevation = ft_to_m(current_level.Elevation)

    sheet_data = [
        (u"תכנית תבניות במפלס {}".format(elevation_str(relative_elevation)), str(base_number)),
        (u"תכנית זיון תקרה במפלס {}".format(elevation_str(relative_elevation)), str(base_number + 2))
    ]

    # Найти среди всех allowed_levels предыдущий (ниже по Elevation)
    prev_allowed_level = None
    for lvl in reversed(allowed_levels):
        if lvl.Elevation < current_level.Elevation:
            prev_allowed_level = lvl
            break

    if prev_allowed_level is not None:
        lower_relative_elevation = ft_to_m(prev_allowed_level.Elevation)
        sheet_data.append((
            u"תכנית זיון קירות ממפלס {} עד {}".format(
                elevation_str(lower_relative_elevation), elevation_str(relative_elevation)
            ),
            str(base_number + 5)
        ))

    # Если нет prev_allowed_level — не делаем лист диапазона!

    for sheet_name, sheet_number in sheet_data:
        if sheet_number not in all_sheet_numbers:
            create_sheet(sheet_name, sheet_number)
            all_sheet_numbers.add(sheet_number)


# --- СОЗДАНИЕ ВИДОВ ---
# Находим нужные типы видов с корректным получением имени
view_family_types = DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType)
re_type = None
gr_type = None
for vft in view_family_types:
    if vft.ViewFamily == DB.ViewFamily.StructuralPlan:
        vft_name = vft.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString()
        if vft_name == "Structural Plan RE":
            re_type = vft
        elif vft_name == "Structural Plan GR":
            gr_type = vft
if not (re_type and gr_type):
    alert(u"Не найден нужный тип вида Structural Plan RE или GR!")
    exit()

created_views = []
with DB.Transaction(doc, "Create Structural Plan Views for Levels") as t:
    t.Start()
    for current_level in selected_levels:
        base_number = extract_base_from_name(current_level.Name)
        if base_number is None:
            continue
        # Structural Plan RE
        view_name_re = "{}RE".format(base_number)
        if view_name_re not in all_view_names:
            new_view_re = DB.ViewPlan.Create(doc, re_type.Id, current_level.Id)
            new_view_re.Name = view_name_re
            created_views.append(new_view_re)
            all_view_names.add(view_name_re)
        # Structural Plan GR
        view_name_gr = "{}GR".format(base_number)
        if view_name_gr not in all_view_names:
            new_view_gr = DB.ViewPlan.Create(doc, gr_type.Id, current_level.Id)
            new_view_gr.Name = view_name_gr
            created_views.append(new_view_gr)
            all_view_names.add(view_name_gr)
    t.Commit()

# --- РАЗМЕЩЕНИЕ ВИДОВ НА ЛИСТАХ ---
def place_views_on_sheets_align_centers(doc, base_numbers):
    all_sheets = {s.SheetNumber: s for s in DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet)}
    all_views = {v.Name: v for v in DB.FilteredElementCollector(doc).OfClass(DB.View)
                 if hasattr(v, 'Name') and not v.IsTemplate}

    with DB.Transaction(doc, "Place & Align Views on Sheets") as t:
        t.Start()
        for base_number in base_numbers:
            sheet_number = str(base_number)
            sheet = all_sheets.get(sheet_number)
            if not sheet:
                continue
            # Имена нужных видов
            view_names = ["{}RE".format(base_number), "{}GR".format(base_number)]
            viewports = []
            # Ставим оба вида в одну точку (например, центр листа)
            # Координата центра листа (0.5, 0.5, 0) — можно менять
            pt = DB.XYZ(0.5, 0.5, 0)
            for view_name in view_names:
                view = all_views.get(view_name)
                if not view:
                    continue
                # Уже размещён? Проверяем по листу
                already_placed = any(
                    vp.ViewId == view.Id for vp in DB.FilteredElementCollector(doc)
                    .OfClass(DB.Viewport).WhereElementIsNotElementType() if vp.SheetId == sheet.Id
                )
                if already_placed:
                    continue
                viewport = DB.Viewport.Create(doc, sheet.Id, view.Id, pt)
                viewports.append(viewport)
            # Если оба вида размещены, совмещаем их центры

        t.Commit()

base_numbers_for_sheets = [
    extract_base_from_name(lvl.Name) for lvl in selected_levels
    if extract_base_from_name(lvl.Name) is not None
]
place_views_on_sheets_align_centers(doc, base_numbers_for_sheets)




alert("Листы и виды успешно созданы.")
