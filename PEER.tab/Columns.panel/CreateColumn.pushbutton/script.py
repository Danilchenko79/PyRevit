# -*- coding: utf-8 -*-
__title__ = "Create Column"
__author__ = "Dmitry D"
# Окно немодальное (modeless): держим движок и scope живыми после завершения
# скрипта, иначе pyRevit чистит глобали и обработчики окна перестают работать
# (уровень не выбирается, кнопки молчат).
__persistentengine__ = True

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
    ElementTransformUtils, SubTransaction, ElementId,
    IFailuresPreprocessor, FailureSeverity, FailureProcessingResult
)
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent
from System.Collections.Generic import List
from System import Uri, Guid
from System.Windows.Media.Imaging import (BitmapImage, BitmapCacheOption,
                                          BitmapCreateOptions)
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
# Габариты сечения в 2D-семействах: пишем в первый НАЙДЕННЫЙ параметр.
# Порядок поиска: GUID общего параметра → имена-кандидаты (новое → старые).
# В чужих проектах может сидеть старая версия семейства, где общий параметр
# закрепился под ДРУГИМ именем (в т.ч. русским) — имя едет внутри .rfa,
# но GUID общего параметра вечный, поэтому матчим сначала по нему.
PARAM_B_CANDIDATES = ("PR_Dimension_Width", "B")
PARAM_H_CANDIDATES = ("PR_Dimension_Height", "H")

# GUID-ы общих параметров — сняты с эталонных .rfa (2026-09-01), во всех
# трёх 2D-семействах одинаковые; те же общие параметры сидят и в 3D-колоннах.
# Cover — семейный параметр (GUID нет), ищется только по имени.
SHARED_GUIDS = {
    "width":  "8f2e4f93-9472-4941-a65d-0ac468fd6a5d",   # PR_Dimension_Width
    "height": "da753fe3-ecfa-465b-9a2c-02f55d0c2ff1",   # PR_Dimension_Height
    "qty_x":  "de7637e2-5111-4f6b-ba9d-b8394ea5d7c3",   # Rebar_QuantityX
    "qty_y":  "79cc3e37-3043-4df5-8f0d-fc304127fc48",   # Rebar_QuantityY
    "dia":    "5498ba20-78b8-42d5-a4bf-f4ba6f5c16dd",   # Rebar_Diameter
}


def _guid_param(el, guid_key):
    """Параметр общего параметра по GUID, или None."""
    g = SHARED_GUIDS.get(guid_key)
    if el is None or not g:
        return None
    try:
        p = el.get_Parameter(Guid(g))
        return p
    except Exception:
        return None


def lookup_param(el, names, guid_key=None, writable=False):
    """Параметр: сначала по GUID общего параметра (надёжно при любых
    именах в чужих проектах), затем первый существующий из списка имён.

    writable=True — ищем параметр ДЛЯ ЗАПИСИ: read-only кандидаты
    пропускаются, поиск продолжается. Пример: в старом 2D-семействе общий
    ADSK_Размер_Ширина — формульный (read-only), а входной параметр —
    семейный B; без пропуска запись срезалась бы на защите IsReadOnly."""
    p = _guid_param(el, guid_key)
    if p is not None and not (writable and p.IsReadOnly):
        return p
    for n in names:
        p = el.LookupParameter(n)
        if p is not None and not (writable and p.IsReadOnly):
            return p
    return None
PARAM_MARK = "Mark"
PARAM_REBAR_QTY_X = "Rebar_QuantityX"
PARAM_REBAR_QTY_Y = "Rebar_QuantityY"
PARAM_LEVEL = "PR_Level"

# 🔹 Форма сечения — определяется по имени 3D-семейства колонны в модели
#    (PEER-Concrete-Column-Rectangular [Rounded [One Side]]).
#    RECT — прямоугольная/квадратная; ROUND2 — полукруг с двух сторон;
#    ROUND1 — полукруг с одной стороны. Коды завязаны на DataTrigger'ы
#    эскизов в CreateColumnForm.xaml — не переименовывать.
SHAPE_RECT = "RECT"
SHAPE_ROUND2 = "ROUND2"
SHAPE_ROUND1 = "ROUND1"
SHAPE_ORDER = {SHAPE_RECT: 0, SHAPE_ROUND2: 1, SHAPE_ROUND1: 2}
SHAPE_LABELS = {
    SHAPE_RECT: "Rectangular",
    SHAPE_ROUND2: "Rounded both sides",
    SHAPE_ROUND1: "Rounded one side",
}

# 2D-семейства для отрисовки на Drafting View по формам сечения.
# Если семейства нет в проекте — такие группы не чертятся и попадают в отчёт
# (таблица, группировка и write-back параметров работают в любом случае).
SHAPE_2D_FAMILY = {
    SHAPE_RECT: FAMILY_NAME,
    SHAPE_ROUND2: "Create Column-Rectangular Rounded",
    SHAPE_ROUND1: "Create Column-Rectangular Rounded One Side",
}


def column_shape(ctype):
    """Код формы сечения (SHAPE_*) по имени семейства типа колонны.
    Разделители -,_ приводятся к пробелам: 'Rectangular-Rounded' и
    'Rectangular Rounded' — одна и та же форма."""
    name = ""
    try:
        name = ctype.FamilyName or ""
    except Exception:
        pass
    n = name.lower().replace("-", " ").replace("_", " ")
    if "rounded" in n:
        return SHAPE_ROUND1 if "one side" in n else SHAPE_ROUND2
    return SHAPE_RECT


class _SilentWarningsPreprocessor(IFailuresPreprocessor):
    """Гасит жёлтые предупреждения Revit во время транзакций скрипта
    (промежуточные состояния: удаление зависимых аннотаций при очистке вида,
    временно не выполненные ограничения семейства и т.п. — Revit решает их
    сам, итог корректен). Настоящие ошибки НЕ трогаем — их покажет Revit."""

    def PreprocessFailures(self, failures_accessor):
        for f in failures_accessor.GetFailureMessages():
            try:
                if f.GetSeverity() == FailureSeverity.Warning:
                    failures_accessor.DeleteWarning(f)
            except Exception:
                pass
        return FailureProcessingResult.Continue


