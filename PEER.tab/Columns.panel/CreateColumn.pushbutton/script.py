# -*- coding: utf-8 -*-
__title__ = "Create Column"
__author__ = "Dmitry D"

from pyrevit import revit, forms, script
from Autodesk.Revit.DB import (
    Transaction,
    FilteredElementCollector,
    BuiltInCategory,
    FamilySymbol,
    FamilyInstance,
    ViewDrafting,
    View,
    ViewFamily,
    ViewFamilyType,
    XYZ,
    Line,
    ReferenceArray,
    Dimension,
    DimensionType,
    BuiltInParameter,
    TextNoteType,
    TextNote,
    IndependentTag, TagMode, TagOrientation, Reference,
    ElementTransformUtils, SubTransaction, ElementId
)
from System.Collections.Generic import List
from Samples.Numeration import process_drafting_view
from Snippets._CreateTextType import create_TextType
import math

# Параметры для размещения тэга под хомутом
STIRRUP_TAG_FAMILY_NAME = "Detail items_Tag Rebar(Text Quantity)"  # Имя семейства тэга

STIRRUP_TAG_TYPE_NAME = "Tag Rebar 2∅10@20 L="  # Имя типа тэга
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


STAPLE_FAMILY_NAME_CANDIDATES = ["PEER_Rebar Shape 62", "PEER_Rebar_Shape 62"]  # поддержка обоих вариантов имени
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




# 🔹 Сбор колонн и уникальных уровней PR_Level (нужно ДО окна ввода,
#    чтобы заполнить выпадающий список уровней в форме)
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

# 🔹 ГЛАВНОЕ ОКНО: уровень сверху + редактируемая таблица групп колонн.
#    Домашний стиль PEER: forms.WPFWindow + внешний .xaml (см. lib/GUI/Resources/UI_STYLE.md).
from collections import defaultdict
import System
import clr as _clr
_clr.AddReference("System.Data")
from System.Data import DataTable


def compute_groups(level):
    """Группы колонн уровня по (B, H, Rebar X, Rebar Y, Ø).

    Возвращает (groups, no_mark_ids). Колонны без марки уходят в no_mark_ids и в
    таблицу не попадают. Диаметр/арматура могут быть 0 — пользователь заполнит их
    прямо в таблице.
    """
    grouped = defaultdict(lambda: {"marks": [], "col_ids": [],
                                   "width": 0.0, "height": 0.0,
                                   "qty_x": 0.0, "qty_y": 0.0, "diam": 0.0})
    no_mark_ids = []
    for col in all_columns:
        lp = col.LookupParameter(PARAM_LEVEL)
        if not (lp and lp.HasValue and lp.AsString() == level):
            continue
        mp = col.LookupParameter(PARAM_MARK)
        mark = mp.AsString() if mp and mp.HasValue else None
        ctype = doc.GetElement(col.GetTypeId())
        wp = ctype.LookupParameter(PARAM_B)
        hp = ctype.LookupParameter(PARAM_H)
        w = wp.AsDouble() if wp else 0.0
        h = hp.AsDouble() if hp else 0.0
        qxp = col.LookupParameter(PARAM_REBAR_QTY_X)
        qyp = col.LookupParameter(PARAM_REBAR_QTY_Y)
        qx = qxp.AsDouble() if qxp and qxp.HasValue else 0.0
        qy = qyp.AsDouble() if qyp and qyp.HasValue else 0.0
        dp = col.LookupParameter("Rebar_Diameter")
        d = dp.AsDouble() if dp and dp.HasValue else 0.0
        if not (mark and mark.strip() and mark != "N/A"):
            no_mark_ids.append(col.Id)
            continue
        key = (round(w, 6), round(h, 6), qx, qy, d)
        g = grouped[key]
        g["marks"].append(mark)
        g["col_ids"].append(col.Id)
        g["width"] = w
        g["height"] = h
        g["qty_x"] = qx
        g["qty_y"] = qy
        g["diam"] = d
    groups = list(grouped.values())
    groups.sort(key=lambda c: (-c["width"] * c["height"],
                               -c["qty_x"] - c["qty_y"], -c["diam"]))
    return groups, no_mark_ids


