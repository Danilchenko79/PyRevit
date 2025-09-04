# -*- coding: utf-8 -*-
__title__ = "Rebar Tag Select"
__doc__ = """Version = 5.3
Date = 24.08.2025
Author: adapted from Erik Frits; edits by Dima D + ChatGPT

Что нового (v5.3):
- Мультивыбор целевых элементов: можно выбрать 1..N Detail Items на активном виде.
- Предфильтр выбора: выбираются только аннотационные элементы категории Detail Items.
- Логика поиска и чтения исходных параметров осталась как в v5.2 (поиск нужного Rebar на текущем листе).
"""

from pyrevit import revit, DB, forms, script
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter

# -----------------------------------------------------
# КОНСТАНТЫ / НАСТРОЙКИ
# -----------------------------------------------------
FAMILY_PREFIX = "PEER_Rebar_Shape"   # отфильтровываем только эти семейства-источники
PARAM_MAP_SOURCE = [                   # что читаем из найденной Rebar-детали
    'Rebar_Number',
    'Rebar_Diameter',
    'Rebar_Length',
    'Rebar_Quantity Text',
    'Rebar_Spacing',
]
PARAM_MAP_TARGET = {                   # куда записываем на выбранных пользователем семействах
    'Rebar_Number': 'Rebar_Number',
    'Rebar_Diameter': 'Rebar_Diameter',
    'Rebar_Length': 'Rebar_Length',
    'Rebar_Quantity Text': 'Rebar_Quantity Text',
    'Rebar_Spacing': 'Rebar_Spacing',
    'PR_Rebar_ID': 'PR_Rebar_ID',      # служебное: Id найденного элемента-источника
}

# -----------------------------------------------------
# УТИЛИТЫ
# -----------------------------------------------------
doc = revit.doc
uidoc = revit.uidoc


def alert_and_exit(msg):
    forms.alert(msg)
    script.exit()


def normalize_number(text):
    """ Преобразовать строку в число (float) с поддержкой запятой/точки и
        с удалением пробелов и разделителей тысяч. Возвращает float.
    """
    if text is None:
        raise ValueError("Empty number text")
    try:
        unicode
    except NameError:
        # Py3 stub на случай окружений
        def unicode(x):
            return str(x)
    s = unicode(text)
    s = s.strip().replace(u' ', u' ')
    s = s.replace(' ', '')
    s = s.replace(',', '.')
    allowed = set('0123456789.-')
    s = ''.join(ch for ch in s if ch in allowed)
    if s.count('.') > 1:
        head, _sep, tail = s.partition('.')
        tail = tail.replace('.', '')
        s = head + '.' + tail
    return float(s)


def get_param_value_as_string(elem, param_name):
    p = elem.LookupParameter(param_name)
    if not p:
        return None
    st = p.StorageType
    if st == StorageType.Integer:
        val = p.AsInteger()
        return None if val is None else str(val)
    elif st == StorageType.Double:
        val = p.AsValueString()
        return None if not val else val
    else:
        val = p.AsString()
        return None if not val else val


def set_param_value(elem, param_name, value):
    p = elem.LookupParameter(param_name)
    if not p:
        return False

    def _clear_parameter(_p):
        if _p.StorageType == StorageType.Integer:
            _p.Set(0)
        elif _p.StorageType == StorageType.Double:
            _p.Set(0.0)
        else:
            _p.Set("")
        return True

    if value in [None, u"", u"(empty)", u"(not found)"]:
        return _clear_parameter(p)

    try:
        st = p.StorageType
        if st == StorageType.Integer:
            f = normalize_number(value)
            p.Set(int(round(f)))
        elif st == StorageType.Double:
            f = normalize_number(value)
            internal = UnitUtils.ConvertToInternalUnits(f, UnitTypeId.Millimeters)
            p.Set(internal)
        else:
            p.Set(str(value))
        return True
    except Exception as e:
        forms.alert(u"Ошибка записи параметра '{}': {}".format(param_name, e))
        return False


class DetailItemSelectionFilter(ISelectionFilter):
    def AllowElement(self, elem):
        try:
            return (isinstance(elem, FamilyInstance)
                    and elem.Category
                    and elem.Category.Id.IntegerValue == int(BuiltInCategory.OST_DetailComponents))
        except:
            return False
    def AllowReference(self, reference, point):
        return True


# -----------------------------------------------------
# 1) МУЛЬТИ-выбор целевых семейств (Detail Items) на активном виде
# -----------------------------------------------------
try:
    refs = uidoc.Selection.PickObjects(
        ObjectType.Element,
        DetailItemSelectionFilter(),
        "Select one or more Detail Items to update"
    )
    selected_elems = [doc.GetElement(r.ElementId) for r in refs]
