# -*- coding: utf-8 -*-

# ╦╔╦╗╔═╗╔═╗╦═╗╔╦╗╔═╗
# ║║║║╠═╝║ ║╠╦╝ ║ ╚═╗
# ╩╩ ╩╩  ╚═╝╩╚═ ╩ ╚═╝ IMPORTS
#====================================================================================================
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import ISelectionFilter, Selection, ObjectType

# ╦  ╦╔═╗╦═╗╦╔═╗╔╗ ╦  ╔═╗╔═╗
# ╚╗╔╝╠═╣╠╦╝║╠═╣╠╩╗║  ║╣ ╚═╗
#  ╚╝ ╩ ╩╩╚═╩╩ ╩╚═╝╩═╝╚═╝╚═╝
#==================================================
app       = __revit__.Application
uidoc     = __revit__.ActiveUIDocument
doc       = __revit__.ActiveUIDocument.Document #type:Document
selection = uidoc.Selection                     #type: Selection

# -*- coding: utf-8 -*-
__title__ = "Rebar Renumber"
__author__ = "ChatGPT + Dim"

from pyrevit import revit, DB, forms, script
from Autodesk.Revit.DB import *
import re

doc = revit.doc
output = script.get_output()


# -*- coding: utf-8 -*-
from pyrevit import revit
from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInCategory, FamilyInstance,
    Transaction, StorageType, UnitUtils, UnitTypeId, ElementId
)
from collections import defaultdict

# Константы по умолчанию (всегда используем)


def process_drafting_view(
    doc,
    drafting_view,
    family_prefix="PEER_Rebar_Shape",        # что нумеруем
    annotation_family_name="PEER_Rebar TAG", # какие теги обновляем
    param_rebar_number="Rebar_Number",
    param_rebar_diameter="Rebar_Diameter",
    param_rebar_length="Rebar_Length",
    param_rebar_a="Rebar_A",
    tag_source_id_param="PR_Rebar_ID"
):
    """Нумерация и обновление тегов ТОЛЬКО на переданном Drafting View."""
    # ---- helpers ----
    START_NUMBER = 1
    SKIP_NUMBERS = {8, 10, 12, 14, 16, 18, 20, 22, 25, 28, 30, 32}
    def get_type_param(elem, name):
        sym = elem.Symbol
        p = sym.LookupParameter(name) if sym else None
        if not p: return ""
        if p.StorageType == StorageType.String:  return p.AsString() or ""
        if p.StorageType == StorageType.Integer: return str(p.AsInteger())
        if p.StorageType == StorageType.Double:  return p.AsValueString() or ""
        return ""

    def get_inst_param(e, name):
        p = e.LookupParameter(name)
        if not p: return ""
        if p.StorageType == StorageType.Double:  return p.AsValueString() or ""
        if p.StorageType == StorageType.String:  return p.AsString() or ""
        if p.StorageType == StorageType.Integer: return str(p.AsInteger())
        return ""

    def as_num(x):
        try: return float(str(x).replace(",", ".").split()[0])
        except: return 0.0

    def extract_digits(s):
        return "".join(ch for ch in str(s) if ch.isdigit())

    def get_param_value(elem, name):
        p = elem.LookupParameter(name)
        if not p: return None
        try:
            if p.StorageType == StorageType.Integer:
                return str(p.AsInteger())
            elif p.StorageType == StorageType.Double:
                raw = p.AsValueString() or ""
                return "".join(c for c in raw if c.isdigit() or c in ['.', ','])
            else:
                return p.AsString() or ""
        except:
            return None

    def set_param_value(elem, name, value):
        p = elem.LookupParameter(name)
        if not p or value is None: return False
        try:
            if p.StorageType == StorageType.Integer:
                cleaned = extract_digits(value)
                p.Set(int(float(cleaned) if cleaned else 0)); return True
            elif p.StorageType == StorageType.Double:
                cleaned = "".join(c for c in str(value) if c.isdigit() or c in ['.', ','])
                mm = float(cleaned) if cleaned else 0.0
                p.Set(UnitUtils.ConvertToInternalUnits(mm, UnitTypeId.Millimeters)); return True
            else:
                p.Set(str(value)); return True
        except:
            return False

    # ---- 1) сбор/группировка/нумерация ----
    all_items = []
    coll = (FilteredElementCollector(doc, drafting_view.Id)
            .OfCategory(BuiltInCategory.OST_DetailComponents)
            .WhereElementIsNotElementType())
    for it in coll:
        if not isinstance(it, FamilyInstance): continue
        try:
            fam_name = it.Symbol.Family.Name
        except:
            continue
        if not fam_name or not fam_name.startswith(family_prefix): continue

        all_items.append({
            "elem": it,
            "Rebar_Shape":    get_type_param(it, "Rebar_Shape"),
            "Rebar_Diameter": get_inst_param(it, param_rebar_diameter),
            "Rebar_Length":   get_inst_param(it, param_rebar_length),
            "Rebar_A":        get_inst_param(it, param_rebar_a),
        })

    grouped = defaultdict(lambda: {"count": 0, "items": []})
    for row in all_items:
        key = (
            row["Rebar_Shape"],
            as_num(row["Rebar_Diameter"]),
            as_num(row["Rebar_Length"]),
            as_num(row["Rebar_A"])
        )
        grouped[key]["count"] += 1
        grouped[key]["items"].append(row["elem"])

    grouped_list = [{
        "Rebar_Shape": k[0],
        "Rebar_Diameter": str(k[1]),
        "Rebar_Length": str(k[2]),
        "Rebar_A": str(k[3]),
        "Count": v["count"],
        "key": k
    } for k, v in grouped.items()]

    sorted_grouped = sorted(
        grouped_list,
        key=lambda i: (i["Rebar_Shape"], as_num(i["Rebar_Diameter"]), as_num(i["Rebar_Length"]), as_num(i["Rebar_A"]))
    )

    current = START_NUMBER
    for entry in sorted_grouped:
        while current in SKIP_NUMBERS:
            current += 1
        entry["Rebar_Number"] = str(current)
        current += 1

    wrote_numbers = 0

    for entry in sorted_grouped:
        for el in grouped[entry["key"]]["items"]:
            p = el.LookupParameter(param_rebar_number)
            if not p: continue
            try:
                p.Set(int(entry["Rebar_Number"]))
            except:
                p.Set(entry["Rebar_Number"])
            wrote_numbers += 1


    doc.Regenerate()




    return {
        "count_items": len(all_items),
        "groups": len(grouped_list),
        "wrote_numbers": wrote_numbers,

    }