class CreateColumnWindow(forms.WPFWindow):
    """Окно: выбор уровня + редактируемая таблица групп."""

    def __init__(self, xaml_path, level_list):
        forms.WPFWindow.__init__(self, xaml_path)
        self.groups = []
        self.no_mark_ids = []
        self._dt = None
        for lvl in level_list:
            self.cb_level.Items.Add(lvl)
        if level_list:
            self.cb_level.SelectedIndex = 0   # триггерит on_level_changed → строит таблицу

    @staticmethod
    def _as_int(v):
        try:
            return int(round(float(v)))
        except Exception:
            return 0

    def _build_table(self, level):
        """Перестраивает таблицу групп под выбранный уровень.

        Числовые поля — типизированные (Int32), поэтому в ячейки нельзя ввести
        не-число, а столбец Total (общее число стержней) считается формулой
        DataTable и обновляется сам при правке B/H.
        """
        self.groups, self.no_mark_ids = compute_groups(level)
        dt = DataTable()
        dt.Columns.Add("Marks", System.String)
        dt.Columns.Add("Size", System.String)
        dt.Columns.Add("DiaMM", System.Int32)    # Rebar_Diameter, мм (редакт.)
        dt.Columns.Add("RebarX", System.Int32)   # Rebar Quantity_B (редакт.)
        dt.Columns.Add("RebarY", System.Int32)   # Rebar Quantity_H (редакт.)
        # Rebar Quantity_B/H — число стержней с ОДНОЙ стороны без 4 угловых.
        # Общее = 4 угловых + 2*(по B) + 2*(по H). Если оба 0 — показываем 0.
        col_total = dt.Columns.Add("Total", System.Int32)
        col_total.Expression = "IIF(RebarX = 0 AND RebarY = 0, 0, 4 + 2*RebarX + 2*RebarY)"
        for g in self.groups:
            b = int(round(g["width"] * 30.48))    # футы → см
            h = int(round(g["height"] * 30.48))
            row = dt.NewRow()
            row["Marks"] = ", ".join(sorted(g["marks"],
                                            key=lambda m: int(m) if m.isdigit() else 9999))
            row["Size"] = u"{} / {}".format(b, h)
            row["DiaMM"] = self._as_int(g["diam"] * 304.8)   # футы → мм
            row["RebarX"] = self._as_int(g["qty_x"])
            row["RebarY"] = self._as_int(g["qty_y"])
            dt.Rows.Add(row)
        self._dt = dt
        self.dg_groups.ItemsSource = dt.DefaultView

    def on_level_changed(self, sender, args):
        lvl = self.cb_level.SelectedItem
        if lvl:
            self._build_table(lvl)

    def edited_groups(self):
        """Геометрия групп + отредактированные Ø, Rebar Quantity_B/H из таблицы."""
        out = []
        if self._dt is None:
            return out
        for i, g in enumerate(self.groups):
            if i >= self._dt.Rows.Count:
                break
            r = self._dt.Rows[i]

            def _pi(name):
                v = r[name]
                try:
                    return int(v)
                except Exception:
                    return 0

            out.append({
                "marks": list(g["marks"]),
                "col_ids": list(g["col_ids"]),
                "width": g["width"],
                "height": g["height"],
                "qty_x": _pi("RebarX"),
                "qty_y": _pi("RebarY"),
                "dia_mm": _pi("DiaMM"),
            })
        return out

    def on_ok(self, sender, args):
        # Зафиксировать правку текущей ячейки/строки перед чтением таблицы.
        try:
            self.dg_groups.CommitEdit()
            self.dg_groups.CommitEdit()
        except Exception:
            pass
        if not (self.tb_view.Text or "").strip():
            forms.alert("Enter a Drafting View name.", title="Create Column")
            return
        if self.cb_level.SelectedItem is None:
            forms.alert("Select a level (PR_Level).", title="Create Column")
            return
        self.DialogResult = True
        self.Close()

    def on_cancel(self, sender, args):
        self.DialogResult = False
        self.Close()


