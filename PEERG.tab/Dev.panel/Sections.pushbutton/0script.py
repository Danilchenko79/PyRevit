# -*- coding: utf-8 -*-
__title__ = "TypeSections"
__author__ = "Your Name"

from pyrevit import revit, script
from Autodesk.Revit.DB import FilteredElementCollector, BuiltInCategory, XYZ, Transaction, ViewSheet, ViewSection

output = script.get_output()
FT_TO_MM = 304.8
MM_TO_FT = 1.0 / 304.8

def world_to_view_coords_mm(point, view):
    transform = view.CropBox.Transform
    origin = transform.Origin
    right = transform.BasisX
    up = transform.BasisY
    rel = point - origin
    x = rel.DotProduct(right) * FT_TO_MM
    y = rel.DotProduct(up) * FT_TO_MM
    return x, y

def to_mm(xyz):
    return xyz.X * FT_TO_MM, xyz.Y * FT_TO_MM, xyz.Z * FT_TO_MM

def eq(a, b, tol):
    return abs(a - b) < tol

def get_section_insert_point(beam_center, floor_center, view):
    bx = view.CropBox.Transform.BasisX
    bz = view.CropBox.Transform.BasisZ
    # Определяем главную ось разреза
    if abs(bx.X) > abs(bx.Y):
        return XYZ(beam_center.X, beam_center.Y, floor_center.Z)
    elif abs(bx.Y) > abs(bx.X):
        return XYZ(beam_center.X, beam_center.Y, floor_center.Z)
    else:
        origin = view.CropBox.Transform.Origin
        vec_to_beam = beam_center - origin
        hor = bx.Normalize()
        vert = bz.Normalize()
        hor_coord = vec_to_beam.DotProduct(hor)
        vert_coord = floor_center.Z
        insert_point = origin + hor.Multiply(hor_coord) + vert.Multiply(vert_coord)
        return insert_point

def insertfamily(view, beam, floor, fam_name, type_name,
                 beam_bbox, floor_bbox, beam_width, beam_height_top, beam_height_bot, floor_thickness):
    coll = FilteredElementCollector(revit.doc).OfCategory(BuiltInCategory.OST_DetailComponents).WhereElementIsElementType()
    detail_type = None
    for ft in coll:
        fam = None
        tname = None
        try:
            fam = ft.FamilyName
        except:
            try:
                fam = ft.Symbol.Family.Name
            except:
                fam = None
        try:
            tname = ft.Name
        except:
            tname = None
        if not tname and ft.LookupParameter("Type Name"):
            tname = ft.LookupParameter("Type Name").AsString()
        if fam == fam_name and tname == type_name:
            detail_type = ft
            break

    if detail_type:
        beam_center = XYZ(
            (beam_bbox.Min.X + beam_bbox.Max.X) / 2.0,
            (beam_bbox.Min.Y + beam_bbox.Max.Y) / 2.0,
            (beam_bbox.Min.Z + beam_bbox.Max.Z) / 2.0
        )
        floor_center = XYZ(
            (floor_bbox.Min.X + floor_bbox.Max.X) / 2.0,
            (floor_bbox.Min.Y + floor_bbox.Max.Y) / 2.0,
            (floor_bbox.Min.Z + floor_bbox.Max.Z) / 2.0
        )
        insert_point = get_section_insert_point(beam_center, floor_center, view)


        # Активируем тип семейства, если нужно
        if hasattr(detail_type, 'IsActive') and not detail_type.IsActive:
            t = Transaction(revit.doc, u"Активация типа семейства")
            t.Start()
            detail_type.Activate()
            t.Commit()
        # Вставляем экземпляр
        t = Transaction(revit.doc, u"Вставка детали")
        t.Start()
        family_instance = revit.doc.Create.NewFamilyInstance(insert_point, detail_type, view)
        t.Commit()
        # output.print_md(
        #     u"Вставка семейства по точке X={}, Y={}, Z={} мм (глобально, автоосева)".format(
        #         int(round(insert_point.X * FT_TO_MM)),
        #         int(round(insert_point.Y * FT_TO_MM)),
        #         int(round(insert_point.Z * FT_TO_MM))
        #     )
        # )

        # Устанавливаем параметры
        beam_width_ft = beam_width * MM_TO_FT
        beam_heightTop_ft = beam_height_top * MM_TO_FT
        beam_heightBot_ft = beam_height_bot * MM_TO_FT
        floor_height_ft = floor_thickness * MM_TO_FT
        t = Transaction(revit.doc, u"Установка параметров семейства")
        t.Start()
        if family_instance.LookupParameter("Beam_Width"):
            family_instance.LookupParameter("Beam_Width").Set(beam_width_ft)
        if family_instance.LookupParameter("Beam_HeightTop"):
            family_instance.LookupParameter("Beam_HeightTop").Set(beam_heightTop_ft)
        if family_instance.LookupParameter("Beam_HeightBot"):
            family_instance.LookupParameter("Beam_HeightBot").Set(beam_heightBot_ft)
        if family_instance.LookupParameter("Floor_Height"):
            family_instance.LookupParameter("Floor_Height").Set(floor_height_ft)
        t.Commit()
        # output.print_md(
        #     u"🔧 Параметры заданы: Beam_Width={:.2f} см, Beam_Height={:.2f} см, Floor_Height={:.2f} см".format(
        #         beam_width, beam_height_top, floor_thickness)
        # )
    else:
        output.print_md(
            u"❗ Не найден тип семейства '{}' типа '{}' для вставки.".format(fam_name, type_name))