def _silence_warnings(t):
    """Подключает глушитель предупреждений к транзакции (до Commit)."""
    try:
        opts = t.GetFailureHandlingOptions()
        opts.SetFailuresPreprocessor(_SilentWarningsPreprocessor())
        t.SetFailureHandlingOptions(opts)
    except Exception:
        pass   # не критично: без глушителя просто покажется жёлтое окно

COLUMN_NUMBER_FAMILY_NAME = "PR_Column Number"
PARAM_NUMBER = "Num"  # первое значение
PARAM_NUMBER2 = "Num2"  # второе значение (для диапазона)
PARAM_NUMBER_PLUS = "Num+"  # булевый (True, если диапазон)

STIRRUP_FAMILY_NAME = "PEER_Rebar_Shape 52"
# Хомут для колонн со скруглением с ОДНОЙ стороны: та же роль, что Shape 52
# у прямоугольных; Rebar_A/B считаются по тем же правилам (габарит − 2 слоя).
STIRRUP60_FAMILY_NAME = "PEER_Rebar_Shape 60"
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


# Возможные имена параметров ширины/высоты сечения колонны у РАЗНЫХ семейств
# (LookupParameter чувствителен к регистру, поэтому перечисляем варианты).
# Проверяются по порядку; берётся первая пара, где заданы И ширина, И высота.
SECTION_SIZE_PAIRS = [
    ("PR_Dimension_Width", "PR_Dimension_Height"),   # текущие семейства PEER
    ("B", "H"),
    ("b", "h"),
    ("Width", "Depth"),
    ("Width", "Height"),
    ("Column_B", "Column_H"),
    ("PR_B", "PR_H"),
]


def _lookup_double(el, name):
    """Значение параметра-длины (Double) по имени, или None. Ищет и на экземпляре,
    и на типе — el передаём нужный."""
    if el is None:
        return None
    p = el.LookupParameter(name)
    if p is None:
        return None
    try:
        if str(p.StorageType) == "Double":
            return p.AsDouble()
    except Exception:
        pass
    return None


def _guid_double(col, ctype, guid_key):
    """Ненулевое значение общего параметра-длины по GUID (экземпляр, затем
    тип), или None."""
    for el in (col, ctype):
        p = _guid_param(el, guid_key)
        if p is not None:
            try:
                if str(p.StorageType) == "Double" and p.HasValue:
                    v = p.AsDouble()
                    if v:
                        return v
            except Exception:
                pass
    return None


def read_section_size(col, ctype):
    """Размеры сечения (ширина, высота) в футах. Сначала общие параметры по
    GUID (имена в чужих проектах могут быть любыми, в т.ч. русскими), затем
    набор имён B/H, b/h, Width/Depth... — на экземпляре и на типе.
    Если ничего не нашли — (0.0, 0.0)."""
    w = _guid_double(col, ctype, "width")
    h = _guid_double(col, ctype, "height")
    if w and h:
        return w, h
    for wn, hn in SECTION_SIZE_PAIRS:
        w = _lookup_double(col, wn)
        if w is None:
            w = _lookup_double(ctype, wn)
        h = _lookup_double(col, hn)
        if h is None:
            h = _lookup_double(ctype, hn)
        if w and h:   # обе величины найдены и ненулевые
            return w, h
    return 0.0, 0.0


# Специальный пункт в списке уровней: ревизия колонн без PR_Level.
NO_LEVEL_LABEL = "No Level"


def _top_level_name(col):
    """Имя верхнего уровня (Top Level) структурной колонны, или '(no top level)'."""
    try:
        p = col.get_Parameter(BuiltInParameter.FAMILY_TOP_LEVEL_PARAM)
        if p and p.HasValue:
            lvl = doc.GetElement(p.AsElementId())
            if lvl is not None:
                return lvl.Name
    except Exception:
        pass
    return "(no top level)"


def _has_valid_mark(col):
    mp = col.LookupParameter(PARAM_MARK)
    mark = mp.AsString() if mp and mp.HasValue else None
    return (mark if (mark and mark.strip() and mark != "N/A") else None)


def collect_no_mark(level):
    """Колонны выбранного уровня БЕЗ марки: [{id, size, top_level}]."""
    rows = []
    for col in all_columns:
        lp = col.LookupParameter(PARAM_LEVEL)
        if not (lp and lp.HasValue and lp.AsString() == level):
            continue
        if _has_valid_mark(col):
            continue
        ctype = doc.GetElement(col.GetTypeId())
        w, h = read_section_size(col, ctype)
        rows.append({
            "id": col.Id,
            "size": u"{} / {}".format(int(round(w * 30.48)), int(round(h * 30.48))),
            "top_level": _top_level_name(col),
        })
    return rows


def collect_duplicates(level):
    """Марки, встречающиеся на уровне больше одного раза:
    [(mark, [{id, size, top_level}, ...])], отсортировано по номеру марки."""
    by_mark = defaultdict(list)
    for col in all_columns:
        lp = col.LookupParameter(PARAM_LEVEL)
        if not (lp and lp.HasValue and lp.AsString() == level):
            continue
        mark = _has_valid_mark(col)
        if not mark:
            continue
        ctype = doc.GetElement(col.GetTypeId())
        w, h = read_section_size(col, ctype)
        by_mark[mark].append({
            "id": col.Id,
            "size": u"{} / {}".format(int(round(w * 30.48)), int(round(h * 30.48))),
            "top_level": _top_level_name(col),
        })
    dups = [(m, lst) for m, lst in by_mark.items() if len(lst) > 1]
    dups.sort(key=lambda kv: int(kv[0]) if kv[0].isdigit() else 9999)
    return dups