_win = CreateColumnWindow(script.get_bundle_file("CreateColumnForm.xaml"), levels)
_win.ShowDialog()
if not _win.DialogResult:
    forms.alert("Cancelled. Script stopped.", exitscript=True)

# --- Глобальные значения (один раз для всех групп) ---
try:
    width_cm = float(str(_win.tb_width.Text).replace(",", "."))
except (ValueError, AttributeError):
    forms.alert("Invalid sheet width! Using default: 59.4 cm.")
    width_cm = 59.4
try:
    cover_cm = float(str(_win.tb_cover.Text).replace(",", "."))
    cover_mm = cover_cm * 10
except (ValueError, AttributeError):
    forms.alert("Invalid cover! Using default: 2.5 cm.")
    cover_cm = 2.5
    cover_mm = 25.0
view_name = (_win.tb_view.Text or "").strip()
selected_level = _win.cb_level.SelectedItem
no_mark_errors = list(_win.no_mark_ids)

# --- Диаметры поперечной арматуры (хомут Shape 52 и шпилька Shape 62), мм ---
try:
    stirrup_dia_mm = float(str(_win.tb_stirrup_dia.Text).replace(",", "."))
    if stirrup_dia_mm <= 0:
        raise ValueError
except (ValueError, AttributeError):
    forms.alert("Invalid stirrup diameter! Using default: 8 mm.")
    stirrup_dia_mm = 8.0
try:
    staple_dia_mm = float(str(_win.tb_staple_dia.Text).replace(",", "."))
    if staple_dia_mm <= 0:
        raise ValueError
except (ValueError, AttributeError):
    forms.alert("Invalid staple diameter! Using default: 10 mm.")
    staple_dia_mm = 10.0

# --- Из таблицы: что чертим (columns_data) и что осталось незаполненным ---
param_errors = []
columns_data = []
for g in _win.edited_groups():
    has_rebar = not (g["qty_x"] == 0 and g["qty_y"] == 0)
    has_diam = g["dia_mm"] != 0
    if not has_rebar or not has_diam:
        missing = []
        if not has_rebar:
            missing.append("Rebar_Quantity")
        if not has_diam:
            missing.append("Rebar_Diameter")
        for cid, mk in zip(g["col_ids"], g["marks"]):
            param_errors.append({"mark": mk, "id": cid, "missing": ", ".join(missing)})
        continue
    columns_data.append({
        "marks": g["marks"],
        "width": g["width"],
        "height": g["height"],
        "rebar_qty_x": g["qty_x"],
        "rebar_qty_y": g["qty_y"],
        "rebar_diam": g["dia_mm"] / 304.8,   # мм → футы
        "col_ids": g["col_ids"],
    })
columns_data.sort(key=lambda c: (-c["width"] * c["height"],
                                 -c["rebar_qty_x"] - c["rebar_qty_y"], -c["rebar_diam"]))

# 🔹 Drafting View — режим ВСЕГДА «пересоздание». Если вид существует, спрашиваем
#    подтверждение ДО любых изменений модели.
def _find_drafting_view(name):
    for v in FilteredElementCollector(doc).OfClass(ViewDrafting):
        if v.Name == name:
            return v
    return None


def _create_drafting_view(name):
    # Имя должно быть уникально среди ВСЕХ видов — иначе Create откатится.
    for v in FilteredElementCollector(doc).OfClass(View):
        if not v.IsTemplate and v.Name == name:
            forms.alert("A view named '{}' already exists (not a Drafting View). "
                        "Choose another name.".format(name), exitscript=True)
    dv_type_id = None
    for vft in FilteredElementCollector(doc).OfClass(ViewFamilyType):
        if vft.ViewFamily == ViewFamily.Drafting:
            dv_type_id = vft.Id
            break
    if dv_type_id is None:
        forms.alert("No Drafting View type found in the project.", exitscript=True)
    with Transaction(doc, "Create Drafting View") as t:
        t.Start()
        nv = ViewDrafting.Create(doc, dv_type_id)
        nv.Name = name
        try:
            nv.Scale = 25
        except Exception:
            pass
        t.Commit()
    return _find_drafting_view(name)


