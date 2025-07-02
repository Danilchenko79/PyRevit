# -*- coding: utf-8 -*-
__title__ = "Rebar Renumber"
__author__ = "ChatGPT + Dim"

from pyrevit import revit, DB, forms, script
from Autodesk.Revit.DB import *
import re

doc = revit.doc
output = script.get_output()
output.print_md("### Rebar list by selected sheets")

# 1️⃣ User selects sheets (MULTISELECT!)
sheets = FilteredElementCollector(doc).OfCategory(BuiltInCategory.OST_Sheets).WhereElementIsNotElementType().ToElements()
sheet_list = forms.SelectFromList.show(
    sheets,
    name_attr="SheetNumber",
    multiselect=True,
    title="Select sheets for analysis"
)
if not sheet_list:
    forms.alert("No sheets selected!")
    script.exit()

# 2️⃣ Functions for retrieving type and instance parameters

def get_type_param(elem, param_name):
    symbol = elem.Symbol
    param = symbol.LookupParameter(param_name)
    if param:
        if param.StorageType == StorageType.String:
            return param.AsString()
        elif param.StorageType == StorageType.Integer:
            return str(param.AsInteger())
        elif param.StorageType == StorageType.Double:
            return param.AsValueString()
        else:
            return ""
    return ""

def get_inst_param(e, n):
    p = e.LookupParameter(n)
    if not p:
        return ""
    if p.StorageType == StorageType.Double:
        return p.AsValueString()
    elif p.StorageType == StorageType.String:
        return p.AsString() or ""
    elif p.StorageType == StorageType.Integer:
        return str(p.AsInteger())
    else:
        return ""

def extract_number_from_string(value_string):
    if not value_string:
        return 0
    match = re.search(r"[-+]?\d*\.\d+|\d+", value_string.replace(',', '.'))
    if match:
        return float(match.group())
    return 0

# 3️⃣ Main collection and marking
all_items = []
with revit.Transaction("Assigning mark by sheet"):
    for sheet in sheet_list:
        sheet_number = sheet.SheetNumber
        # Find views on the sheet
        view_ids = sheet.GetAllViewports()
        views = []
        for vp_id in view_ids:
            vp = doc.GetElement(vp_id)
            view = doc.GetElement(vp.ViewId)
            if view:
                views.append(view)
        # For each view, find Detail Items
        for view in views:
            collector = FilteredElementCollector(doc, view.Id)\
                .OfCategory(BuiltInCategory.OST_DetailComponents)\
                .WhereElementIsNotElementType()
            for item in collector:
                if isinstance(item, FamilyInstance):
                    fam_name = item.Symbol.Family.Name
                    if fam_name.startswith("PEER_Rebar_Shape"):
                        # Assign "Mark" parameter (or another one if not standard) to sheet number
                        mark_param = item.LookupParameter("Mark")  # change "Mark" if you use a custom parameter!
                        if mark_param:
                            mark_param.Set(sheet_number)
                        # Collect parameters for the table
                        rebar_shape = get_type_param(item, "Rebar_Shape")
                        rebar_number = get_inst_param(item, "Rebar_Number")
                        rebar_diameter = get_inst_param(item, "Rebar_Diameter")
                        rebar_length = get_inst_param(item, "Rebar_Length")
                        rebar_a = get_inst_param(item, "Rebar_A")
                        all_items.append({
                            "elem": item,
                            "SheetNumber": sheet_number,
                            "Rebar_Number": rebar_number,
                            "Rebar_Shape": rebar_shape,
                            "Rebar_Diameter": rebar_diameter,
                            "Rebar_Length": rebar_length,
                            "Rebar_A": rebar_a
                        })

# 4️⃣ Grouping, sorting, and output
from collections import defaultdict

def num(x):
    try:
        return float(str(x).replace(",", ".").split()[0])
    except:
        return 0

grouped = defaultdict(lambda: {"count": 0, "Rebar_Number": [], "items": []})

for i in all_items:
    key = (
        i["Rebar_Shape"],
        num(i["Rebar_Diameter"]),
        num(i["Rebar_Length"]),
        num(i["Rebar_A"])
    )
    grouped[key]["count"] += 1
    grouped[key]["Rebar_Number"].append(i["Rebar_Number"])
    grouped[key]["items"].append(i["elem"])

# Transform to list for sorting
grouped_list = []
for k, v in grouped.items():
    grouped_list.append({
        "Rebar_Shape": k[0],
        "Rebar_Diameter": str(k[1]),
        "Rebar_Length": str(k[2]),
        "Rebar_A": str(k[3]),
        "Count": v["count"],
        "Rebar_Number": ", ".join(sorted(set(v["Rebar_Number"])))
    })

# Sorting as in the schedule
sorted_grouped = sorted(
    grouped_list,
    key=lambda i: (
        i["Rebar_Shape"],
        num(i["Rebar_Diameter"]),
        num(i["Rebar_Length"]),
        num(i["Rebar_A"])
    )
)

# 5️⃣ Numbering and output result (table with quantities)
# Numbers to skip
skip_numbers = set([8,10,12,14,16,18,20,22,25,28,30])
# Request starting number from user
start_number = forms.ask_for_string(
    default="1",
    prompt="Enter starting number for numbering (Rebar_Number)"
)
try:
    start_number = int(start_number)
except:
    forms.alert("Invalid number. Defaulting to 1.")
    start_number = 1