def collect_no_level():
    """Колонны БЕЗ PR_Level, сгруппированные по Top Level:
    [(top_level_name, [{id, mark, size}])], отсортировано по имени уровня."""
    by_top = defaultdict(list)
    for col in all_columns:
        lp = col.LookupParameter(PARAM_LEVEL)
        if lp and lp.HasValue and (lp.AsString() or "").strip():
            continue   # уровень задан — не наш случай
        ctype = doc.GetElement(col.GetTypeId())
        w, h = read_section_size(col, ctype)
        mark = _has_valid_mark(col)
        by_top[_top_level_name(col)].append({
            "id": col.Id,
            "mark": mark if mark else u"—",
            "size": u"{} / {}".format(int(round(w * 30.48)), int(round(h * 30.48))),
        })
    return sorted(by_top.items(), key=lambda kv: kv[0])


def compute_groups(level):
    """Группы колонн уровня по (B, H, Rebar X, Rebar Y, Ø).

    Возвращает (groups, no_mark_ids). Колонны без марки уходят в no_mark_ids и в
    таблицу не попадают. Диаметр/арматура могут быть 0 — пользователь заполнит их
    прямо в таблице.
    """
    grouped = defaultdict(lambda: {"marks": [], "col_ids": [],
                                   "width": 0.0, "height": 0.0,
                                   "qty_x": 0.0, "qty_y": 0.0, "diam": 0.0,
                                   "shape": SHAPE_RECT})
    no_mark_ids = []
    for col in all_columns:
        lp = col.LookupParameter(PARAM_LEVEL)
        if not (lp and lp.HasValue and lp.AsString() == level):
            continue
        mp = col.LookupParameter(PARAM_MARK)
        mark = mp.AsString() if mp and mp.HasValue else None
        ctype = doc.GetElement(col.GetTypeId())
        # Размеры сечения — устойчиво к разным именам параметров (B/H, b/h, ...).
        w, h = read_section_size(col, ctype)
        qxp = lookup_param(col, (PARAM_REBAR_QTY_X,), "qty_x")
        qyp = lookup_param(col, (PARAM_REBAR_QTY_Y,), "qty_y")
        qx = qxp.AsDouble() if qxp and qxp.HasValue else 0.0
        qy = qyp.AsDouble() if qyp and qyp.HasValue else 0.0
        dp = lookup_param(col, ("Rebar_Diameter",), "dia")
        d = dp.AsDouble() if dp and dp.HasValue else 0.0
        if not (mark and mark.strip() and mark != "N/A"):
            no_mark_ids.append(col.Id)
            continue
        shape = column_shape(ctype)
        key = (shape, round(w, 6), round(h, 6), qx, qy, d)
        g = grouped[key]
        g["marks"].append(mark)
        g["col_ids"].append(col.Id)
        g["width"] = w
        g["height"] = h
        g["qty_x"] = qx
        g["qty_y"] = qy
        g["diam"] = d
        g["shape"] = shape
    groups = list(grouped.values())
    # Сначала группируем по форме сечения, внутри формы — прежний порядок.
    groups.sort(key=lambda c: (SHAPE_ORDER.get(c["shape"], 99),
                               -c["width"] * c["height"],
                               -c["qty_x"] - c["qty_y"], -c["diam"]))
    return groups, no_mark_ids


from System.Windows import RoutedEventHandler
from System.Windows.Controls import ComboBoxItem, DataGridEditAction
from System.Windows.Controls.Primitives import ButtonBase
from System.Windows.Media import Brushes
from System.Windows import FontWeights


class HelpPopup(forms.WPFWindow):
    """Всплывающая справка (инструкция / легенда армирования). Чистый UI без
    Revit API, поэтому открывается напрямую, без ExternalEvent. Esc закрывает
    окно средствами pyRevit WPFWindow."""

    def on_close(self, sender, args):
        self.Close()


# Эскизы для окна легенды: имя Image-контрола в XAML -> файл в папке кнопки.
REBAR_HELP_IMAGES = (
    ("img_rect", "sketch_rect.png"),
    ("img_round2", "sketch_round2.png"),
    ("img_round1", "sketch_round1.png"),
)


def load_bitmap(path):
    """BitmapImage с чтением файла в память. Обязательно OnLoad +
    IgnoreImageCache: иначе WPF держит PNG заблокированным до конца сессии
    Revit и кэширует старую картинку после замены файла."""
    bi = BitmapImage()
    bi.BeginInit()
    bi.UriSource = Uri(path)
    bi.CacheOption = BitmapCacheOption.OnLoad
    bi.CreateOptions = BitmapCreateOptions.IgnoreImageCache
    bi.EndInit()
    return bi