except Exception as e:
    if "cancelled" in str(e).lower():
        alert_and_exit("Selection operation cancelled.")
    else:
        raise

if not selected_elems:
    alert_and_exit("No Detail Items selected.")

# На всякий случай фильтруем только DetailComponents
selected_elems = [fi for fi in selected_elems
                  if isinstance(fi, FamilyInstance)
                  and fi.Category
                  and fi.Category.Id.IntegerValue == int(BuiltInCategory.OST_DetailComponents)]

if not selected_elems:
    alert_and_exit("No valid Detail Items in the selection.")

# -----------------------------------------------------
# 2) Ввод номера арматуры
# -----------------------------------------------------
rebar_number_input = forms.ask_for_string(
    default='',
    prompt="Enter the rebar number to search for:",
    title="Rebar Search"
)

if not rebar_number_input:
    alert_and_exit("Rebar number not entered. Script stopped.")

rebar_number_key = rebar_number_input.strip()

# -----------------------------------------------------
# 3) Находим лист, где размещён активный вид
# -----------------------------------------------------
active_view = revit.active_view
sheet_id = None
for vp in FilteredElementCollector(doc).OfClass(Viewport):
    if vp.ViewId == active_view.Id:
        sheet_id = vp.SheetId
        break

if not sheet_id:
    alert_and_exit("The active view is not placed on any sheet.")

sheet = doc.GetElement(sheet_id)

# -----------------------------------------------------
# 4) Все виды на этом листе
# -----------------------------------------------------
placed_views = []
for vp_id in sheet.GetAllViewports():
    vp = doc.GetElement(vp_id)
    v = doc.GetElement(vp.ViewId)
    if isinstance(v, View) and not v.IsTemplate:
        placed_views.append(v)

if not placed_views:
    alert_and_exit("No views found on the current sheet.")

# -----------------------------------------------------
# 5) Поиск Detail Item с нужным номером (только семейства PEER_Rebar_Shape*)
# -----------------------------------------------------
found_items = []  # (FamilyInstance, View)
for v in placed_views:
    collector = (FilteredElementCollector(doc, v.Id)
                 .OfCategory(BuiltInCategory.OST_DetailComponents)
                 .WhereElementIsNotElementType())
    for fi in collector:
        if not isinstance(fi, FamilyInstance):
            continue
        fam_name = fi.Symbol.Family.Name if fi.Symbol and fi.Symbol.Family else ""
        if not fam_name.startswith(FAMILY_PREFIX):
            continue
        p = fi.LookupParameter('Rebar_Number')
        if not p:
            continue
        if p.StorageType == StorageType.Integer:
            val = str(p.AsInteger())
        elif p.StorageType == StorageType.Double:
            val = p.AsValueString() or ""
        else:
            val = p.AsString() or ""
        if val.strip() == rebar_number_key:
            found_items.append((fi, v))

if not found_items:
    alert_and_exit(u"Detail Item with number '{}' was not found on the sheet.".format(rebar_number_key))

# Если найдено несколько — предложим выбрать
if len(found_items) == 1:
    chosen = found_items[0][0]
else:
    options = []
    mapping = {}
    for fi, v in found_items:
        text = u"{} | View: {} | Id: {}".format(
            fi.Symbol.Family.Name if fi.Symbol and fi.Symbol.Family else u"<no family>",
            v.Name,
            fi.Id.IntegerValue
        )
        options.append(text)
        mapping[text] = fi
    picked = forms.SelectFromList.show(options, title=u"Choose matching rebar detail", multiselect=False)
    if not picked:
        alert_and_exit("Operation cancelled.")
    chosen = mapping[picked]

# -----------------------------------------------------
# 6) Читаем параметры с найденного элемента-источника
# -----------------------------------------------------
values = {name: (get_param_value_as_string(chosen, name) or u"") for name in PARAM_MAP_SOURCE}
values['PR_Rebar_ID'] = str(chosen.Id.IntegerValue)

# -----------------------------------------------------
# 7) Записываем на КАЖДЫЙ выбранный пользователем элемент
# -----------------------------------------------------
updated = 0
with revit.Transaction(u"Установка параметров Rebar Tag (multi)"):
    for target in selected_elems:
        ok_any = False
        for src_name, tgt_name in PARAM_MAP_TARGET.items():
            if set_param_value(target, tgt_name, values.get(src_name, u"")):
                ok_any = True
        if ok_any:
            updated += 1

forms.alert(u"Values transferred to {} item(s).".format(updated))