drafting_view = _find_drafting_view(view_name)
if drafting_view is not None:
    # Вид существует — подтверждение полной замены ДО изменений модели.
    if not forms.alert(
            "Drafting View '{}' already exists.\n\nReplace it completely?\n"
            "All its contents will be deleted and redrawn.".format(view_name),
            title="Create Column", yes=True, no=True):
        script.exit()

# --- Запись отредактированных значений обратно в колонны модели ---
with Transaction(doc, "Update Column Reinforcement") as t:
    t.Start()
    for g in columns_data:
        for cid in g.get("col_ids", []):
            model_col = doc.GetElement(cid)
            if model_col is None:
                continue
            for pname, pval in ((PARAM_REBAR_QTY_X, float(g["rebar_qty_x"])),
                                (PARAM_REBAR_QTY_Y, float(g["rebar_qty_y"])),
                                ("Rebar_Diameter", g["rebar_diam"])):
                p = model_col.LookupParameter(pname)
                if p and not p.IsReadOnly:
                    try:
                        p.Set(pval)
                    except Exception:
                        pass
    t.Commit()





# Пересоздание: вид есть — чистим содержимое; вид отсутствует/пропал — создаём ниже.
if drafting_view is not None:
    # Чистим содержимое вида. САМ вид не трогаем (исключаем его Id).
    view_id = drafting_view.Id
    with Transaction(doc, "Clear Drafting View") as t:
        t.Start()
        ids_to_delete = List[ElementId](
            [el.Id for el in FilteredElementCollector(doc, view_id)
             .WhereElementIsNotElementType() if el.Id != view_id]
        )
        if ids_to_delete.Count:
            try:
                doc.Delete(ids_to_delete)
            except Exception:
                # Пакетное удаление упало — удаляем по одному, пропуская сбои.
                for eid in ids_to_delete:
                    try:
                        doc.Delete(eid)
                    except Exception:
                        pass
        t.Commit()
    # После очистки вид иногда пропадает (какой-то элемент тянет его за собой).
    # Пере-получаем по имени; если исчез — создадим заново ниже. Скрипт не падает.
    drafting_view = _find_drafting_view(view_name)

if drafting_view is None:
    # Вида не было, либо он исчез при очистке — создаём заново.
    drafting_view = _create_drafting_view(view_name)

if drafting_view is None:
    forms.alert("Could not create Drafting View '{}'. Script stopped.".format(view_name),
                exitscript=True)

# Режим Update убран — всегда чертим все валидные группы.
draw_list = columns_data

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

# Поиск семейства шпильки (Shape 62)
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


spacing_ft = 200 * 0.0328084
# Ширина листа (см) переводится в модельные см через масштаб вида,
# затем в футы. Раньше коэффициент 25 был зашит в код.
try:
    _sc = drafting_view.Scale
    view_scale = _sc if _sc else 25
except Exception:
    view_scale = 25