class CreateColumnWindow(forms.WPFWindow):
    """Окно: выбор уровня + редактируемая таблица групп + таблица проблемных колонн."""

    def __init__(self, xaml_path, level_list):
        forms.WPFWindow.__init__(self, xaml_path)
        self.groups = []
        self.no_mark_ids = []
        self._dt = None
        self._dups = []            # [(mark, [{id, size, top_level}])] — дубли марок уровня
        self._dup_mark_set = set() # для подсветки в таблице групп
        self.dup_marks = []        # список марок-дублей — читает run_pipeline
        # Кнопки "Select" внутри dg_problems ловим через bubbling (надёжно в IPy).
        self.dg_problems.AddHandler(
            ButtonBase.ClickEvent, RoutedEventHandler(self.on_select_element))
        # Клики по маркам-ссылкам в dg_groups (разбиение группы) — тоже bubbling.
        self.dg_groups.AddHandler(
            ButtonBase.ClickEvent, RoutedEventHandler(self.on_split_group))
        self._bulk_edit = False   # защита от рекурсии в on_cell_edit_ending
        for lvl in level_list:
            self.cb_level.Items.Add(lvl)
        # Специальный пункт "No Level" — другим цветом (ревизия колонн без PR_Level).
        no_lvl = ComboBoxItem()
        no_lvl.Content = NO_LEVEL_LABEL
        no_lvl.Foreground = Brushes.OrangeRed
        no_lvl.FontWeight = FontWeights.SemiBold
        self.cb_level.Items.Add(no_lvl)
        if level_list:
            self.cb_level.SelectedIndex = 0   # триггерит on_level_changed → строит таблицу

    def selected_level_value(self):
        """Выбранный уровень как строка ('No Level' для спец-пункта)."""
        sel = self.cb_level.SelectedItem
        if isinstance(sel, ComboBoxItem):
            return str(sel.Content)
        return sel

    @staticmethod
    def _as_int(v):
        try:
            return int(round(float(v)))
        except Exception:
            return 0

    def _build_table(self, level):
        """Перестраивает таблицу групп под выбранный уровень."""
        self.groups, self.no_mark_ids = compute_groups(level)
        # Дубли марок уровня: подсветка в таблице групп + список внизу +
        # предупреждение перед отрисовкой.
        self._dups = collect_duplicates(level)
        self.dup_marks = [m for m, _ in self._dups]
        self._dup_mark_set = set(self.dup_marks)
        self._fill_table()

    def _fill_table(self):
        """Строит DataTable из self.groups (единицы модели: футы/штуки).

        Числовые поля — типизированные (Int32), поэтому в ячейки нельзя ввести
        не-число, а столбец Total (общее число стержней) считается формулой
        DataTable и обновляется сам при правке.
        Total по форме сечения (что значат X/Y — см. эскиз в первой колонке):
         - прямоугольная: X/Y — стержни с ОДНОЙ стороны без 4 угловых,
           итог = 4 угловых + 2*X + 2*Y;
         - скруглённые (обе): итог = 2*(X + Y), угловые входят в Qh.
        Если оба нуля — показываем 0.
        """
        dt = DataTable()
        dt.Columns.Add("RowIdx", System.Int32)    # индекс в self.groups (кнопка Split)
        dt.Columns.Add("Shape", System.String)    # код формы (RECT/ROUND2/ROUND1) — эскиз в XAML
        dt.Columns.Add("CanSplit", System.String) # "1" — группа из нескольких марок
        dt.Columns.Add("HasDup", System.String)   # "1" — есть марка-дубль (красная подсветка)
        dt.Columns.Add("Marks", System.String)
        dt.Columns.Add("Size", System.String)
        dt.Columns.Add("DiaMM", System.Int32)    # Rebar_Diameter, мм (редакт.)
        dt.Columns.Add("RebarX", System.Int32)   # Rebar Quantity_B (редакт.)
        dt.Columns.Add("RebarY", System.Int32)   # Rebar Quantity_H (редакт.)
        col_total = dt.Columns.Add("Total", System.Int32)
        col_total.Expression = ("IIF(RebarX = 0 AND RebarY = 0, 0, "
                                "IIF(Shape = 'RECT', "
                                "4 + 2*RebarX + 2*RebarY, "
                                "2*(RebarX + RebarY)))")
        for i, g in enumerate(self.groups):
            b = int(round(g["width"] * 30.48))    # футы → см
            h = int(round(g["height"] * 30.48))
            row = dt.NewRow()
            row["RowIdx"] = i
            row["Shape"] = g["shape"]
            row["CanSplit"] = "1" if len(g["marks"]) > 1 else "0"
            row["HasDup"] = ("1" if any(m in self._dup_mark_set for m in g["marks"])
                             else "0")
            row["Marks"] = ", ".join(sorted(g["marks"],
                                            key=lambda m: int(m) if m.isdigit() else 9999))
            row["Size"] = u"{} / {}".format(b, h)
            row["DiaMM"] = self._as_int(g["diam"] * 304.8)   # футы → мм
            row["RebarX"] = self._as_int(g["qty_x"])
            row["RebarY"] = self._as_int(g["qty_y"])
            dt.Rows.Add(row)
        self._dt = dt
        self.dg_groups.ItemsSource = dt.DefaultView

    @staticmethod
    def _new_problems_dt():
        dt = DataTable()
        for name in ("Mark", "Size", "TopLevel", "IdStr", "BtnVis"):
            dt.Columns.Add(name, System.String)
        return dt

    def _build_no_mark_table(self, level):
        """Нижняя таблица: колонны уровня без марки + колонны с маркой-дублем."""
        rows = collect_no_mark(level)
        # Синхронизируем с отчётом после OK.
        self.no_mark_ids = [r["id"] for r in rows]
        dt = self._new_problems_dt()
        for r in rows:
            row = dt.NewRow()
            row["Mark"] = u"—"
            row["Size"] = r["size"]
            row["TopLevel"] = r["top_level"]
            row["IdStr"] = str(r["id"])   # ElementId.ToString() = число
            row["BtnVis"] = "Visible"
            dt.Rows.Add(row)
        # Дубли: строка-заголовок по марке, под ней — каждая колонна с этой маркой.
        for mark, cols in self._dups:
            head = dt.NewRow()
            head["Mark"] = u"Duplicate mark '{}'  ({} pcs.)".format(mark, len(cols))
            head["Size"] = ""
            head["TopLevel"] = ""
            head["IdStr"] = ""
            head["BtnVis"] = "Collapsed"
            dt.Rows.Add(head)
            for c in cols:
                row = dt.NewRow()
                row["Mark"] = mark
                row["Size"] = c["size"]
                row["TopLevel"] = c["top_level"]
                row["IdStr"] = str(c["id"])
                row["BtnVis"] = "Visible"
                dt.Rows.Add(row)
        self.tb_problems_title.Text = \
            "Problem columns - no mark: {}, duplicate marks: {}".format(
                len(rows), len(self._dups))
        self.dg_problems.ItemsSource = dt.DefaultView

    def _build_no_level_table(self):
        """Режим 'No Level': колонны без PR_Level, сгруппированные по Top Level.
        Строка-заголовок 'Top Level: X', под ней — колонны этого уровня."""
        groups = collect_no_level()
        dt = self._new_problems_dt()
        total = 0
        for top_name, cols in groups:
            head = dt.NewRow()
            head["Mark"] = u"Top Level: {}  ({} pcs.)".format(top_name, len(cols))
            head["Size"] = ""
            head["TopLevel"] = ""
            head["IdStr"] = ""
            head["BtnVis"] = "Collapsed"   # у заголовка кнопки нет
            dt.Rows.Add(head)
            for c in cols:
                total += 1
                row = dt.NewRow()
                row["Mark"] = c["mark"]
                row["Size"] = c["size"]
                row["TopLevel"] = top_name
                row["IdStr"] = str(c["id"])   # ElementId.ToString() = число
                row["BtnVis"] = "Visible"
                dt.Rows.Add(row)
        self.tb_problems_title.Text = \
            "Columns without PR_Level (grouped by Top Level): {}".format(total)
        self.dg_problems.ItemsSource = dt.DefaultView

    def on_level_changed(self, sender, args):
        lvl = self.selected_level_value()
        if not lvl:
            return
        if lvl == NO_LEVEL_LABEL:
            # Режим ревизии: группы не строим и не чертим.
            self.groups = []
            self.no_mark_ids = []
            self._dups = []
            self._dup_mark_set = set()
            self.dup_marks = []
            self._dt = None
            self.dg_groups.ItemsSource = None
            self._build_no_level_table()
        else:
            self._build_table(lvl)
            self._build_no_mark_table(lvl)

    def on_select_element(self, sender, args):
        """Кнопка 'Select' в строке: выделить колонну в модели и зазумить на неё."""
        src = args.OriginalSource
        tag = getattr(src, "Tag", None)
        if not tag:
            return
        try:
            eid = ElementId(int(str(tag)))
        except Exception:
            return

        # Окно немодальное — Revit API доступен только через ExternalEvent.
        def _do_select():
            uidoc = revit.uidoc
            uidoc.Selection.SetElementIds(List[ElementId]([eid]))
            uidoc.ShowElements(eid)

        self.action_handler.action = _do_select
        self.action_event.Raise()

    # Столбцы, в которых работает массовая правка по выделению.
    BULK_EDIT_COLUMNS = ("DiaMM", "RebarX", "RebarY")

    def on_cell_edit_ending(self, sender, e):
        """Массовая правка: значение, введённое в ячейку, применяется ко всем
        ВЫДЕЛЕННЫМ ячейкам того же столбца (протяжка мышью / Ctrl / Shift).
        Свою ячейку коммитит сам DataGrid штатным биндингом."""
        if self._bulk_edit:
            return
        try:
            if e.EditAction != DataGridEditAction.Commit:
                return
            binding = getattr(e.Column, "Binding", None)
            path = binding.Path.Path if binding is not None else None
            if path not in self.BULK_EDIT_COLUMNS:
                return
            txt = getattr(e.EditingElement, "Text", None)
            if txt is None:
                return
            try:
                val = int(round(float(str(txt).replace(",", "."))))
            except Exception:
                return   # невалидный ввод — отработает штатная валидация
            edited_item = e.Row.Item
            self._bulk_edit = True
            try:
                for cell in self.dg_groups.SelectedCells:
                    if cell.Column is not e.Column:
                        continue   # выделение в другом столбце не трогаем
                    drv = cell.Item
                    if drv is edited_item:
                        continue
                    try:
                        drv.Row[path] = val
                    except Exception:
                        pass
            finally:
                self._bulk_edit = False
        except Exception:
            pass   # правка одной ячейки важнее массовой — молча пропускаем

    def on_split_group(self, sender, args):
        """Клик по подчёркнутым маркам: разбить группу на отдельные строки."""
        tag = getattr(args.OriginalSource, "Tag", None)
        if tag is None:
            return   # клик по другой кнопке внутри dg_groups
        try:
            idx = int(str(tag))
        except Exception:
            return
        # Зафиксировать текущую правку ячейки, чтобы не потерять её при rebuild.
        try:
            self.dg_groups.CommitEdit()
            self.dg_groups.CommitEdit()
        except Exception:
            pass
        self._split_group(idx)

    def _split_group(self, idx):
        """Разбивает группу idx по маркам; правки остальных строк сохраняются.
        Если после разбиения значения не менять, при OK одинаковые строки
        сольются обратно в одну группу (см. run_pipeline)."""
        edited = self.edited_groups()
        if not (0 <= idx < len(edited)) or len(edited[idx]["marks"]) < 2:
            return

        def _to_model(e, marks, col_ids):
            return {"marks": list(marks), "col_ids": list(col_ids),
                    "width": e["width"], "height": e["height"],
                    "shape": e["shape"],
                    "qty_x": float(e["qty_x"]), "qty_y": float(e["qty_y"]),
                    "diam": e["dia_mm"] / 304.8}   # мм → футы

        new_groups = []
        for i, e in enumerate(edited):
            if i != idx:
                new_groups.append(_to_model(e, e["marks"], e["col_ids"]))
                continue
            pairs = sorted(zip(e["marks"], e["col_ids"]),
                           key=lambda p: int(p[0]) if p[0].isdigit() else 9999)
            for mk, cid in pairs:
                new_groups.append(_to_model(e, [mk], [cid]))
        self.groups = new_groups
        self._fill_table()

    def on_help_instructions(self, sender, args):
        """Иконка 'i': инструкция по работе с окном."""
        HelpPopup(script.get_bundle_file("CreateColumnInstructions.xaml")).ShowDialog()

    def on_help_rebar(self, sender, args):
        """Иконка '?': легенда армирования — какая арматура за какой параметр."""
        w = HelpPopup(script.get_bundle_file("CreateColumnRebarHelp.xaml"))
        for ctrl_name, file_name in REBAR_HELP_IMAGES:
            path = script.get_bundle_file(file_name)
            img = getattr(w, ctrl_name, None)
            if path and img is not None:
                try:
                    img.Source = load_bitmap(path)
                except Exception:
                    pass   # нет картинки — окно откроется без неё
        w.ShowDialog()

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
                "shape": g["shape"],
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
        lvl = self.selected_level_value()
        if not lvl:
            forms.alert("Select a level (PR_Level).", title="Create Column")
            return
        if lvl == NO_LEVEL_LABEL:
            forms.alert("'No Level' is a review mode - nothing is drawn.\n"
                        "Fix PR_Level on these columns, then pick a real level.",
                        title="Create Column")
            return
        # Окно немодальное: DialogResult недоступен. Генерацию выполняем через
        # ExternalEvent (валидный API-контекст), окно закрываем сразу.
        self.action_handler.action = run_pipeline
        self.action_event.Raise()
        self.Close()

    def on_cancel(self, sender, args):
        self.Close()