# Generate Rebar_Number
current_number = start_number
for entry in sorted_grouped:
    while current_number in skip_numbers:
        current_number += 1
    entry["Rebar_Number"] = str(current_number)
    current_number += 1

# (Optional) Write new numbers to elements’ parameters
with revit.Transaction("Update Rebar_Number values"):
    for entry in sorted_grouped:
        # Find group of elements
        for it in grouped[(entry["Rebar_Shape"], num(entry["Rebar_Diameter"]), num(entry["Rebar_Length"]), num(entry["Rebar_A"]))]["items"]:
            param = it.LookupParameter("Rebar_Number")
            if param:
                try:
                    param.Set(int(entry["Rebar_Number"]))
                except:
                    param.Set(str(entry["Rebar_Number"]))


from pyrevit import revit, forms, script
from Autodesk.Revit.DB import *
from Autodesk.Revit.DB import UnitUtils, UnitTypeId

doc = revit.doc

# Annotation family name
ANNOTATION_FAMILY_NAME = "PEER_Rebar TAG"

# 1. Determine the sheet to work with
active_view = revit.active_view
sheet = None

# If currently on a sheet — use it directly
if isinstance(active_view, ViewSheet):
    sheet = active_view
else:
    # If the active view is placed on a sheet — find sheet via Viewport
    viewports = FilteredElementCollector(doc).OfClass(Viewport).ToElements()
    for vp in viewports:
        if vp.ViewId == active_view.Id:
            sheet = doc.GetElement(vp.SheetId)
            break

if not sheet:
    forms.alert("Active view is not placed on a sheet, or sheet not found.")
    script.exit()

# 2. Find all views placed on this sheet
views_on_sheet = []
viewports = FilteredElementCollector(doc).OfClass(Viewport).ToElements()
for vp in viewports:
    if vp.SheetId == sheet.Id:
        view = doc.GetElement(vp.ViewId)
        if view:
            views_on_sheet.append(view)

if not views_on_sheet:
    forms.alert("No views found on the sheet.")
    script.exit()

# 3. Collect all annotation instances on all views of the sheet
annotation_instances = []
for view in views_on_sheet:
    collector = FilteredElementCollector(doc, view.Id)\
        .OfCategory(BuiltInCategory.OST_DetailComponents)\
        .WhereElementIsNotElementType()
    for fi in collector:
        if isinstance(fi, FamilyInstance):
            try:
                if fi.Symbol.Family.Name == ANNOTATION_FAMILY_NAME:
                    annotation_instances.append(fi)
            except Exception:
                continue

if not annotation_instances:
    forms.alert("No annotation families '{}' found on the selected sheet views.".format(ANNOTATION_FAMILY_NAME))
    script.exit()

# Function to get parameter value
def get_param_value(elem, param_name):
    param = elem.LookupParameter(param_name)
    if param:
        try:
            if param.StorageType == StorageType.Integer:
                return str(param.AsInteger())
            elif param.StorageType == StorageType.Double:
                raw_value = param.AsValueString()
                cleaned = "".join(c for c in raw_value if c.isdigit() or c in ['.', ','])
                return cleaned
            else:
                return param.AsString() or "(empty)"
        except Exception:
            return "(read error)"
    return None

# Function to set parameter value
def set_param_value(elem, param_name, value):
    param = elem.LookupParameter(param_name)
    if param and value:
        try:
            cleaned_value = "".join(c for c in str(value) if c.isdigit() or c in ['.', ','])
            if param.StorageType == StorageType.Integer:
                param.Set(int(float(cleaned_value)))
            elif param.StorageType == StorageType.Double:
                internal_value = UnitUtils.ConvertToInternalUnits(float(cleaned_value), UnitTypeId.Millimeters)
                param.Set(internal_value)
            else:
                param.Set(str(value))
        except Exception as e:
            forms.alert("Error setting parameter '{}': {}".format(param_name, e))

# Main part: update annotation parameters
updated_count = 0
missing_elements = []

with revit.Transaction("Update rebar annotation parameters"):
    for tag in annotation_instances:
        source_id_param = tag.LookupParameter("PR_Rebar_ID")
        if source_id_param:
            try:
                raw_id = source_id_param.AsString() or source_id_param.AsValueString()
                if not raw_id:
                    continue
                source_id_str = "".join(c for c in raw_id if c.isdigit())
                if not source_id_str:
                    continue
                source_elem_id = int(source_id_str)
                source_elem = doc.GetElement(ElementId(source_elem_id))
                if not source_elem:
                    missing_elements.append(source_id_str)
                    continue

                # Read parameters from source element
                rebar_number = get_param_value(source_elem, "Rebar_Number")
                rebar_diameter = get_param_value(source_elem, "Rebar_Diameter")
                rebar_length = get_param_value(source_elem, "Rebar_Length")

                # Write parameters back into annotation
                set_param_value(tag, "Rebar_Number", rebar_number)
                set_param_value(tag, "Rebar_Diameter", rebar_diameter)
                set_param_value(tag, "Rebar_Length", rebar_length)

                updated_count += 1
            except Exception as e:
                forms.alert("Error processing element ID {}: {}".format(raw_id, e))

# Show results
result_message = "Updated {} rebar annotations.".format(updated_count)
if missing_elements:
    missing_str = ", ".join(missing_elements)
    result_message += "\n\n⚠️ The following elements were not found (possibly deleted): {}".format(missing_str)

forms.alert(result_message)