def process_view(view):
    # Весь основной код — теперь можно вызывать и для листа, и для разреза
    beams = list(FilteredElementCollector(revit.doc, view.Id).OfCategory(BuiltInCategory.OST_StructuralFraming).WhereElementIsNotElementType())
    floors = list(FilteredElementCollector(revit.doc, view.Id).OfCategory(BuiltInCategory.OST_Floors).WhereElementIsNotElementType())

    if len(beams) != 1 or len(floors) != 1:
        output.print_md(u"❗ На активном виде должно быть ровно одна балка и одно перекрытие! Сейчас: Балок = {}, Плит = {}".format(len(beams), len(floors)))
        return
    beam = beams[0]
    floor = floors[0]
    slope_param = floor.LookupParameter("Slope") or floor.LookupParameter(u"Уклон")
    if slope_param and abs(slope_param.AsDouble()) > 1e-6:
        output.print_md(u"⚠️ Перекрытие на виде имеет уклон! Скрипт не выполняется для плит под уклоном.")
        return
    beam_bbox = beam.get_BoundingBox(view)
    floor_bbox = floor.get_BoundingBox(view)
    if not beam_bbox or not floor_bbox:
        output.print_md(u"❗ Не удалось получить bounding box балки или плиты.")
        return
    bx_min, by_min = world_to_view_coords_mm(beam_bbox.Min, view)
    bx_max, by_max = world_to_view_coords_mm(beam_bbox.Max, view)
    fx_min, fy_min = world_to_view_coords_mm(floor_bbox.Min, view)
    fx_max, fy_max = world_to_view_coords_mm(floor_bbox.Max, view)
    beam_width = abs(bx_max - bx_min)
    beam_height_top = max(abs(by_max - fy_min), 400)
    beam_height_bot = max(abs(by_min - fy_max), 400)
    floor_thickness = abs(fy_max - fy_min)
    tolerance = 30
    section_type = None
    def eq2(a, b, tol=tolerance):
        return abs(a - b) < tol
    if eq2(fx_min, bx_min):
        if eq2(fy_min, by_min):
            section_type = "Сечение А"
        elif eq2(fy_max, by_max):
            section_type = "Сечение B"
        elif by_max > fy_max and by_min < fy_min:
            section_type = "Сечение H"
    elif eq2(fx_max, bx_max):
        if eq2(fy_min, by_min):
            section_type = "Сечение D"
        elif eq2(fy_max, by_max):
            section_type = "Сечение C"
        elif by_max > fy_max and by_min < fy_min:
            section_type = "Сечение G"
    elif bx_max < fx_max and bx_min > fx_min:
        if eq2(by_min, fy_min):
            section_type = "Сечение E"
        elif eq2(by_max, fy_max):
            section_type = "Сечение F"
        elif by_max > fy_max and by_min < fy_min:
            section_type = "Сечение I"
    if section_type:
        output.print_md(u"### 🟩 Тип сечения: **{}**".format(section_type))
        fam_name = "PR_RebarSection A,D"  # заменить на актуальное имя
        section_type_map = {
            "Сечение А": "Type A",
            "Сечение D": "Type D",
            "Сечение B": "Type B",
            "Сечение C": "Type C",
            "Сечение H": "Type H",
            "Сечение G": "Type G",
            "Сечение I": "Type I",
            "Сечение E": "Type E",
            "Сечение F": "Type F"
        }
        type_name = section_type_map.get(section_type, "")
        insertfamily(view, beam, floor, fam_name, type_name,
            beam_bbox, floor_bbox, beam_width, beam_height_top, beam_height_bot, floor_thickness)
    else:
        output.print_md(u"❗ Не удалось определить тип сечения.")

# Главный блок запуска — определяем, лист это или вид
active_view = revit.active_view
from Autodesk.Revit.DB import ViewSheet, ViewSection

doc = revit.doc
if isinstance(active_view, ViewSheet):
    viewport_ids = active_view.GetAllViewports()
    viewports = [doc.GetElement(vpid) for vpid in viewport_ids]
    views_on_sheet = [doc.GetElement(vp.ViewId) for vp in viewports]
    section_views = [v for v in views_on_sheet if isinstance(v, ViewSection)]
    output.print_md(u"🗂 Найдено {} разрезов на листе.".format(len(section_views)))
    for v in section_views:
        process_view(v)
else:
    process_view(active_view)