def run_pipeline():
    """Полный пайплайн: чтение окна -> write-back -> вид -> чертёж -> отчёт.

    Окно немодальное, поэтому вызывается через ExternalEvent (валидный
    API-контекст Revit). Все forms.alert(...) внутри завершают шаг через return."""
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
    selected_level = _win.selected_level_value()
    no_mark_errors = list(_win.no_mark_ids)
    dup_marks = list(getattr(_win, "dup_marks", []))

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
            "shape": g.get("shape", SHAPE_RECT),
            "rebar_qty_x": g["qty_x"],
            "rebar_qty_y": g["qty_y"],
            "rebar_diam": g["dia_mm"] / 304.8,   # мм → футы
            "col_ids": g["col_ids"],
        })
    # После ручного разбиения группы (Split в таблице) могли остаться строки
    # с одинаковыми значениями — сливаем их обратно, как сделала бы
    # перегруппировка при следующем запуске.
    merged = {}
    merged_order = []
    for g in columns_data:
        key = (g["shape"], round(g["width"], 6), round(g["height"], 6),
               g["rebar_qty_x"], g["rebar_qty_y"], round(g["rebar_diam"], 9))
        if key in merged:
            merged[key]["marks"].extend(g["marks"])
            merged[key]["col_ids"].extend(g["col_ids"])
        else:
            merged[key] = g
            merged_order.append(key)
    columns_data = [merged[k] for k in merged_order]

    # Порядок отрисовки — как в таблице: по форме, внутри формы по размеру.
    columns_data.sort(key=lambda c: (SHAPE_ORDER.get(c["shape"], 99),
                                     -c["width"] * c["height"],
                                     -c["rebar_qty_x"] - c["rebar_qty_y"], -c["rebar_diam"]))

    # Дубли марок на уровне — предупреждаем ДО любых изменений модели.
    if dup_marks:
        if not forms.alert(
                "Duplicate marks on this level: {}.\n\n"
                "Several columns share the same mark - they are highlighted red "
                "in the table and listed in the problem table below.\n"
                "Draw anyway? (Better: fix the numbering and rerun.)".format(
                    ", ".join(dup_marks)),
                title="Create Column", yes=True, no=True):
            return

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
                            "Choose another name.".format(name))
                return None
        dv_type_id = None
        for vft in FilteredElementCollector(doc).OfClass(ViewFamilyType):
            if vft.ViewFamily == ViewFamily.Drafting:
                dv_type_id = vft.Id
                break
        if dv_type_id is None:
            forms.alert("No Drafting View type found in the project.")
            return
        with Transaction(doc, "Create Drafting View") as t:
            t.Start()
            _silence_warnings(t)
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
            return

    # --- Запись отредактированных значений обратно в колонны модели ---
    with Transaction(doc, "Update Column Reinforcement") as t:
        t.Start()
        _silence_warnings(t)
        for g in columns_data:
            for cid in g.get("col_ids", []):
                model_col = doc.GetElement(cid)
                if model_col is None:
                    continue
                for pname, gkey, pval in (
                        (PARAM_REBAR_QTY_X, "qty_x", float(g["rebar_qty_x"])),
                        (PARAM_REBAR_QTY_Y, "qty_y", float(g["rebar_qty_y"])),
                        ("Rebar_Diameter", "dia", g["rebar_diam"])):
                    p = lookup_param(model_col, (pname,), gkey, writable=True)
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
            _silence_warnings(t)
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
        forms.alert("Could not create Drafting View '{}'. Script stopped.".format(view_name))
        return

    # Режим Update убран — всегда чертим все валидные группы.
    draw_list = columns_data

    # 2D-семейства по формам сечения (SHAPE_2D_FAMILY). Прямоугольное обязательно;
    # скруглённые — если найдены. Группы форм без семейства пропускаем при
    # отрисовке и показываем в отчёте (write-back в модель уже выполнен).
    shape_symbols = {}
    for symbol in FilteredElementCollector(doc).OfClass(FamilySymbol):
        for shp, fam_name in SHAPE_2D_FAMILY.items():
            if shp not in shape_symbols and symbol.FamilyName == fam_name:
                shape_symbols[shp] = symbol
    if SHAPE_RECT not in shape_symbols:
        forms.alert("Family '{}' not found.".format(FAMILY_NAME))
        return
    shape_skipped = []   # группы, для чьей формы нет 2D-семейства в проекте

    # Поиск семейства хомута
    stirrup_symbol = None
    for symbol in FilteredElementCollector(doc).OfClass(FamilySymbol):
        if symbol.FamilyName == STIRRUP_FAMILY_NAME:
            stirrup_symbol = symbol
            break
    if stirrup_symbol is None:
        forms.alert("Family '{}' not found.".format(STIRRUP_FAMILY_NAME))
        return

    # Поиск семейства шпильки (Shape 62)
    staple_symbol = None
    for symbol in FilteredElementCollector(doc).OfClass(FamilySymbol):
        if symbol.FamilyName in STAPLE_FAMILY_NAME_CANDIDATES:
            staple_symbol = symbol
            break
    if staple_symbol is None:
        forms.alert("Family '{}' not found.".format(" / ".join(STAPLE_FAMILY_NAME_CANDIDATES)))
        return

    # Хомут Shape 60 (для колонн со скруглением с одной стороны). Обязателен
    # только если такие группы вообще чертим.
    stirrup60_symbol = None
    for symbol in FilteredElementCollector(doc).OfClass(FamilySymbol):
        if symbol.FamilyName == STIRRUP60_FAMILY_NAME:
            stirrup60_symbol = symbol
            break
    if stirrup60_symbol is None and any(
            c.get("shape") == SHAPE_ROUND1 for c in draw_list):
        forms.alert("Family '{}' not found.".format(STIRRUP60_FAMILY_NAME))
        return

    # Поиск типа тэга для хомутов
    stirrup_tag_type = None
    for tag_type in FilteredElementCollector(doc).OfClass(FamilySymbol).OfCategory(BuiltInCategory.OST_DetailComponentTags):
        name_param = tag_type.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        tag_type_name = name_param.AsString() if name_param else None
        if tag_type.FamilyName == STIRRUP_TAG_FAMILY_NAME and tag_type_name == STIRRUP_TAG_TYPE_NAME:
            stirrup_tag_type = tag_type
            break

    if stirrup_tag_type is None:
        forms.alert("Tag type '{}' in family '{}' not found.".format(STIRRUP_TAG_TYPE_NAME, STIRRUP_TAG_FAMILY_NAME))
        return


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


    def staple_count(q, spacing_ft, shape):
        """Количество шпилек этого типа на сечении колонны.

        Правила (от юзера, 2026-08): шаг стержней по стороне > 150 мм →
        количество = Q (Rebar_Quantity стороны); иначе шпилька через стержень:
        roundup(Q/2) − 1. Для обеих скруглённых форм вместо Q подставляется
        Q − 2 (угловые/касательные стержни шпилек не получают).
        0 или меньше — шпилька не ставится вовсе."""
        q = int(q)
        if shape in (SHAPE_ROUND1, SHAPE_ROUND2):
            q -= 2
        if q <= 0:
            return 0
        spacing_mm = ft_to_mm(spacing_ft) if spacing_ft else 9999.0
        if spacing_mm > 150.0:
            return q
        return int(math.ceil(q / 2.0)) - 1


    def set_staple_qty(inst, qty):
        """Количество шпилек этого типа на сечении колонны — в параметры
        шпильки: Rebar_Quantity Text (строка, её читает тэг) и Rebar_Quantity."""
        p = inst.LookupParameter("Rebar_Quantity Text")
        if p and not p.IsReadOnly:
            try:
                p.Set(str(int(qty)))
            except Exception:
                pass
        p = inst.LookupParameter("Rebar_Quantity")
        if p and not p.IsReadOnly:
            try:
                if str(p.StorageType) == "Integer":
                    p.Set(int(qty))
                else:
                    p.Set(float(qty))
            except Exception:
                pass


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
        _silence_warnings(t)
        for sym in shape_symbols.values():
            if not sym.IsActive:
                sym.Activate()
        if not stirrup_symbol.IsActive:
            stirrup_symbol.Activate()
        if stirrup60_symbol is not None and not stirrup60_symbol.IsActive:
            stirrup60_symbol.Activate()
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
            shape = col_data.get("shape", SHAPE_RECT)
            fam_symbol = shape_symbols.get(shape)
            if fam_symbol is None:
                # Для этой формы нет 2D-семейства в проекте — в отчёт и дальше.
                shape_skipped.append(col_data)
                continue
            if width > 0 and height > 0:
                if current_row_width + width > max_row_width_ft:
                    current_row_width = 0
                    current_row_y -= (height + spacing_ft)
                location_point = XYZ(current_row_width, current_row_y, 0)
                instance = doc.Create.NewFamilyInstance(location_point, fam_symbol, drafting_view,)
                eid = instance.Id
                # Устанавливаем B и H
                p_b = lookup_param(instance, PARAM_B_CANDIDATES, "width",
                                   writable=True)
                if p_b:
                    p_b.Set(width)

                p_h = lookup_param(instance, PARAM_H_CANDIDATES, "height",
                                   writable=True)
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
                p_rebar_qty_x = lookup_param(instance, (PARAM_REBAR_QTY_X,), "qty_x",
                                             writable=True)
                if p_rebar_qty_x:
                    try:
                        p_rebar_qty_x.Set(col_data["rebar_qty_x"])
                    except Exception as e:
                        print("Error setting {}: {}".format(PARAM_REBAR_QTY_X, e))

                p_rebar_qty_y = lookup_param(instance, (PARAM_REBAR_QTY_Y,), "qty_y",
                                             writable=True)
                if p_rebar_qty_y:
                    try:
                        p_rebar_qty_y.Set(col_data["rebar_qty_y"])
                    except Exception as e:
                        print("Error setting {}: {}".format(PARAM_REBAR_QTY_Y, e))
                # Устанавливаем Rebar_Diameter
                p_rebar_diam = lookup_param(instance, ("Rebar_Diameter",), "dia",
                                            writable=True)
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

                # Шаг стержней по сторонам — из формул семейства (после
                # Regenerate), для правила 150 мм в количестве шпилек.
                sx_p = inst.LookupParameter("Rebar_SpacingX")
                spacing_x = sx_p.AsDouble() if sx_p and sx_p.HasValue else None
                sy_p = inst.LookupParameter("Rebar_SpacingY")
                spacing_y = sy_p.AsDouble() if sy_p and sy_p.HasValue else None
                # Армирование сбоку: хомут — Shape 52 (RECT) / Shape 60 (ROUND1),
                # у «стадиона» (ROUND2) хомут пока не определён — только шпильки.
                # Шпильки Shape 62 — для всех форм по одним правилам.
                if shape in (SHAPE_RECT, SHAPE_ROUND1, SHAPE_ROUND2):
                    stirrups_to_place.append({
                        "location_point": location_point,
                        "width": width,
                        "height": height,
                        "shape": shape,
                        # Для количества шпилек на сечении (в тэг шпильки):
                        # вертикальных — от QuantityX, горизонтальных — от QuantityY.
                        "qty_x": col_data["rebar_qty_x"],
                        "qty_y": col_data["rebar_qty_y"],
                        "spacing_x": spacing_x,
                        "spacing_y": spacing_y,
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
            info_shape = stirrup_info.get("shape")
            # Хомут ставим правее колонны на половину её ширины от правого края
            # (центр хомута = правый край + width/2).
            center_x = loc.X+width/2
            center_y = loc.Y + height / 2
            stirrup_x = center_x + width
            stirrup_location = XYZ(stirrup_x, center_y, 0)

            # width/height — во внутренних единицах Revit (футы). Переводим в мм
            # и вычитаем защитный слой с двух сторон. Нужны и шпилькам ниже,
            # поэтому считаем до создания хомута.
            stirrup_a = width * 304.8 - (2*cover_cm)*10
            stirrup_b = height * 304.8 - (2*cover_cm)*10

            # Хомут: RECT — Shape 52, ROUND1 — Shape 60. У «стадиона» (ROUND2)
            # хомут пока не определён — ставим только шпильки.
            has_stirrup = info_shape != SHAPE_ROUND2
            if has_stirrup:
                cur_stirrup_symbol = (stirrup60_symbol
                                      if info_shape == SHAPE_ROUND1
                                      else stirrup_symbol)
                stirrup_instance = doc.Create.NewFamilyInstance(stirrup_location, cur_stirrup_symbol, drafting_view)
                created_stirrups.append(stirrup_instance)
                p_stirrup_a = stirrup_instance.LookupParameter(PARAM_REBAR_A)
                p_stirrup_b = stirrup_instance.LookupParameter(PARAM_REBAR_B)
                if p_stirrup_a:
                    p_stirrup_a.Set(mm_to_ft(stirrup_a))
                if p_stirrup_b:
                    p_stirrup_b.Set(mm_to_ft(stirrup_b))
                p_rebar_number = stirrup_instance.LookupParameter("Rebar_Diameter")
                if p_rebar_number:
                    p_rebar_number.Set(mm_to_ft(stirrup_dia_mm))   # диаметр хомута
                p_rebar_spacing = stirrup_instance.LookupParameter("Rebar_Spacing")
                if p_rebar_spacing:
                    p_rebar_spacing.Set(mm_to_ft(200))

            # --- ТЭГ под хомутом (координаты tag_x/tag_y нужны и шпилькам) ---
            # stirrup_b — высота хомута в мм.
            # У Shape 60 внизу дуга с размером радиуса — тэг опускаем ниже,
            # чтобы не перекрывал этот размер.
            tag_extra_down = 300 if info_shape == SHAPE_ROUND1 else 0
            stirrup_b_ft = mm_to_ft(stirrup_b + 350 + tag_extra_down)  # в футах
            Space_x=mm_to_ft(300)
            tag_y = stirrup_location.Y - stirrup_b_ft / 2  # низ хомута = верх тэга
            tag_x = stirrup_location.X + Space_x  # низ хомута = верх тэга
            tag_location = XYZ(tag_x, tag_y, 0)
            if has_stirrup:
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

            # Количество шпилек на сечении — по правилу 150 мм (см. staple_count).
            staple_qty_v = staple_count(stirrup_info.get("qty_x", 0),
                                        stirrup_info.get("spacing_x"),
                                        stirrup_info.get("shape"))
            if hasVerticalSpacer == 1 and staple_qty_v > 0:

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
                set_staple_qty(staple_instance, staple_qty_v)

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

            staple_qty_h = staple_count(stirrup_info.get("qty_y", 0),
                                        stirrup_info.get("spacing_y"),
                                        stirrup_info.get("shape"))
            if hasHorizontalSpacer == 1 and staple_qty_h > 0:
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
                set_staple_qty(staple_instance, staple_qty_h)

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
        _silence_warnings(t)
        process_drafting_view(doc, drafting_view)
        t.Commit()

    # =========================================================
    # ОТЧЁТ по проблемным колоннам (не вычерчены)
    # =========================================================
    output = script.get_output()

    if no_mark_errors or param_errors or shape_skipped:
        output.print_md("# Problem columns report (level: {})".format(selected_level))
        output.print_md("These columns were **not drawn**. "
                        "Click a link in the table to jump to the element in the model.")

        # Table 0 - groups whose shape has no 2D detail family in the project
        if shape_skipped:
            output.print_md("## Groups without a 2D family for their shape - {} pcs.".format(
                len(shape_skipped)))
            table0 = []
            for i, g in enumerate(shape_skipped, 1):
                table0.append([
                    i,
                    ", ".join(g["marks"]),
                    SHAPE_LABELS.get(g["shape"], g["shape"]),
                    SHAPE_2D_FAMILY.get(g["shape"], "?"),
                ])
            output.print_table(table0,
                               columns=["#", "Marks", "Shape", "Expected 2D family"])
            output.print_md("Load the listed 2D families into the project "
                            "(or fix SHAPE_2D_FAMILY names in the script) and rerun.")

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
    placed_groups = len(draw_list) - len(shape_skipped)
    if placed_groups == 0:
        forms.alert("No columns were drawn: all groups are missing reinforcement, "
                    "diameter, mark or a 2D family for their shape. "
                    "See the report in the output window.")
    elif no_mark_errors or param_errors or shape_skipped:
        forms.alert("Done. Groups drawn: {}. "
                    "Some columns have problems - see the report in the output window.".format(placed_groups))
    else:
        forms.alert("Done. Groups drawn: {}.".format(placed_groups))


# ============================================================
# MODELESS ЗАПУСК: окно не блокирует Revit — можно вращать 3D,
# пока оно открыто. Обращения к API (Select, генерация по OK)
# идут через ExternalEvent — иначе из немодального окна Revit
# API недоступен.
# ============================================================
class _ActionEventHandler(IExternalEventHandler):
    """Выполняет отложенное действие в валидном API-контексте Revit."""

    def __init__(self, name):
        self.name = name
        self.action = None

    def Execute(self, uiapp):
        act = self.action
        self.action = None
        if act is None:
            return
        try:
            act()
        except Exception as ex:
            try:
                forms.alert("Create Column error:\n{}".format(ex),
                            title="Create Column")
            except Exception:
                pass

    def GetName(self):
        return self.name


_action_handler = _ActionEventHandler("PEER Create Column")
_action_event = ExternalEvent.Create(_action_handler)

_win = CreateColumnWindow(script.get_bundle_file("CreateColumnForm.xaml"), levels)
_win.action_handler = _action_handler
_win.action_event = _action_event
_win.Show()   # немодально: скрипт завершается, окно и обработчики живут дальше