MAX_ROW_WIDTH_CM = width_cm * view_scale
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
            raise ValueError("Element has no LocationPoint. Provide base_point explicitly.")

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

    # --- Ищем/создаём тип текста один раз (а не на каждой колонне) ---
    text_type = None
    for ttype in FilteredElementCollector(doc).OfClass(TextNoteType):
        name_param = ttype.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        type_name = name_param.AsString() if name_param else None
        if type_name == TEXT_NOTE_TYPE_NAME:
            text_type = ttype.Id
            break
    if not text_type:
        text_type = create_TextType(doc,
                                    TEXT_NOTE_TYPE_NAME,
                                    size_mm=3.5,
                                    font="TN_CalibriL_Structural",
                                    width_factor=1)

    # --- Ищем семейство номеров марок один раз ---
    column_number_symbol = None
    for symbol in FilteredElementCollector(doc).OfClass(FamilySymbol):
        if symbol.FamilyName == COLUMN_NUMBER_FAMILY_NAME:
            column_number_symbol = symbol
            break
    if column_number_symbol is not None and not column_number_symbol.IsActive:
        column_number_symbol.Activate()

    stirrups_to_place = []
    for col_data in draw_list:
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
            # (text_type найден/создан один раз до цикла)
            b_int = int(round(width * 30.48))  # футы -> см
            h_int = int(round(height * 30.48))  # футы -> см
            hebrew_text = u"עמוד {}/{}".format(b_int, h_int)
            text_location = location_point + XYZ(0, -1.2, 0)
            text_note = TextNote.Create(doc, drafting_view.Id, text_location,
                                        hebrew_text, text_type)
            # Размещаем семейства с номерами марок (PR_Column Number)
            # (column_number_symbol найден/активирован один раз до цикла)
            if column_number_symbol is not None:
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
                        # Фиксированный шаг между рядами (раньше домножался на row,
                        # из-за чего ряды расползались всё дальше друг от друга).
                        cur_y = cur_y - 21 * 0.0328084
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
            # Параметры могут отсутствовать в старых версиях семейства — считаем 0.
            hasHorizontalSpacer_param = inst.LookupParameter("HasHorizontalSpacer")
            hasHorizontalSpacer = hasHorizontalSpacer_param.AsInteger() if hasHorizontalSpacer_param else 0

            hasVerticalSpacer_param = inst.LookupParameter("HasVerticalSpacer")
            hasVerticalSpacer = hasVerticalSpacer_param.AsInteger() if hasVerticalSpacer_param else 0
            stirrups_to_place.append({
                "location_point": location_point,
                "width": width,
                "height": height,
                "hasVerticalSpacer":hasVerticalSpacer,
                "hasHorizontalSpacer":hasHorizontalSpacer
            })

            current_row_width += width + spacing_ft

    # После расстановки всех колонн и аннотаций — расставляем хомуты

    # Собираем созданные хомуты/шпильки, чтобы в самом конце (последним действием)
    # ещё раз проставить их поперечные диаметры — на случай, если семейство при
    # регенерации/других правках сбрасывает Rebar_Diameter к дефолту.
    created_stirrups = []
    created_staples = []

    for stirrup_info in stirrups_to_place:
        loc = stirrup_info["location_point"]
        width = stirrup_info["width"]
        height = stirrup_info["height"]
        hasVerticalSpacer = stirrup_info["hasVerticalSpacer"]
        hasHorizontalSpacer = stirrup_info["hasHorizontalSpacer"]
        # Хомут ставим правее колонны на половину её ширины от правого края
        # (центр хомута = правый край + width/2).
        center_x = loc.X+width/2
        center_y = loc.Y + height / 2
        stirrup_x = center_x + width
        stirrup_location = XYZ(stirrup_x, center_y, 0)
        stirrup_instance = doc.Create.NewFamilyInstance(stirrup_location, stirrup_symbol, drafting_view)
        created_stirrups.append(stirrup_instance)

        # width/height — во внутренних единицах Revit (футы). Переводим в мм
        # и вычитаем защитный слой с двух сторон.
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
            p_rebar_number.Set(mm_to_ft(stirrup_dia_mm))   # диаметр хомута (Shape 52)
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
        # ВТОРАЯ ФОРМА: ШПИЛЬКА (Shape 62)
        # ============================

        if hasVerticalSpacer==1:

            staple_x = stirrup_location.X + mm_to_ft(SECOND_REBAR_OFFSET_MM)+mm_to_ft(stirrup_a/2)  # правее хомута
            staple_y = stirrup_location.Y
            staple_pt = XYZ(staple_x, staple_y, 0)

            staple_instance = doc.Create.NewFamilyInstance(staple_pt, staple_symbol, drafting_view)
            created_staples.append(staple_instance)

            # Размеры шпильки: по высоте H - 50 мм, по ширине B - 50 мм (как у хомута)
            # width/height тут в футах; переводим в мм → вычитаем 50 → обратно в футы

            staple_b_mm = max(0.0, ft_to_mm(height) - (2*cover_cm)*10)  # высота по Y

            pA_s = staple_instance.LookupParameter(PARAM_REBAR_B)

            if pA_s: pA_s.Set(mm_to_ft(staple_b_mm))


            p_diam_s = staple_instance.LookupParameter("Rebar_Diameter")
            if p_diam_s: p_diam_s.Set(mm_to_ft(staple_dia_mm))   # диаметр шпильки (Shape 62)
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
            created_staples.append(staple_instance)

            # --- параметры шпильки ---
            staple_b_mm = max(0.0, ft_to_mm(width) - (2*cover_cm)*10)  # высота по Y
            pA_s = staple_instance.LookupParameter(PARAM_REBAR_B)
            if pA_s:
                pA_s.Set(mm_to_ft(staple_b_mm))

            p_diam_s = staple_instance.LookupParameter("Rebar_Diameter")
            if p_diam_s: p_diam_s.Set(mm_to_ft(staple_dia_mm))   # диаметр шпильки (Shape 62)
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

    # --- ФИНАЛЬНЫЙ проход: проставляем поперечные диаметры ПОСЛЕДНИМ действием ---
    # (после всех правок/регенераций/тегов), чтобы значение из окна точно осталось,
    # а не откатилось к дефолту семейства.
    doc.Regenerate()

    def _set_dia(inst, dia_mm):
        try:
            p = inst.LookupParameter("Rebar_Diameter")
            if p and not p.IsReadOnly:
                p.Set(mm_to_ft(dia_mm))
        except Exception as e:
            print("Diameter set error: {}".format(e))

    for si in created_stirrups:
        _set_dia(si, stirrup_dia_mm)   # хомут Shape 52
    for si in created_staples:
        _set_dia(si, staple_dia_mm)    # шпилька Shape 62

    t.Commit()

with Transaction(doc, "Numeration") as t:
    t.Start()
    process_drafting_view(doc, drafting_view)
    t.Commit()

# =========================================================
# ОТЧЁТ по проблемным колоннам (не вычерчены)
# =========================================================
output = script.get_output()

if no_mark_errors or param_errors:
    output.print_md("# Problem columns report (level: {})".format(selected_level))
    output.print_md("These columns were **not drawn**. "
                    "Click a link in the table to jump to the element in the model.")

    # Table 1 - columns without a mark
    if no_mark_errors:
        output.print_md("## Columns without a mark - {} pcs.".format(len(no_mark_errors)))
        table1 = []
        for i, eid in enumerate(no_mark_errors, 1):
            table1.append([i, output.linkify(eid, title="Go to element")])
        output.print_table(table1, columns=["#", "Element"])

    # Table 2 - columns with missing reinforcement data
    if param_errors:
        output.print_md("## Columns with missing reinforcement - {} pcs.".format(len(param_errors)))
        table2 = []
        for i, err in enumerate(param_errors, 1):
            table2.append([
                i,
                err["mark"],
                output.linkify(err["id"], title="Go to element"),
                err["missing"],
            ])
        output.print_table(table2, columns=["#", "Mark", "Element", "Missing"])

# Summary message
placed_groups = len(draw_list)
if placed_groups == 0:
    forms.alert("No columns were drawn: all groups are missing reinforcement or "
                "diameter (or have no mark). See the report in the output window.")
elif no_mark_errors or param_errors:
    forms.alert("Done. Groups drawn: {}. "
                "Some columns have problems - see the report in the output window.".format(placed_groups))
else:
    forms.alert("Done. Groups drawn: {}.".format(placed_groups))
