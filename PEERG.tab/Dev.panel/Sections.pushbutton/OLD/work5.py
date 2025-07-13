# -*- coding: utf-8 -*-
__title__ = "TypeSections"
__author__ = "Your Name"

from pyrevit import revit, script
from Autodesk.Revit.DB import FilteredElementCollector, BuiltInCategory, XYZ, Transaction

output = script.get_output()
view = revit.active_view

FT_TO_MM = 304.8
MM_TO_FT = 1.0 / 304.8

def insertfamily():
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
        output.print_md(
            u"Вставка семейства по точке X={}, Y={}, Z={} мм (глобально, автоосева)".format(
                int(round(insert_point.X * FT_TO_MM)),
                int(round(insert_point.Y * FT_TO_MM)),
                int(round(insert_point.Z * FT_TO_MM))
            )
        )
        if hasattr(detail_type, 'IsActive') and not detail_type.IsActive:
            t = Transaction(revit.doc, u"Активация типа семейства")
            t.Start()
            detail_type.Activate()
            t.Commit()
        t = Transaction(revit.doc, u"Вставка детали")
        t.Start()
        family_instance = revit.doc.Create.NewFamilyInstance(insert_point, detail_type, view)
        t.Commit()
        output.print_md(
            u"✅ Семейство '{}' типа '{}' вставлено в автоопределённую точку.".format(fam_name, type_name)
        )
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
        output.print_md(
            u"🔧 Параметры заданы: Beam_Width={:.2f} см, Beam_Height={:.2f} см, Floor_Height={:.2f} см".format(
                beam_width, beam_height, floor_thickness)
        )
    else:
        output.print_md(
            u"❗ Не найден тип семейства '{}' типа '{}' для вставки.".format(fam_name, type_name))

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

beams = list(FilteredElementCollector(revit.doc, view.Id).OfCategory(BuiltInCategory.OST_StructuralFraming).WhereElementIsNotElementType())
floors = list(FilteredElementCollector(revit.doc, view.Id).OfCategory(BuiltInCategory.OST_Floors).WhereElementIsNotElementType())

if len(beams) != 1 or len(floors) != 1:
    output.print_md(u"❗ На активном виде должно быть ровно одна балка и одно перекрытие! Сейчас: Балок = {}, Плит = {}".format(len(beams), len(floors)))
else:
    beam = beams[0]
    floor = floors[0]
    slope_param = floor.LookupParameter("Slope") or floor.LookupParameter(u"Уклон")
    if slope_param and abs(slope_param.AsDouble()) > 1e-6:
        output.print_md(u"⚠️ Перекрытие на виде имеет уклон! Скрипт не выполняется для плит под уклоном.")
    else:
        beam_bbox = beam.get_BoundingBox(view)
    floor_bbox = floor.get_BoundingBox(view)
    if not beam_bbox or not floor_bbox:
        output.print_md(u"❗ Не удалось получить bounding box балки или плиты.")
    else:
        bx_min, by_min = world_to_view_coords_mm(beam_bbox.Min, view)
        bx_max, by_max = world_to_view_coords_mm(beam_bbox.Max, view)
        fx_min, fy_min = world_to_view_coords_mm(floor_bbox.Min, view)
        fx_max, fy_max = world_to_view_coords_mm(floor_bbox.Max, view)
        beam_width = abs(bx_max - bx_min)
        beam_height = abs(by_max - by_min)
        beam_height_top = max(abs(by_max - fy_min), 500)
        beam_height_bot = max(abs(by_min - fy_max), 500)
        floor_thickness = abs(fy_max - fy_min)
        floor_width = abs(fx_max - fx_min)
        beam_global_min = to_mm(beam_bbox.Min)
        beam_global_max = to_mm(beam_bbox.Max)
        output.print_md(u"Глобальные координаты (Revit XYZ):")
        output.print_md(u"Min: X={:.0f} мм, Y={:.0f} мм, Z={:.0f} мм".format(*beam_global_min))
        output.print_md(u"Max: X={:.0f} мм, Y={:.0f} мм, Z={:.0f} мм".format(*beam_global_max))
        output.print_md(u"**Балка**:")
        output.print_md(u"Xmin = {:.0f} мм, Xmax = {:.0f} мм".format(bx_min, bx_max))
        output.print_md(u"Ymin = {:.0f} мм, Ymax = {:.0f} мм".format(by_min, by_max))
        output.print_md(u"Ширина = {:.0f} мм, Высота = {:.0f} мм".format(beam_width, beam_height))
        output.print_md(u"**Плита**:")
        floor_global_min = to_mm(floor_bbox.Min)
        floor_global_max = to_mm(floor_bbox.Max)
        output.print_md(u"Глобальные координаты (Revit XYZ):")
        output.print_md(u"Min: X={:.0f} мм, Y={:.0f} мм, Z={:.0f} мм".format(*floor_global_min))
        output.print_md(u"Max: X={:.0f} мм, Y={:.0f} мм, Z={:.0f} мм".format(*floor_global_max))
        output.print_md(u"Xmin = {:.0f} мм, Xmax = {:.0f} мм".format(fx_min, fx_max))
        output.print_md(u"Ymin = {:.0f} мм, Ymax = {:.0f} мм".format(fy_min, fy_max))
        output.print_md(u"Толщина = {:.0f} мм, Ширина = {:.0f} мм".format(floor_thickness, floor_width))

        # === Определение направления разреза ===
        basis_x = view.CropBox.Transform.BasisX
        basis_y = view.CropBox.Transform.BasisY
        section_dir = None
        direction = None
        # Проверяем преобладающее направление секции
        if abs(basis_x.X) > abs(basis_x.Y):
            direction = "X"
            if basis_x.X > 0:
                section_dir = "LeftToRight"
            else:
                section_dir = "RightToLeft"
        elif abs(basis_x.Y) > abs(basis_x.X):
            direction = "Y"
            if basis_x.Y > 0:
                section_dir = "BottomToTop"
            else:
                section_dir = "TopToBottom"
        else:
            direction = "Angled"
            section_dir = "Angled"
        output.print_md(u"🧭 Направление разреза: {} ({})".format(direction, section_dir))

        # === Дальше логика зависит от направления ===
        tolerance = 30  # мм
        def eq(a, b, tol=tolerance):
            return abs(a - b) < tol

        section_type = None
        if direction == "X":
            if section_dir == "LeftToRight":
                # Стандартная логика как раньше
                if eq(fx_min, bx_min):
                    if eq(fy_min, by_min):
                        section_type = "Сечение А"
                    elif eq(fy_max, by_max):
                        section_type = "Сечение B"
                    elif by_max > fy_max and by_min < fy_min:
                        section_type = "Сечение H"
                elif eq(fx_max, bx_max):
                    if eq(fy_min, by_min):
                        section_type = "Сечение D"
                    elif eq(fy_max, by_max):
                        section_type = "Сечение C"
                    elif by_max > fy_max and by_min < fy_min:
                        section_type = "Сечение G"
                elif bx_max < fx_max and bx_min > fx_min:
                    if eq(by_min, fy_min):
                        section_type = "Сечение E"
                    elif eq(by_max, fy_max):
                        section_type = "Сечение F"
                    elif by_max > fy_max and by_min < fy_min:
                        section_type = "Сечение I"
            elif section_dir == "RightToLeft":
                # Инвертируем X-границы (левый и правый края меняются местами!)
                if eq(fx_max, bx_max):
                    if eq(fy_min, by_min):
                        section_type = "Сечение А"
                    elif eq(fy_max, by_max):
                        section_type = "Сечение B"
                    elif by_max > fy_max and by_min < fy_min:
                        section_type = "Сечение H"
                elif eq(fx_min, bx_min):
                    if eq(fy_min, by_min):
                        section_type = "Сечение D"
                    elif eq(fy_max, by_max):
                        section_type = "Сечение C"
                    elif by_max > fy_max and by_min < fy_min:
                        section_type = "Сечение G"
                elif bx_min > fx_min and bx_max < fx_max:
                    if eq(by_min, fy_min):
                        section_type = "Сечение E"
                    elif eq(by_max, fy_max):
                        section_type = "Сечение F"
                    elif by_max > fy_max and by_min < fy_min:
                        section_type = "Сечение I"
        elif direction == "Y":
            if section_dir == "BottomToTop":
                # Аналогично — стандартная логика по Y
                if eq(fy_min, by_min):
                    if eq(fx_min, bx_min):
                        section_type = "Сечение А"
                    elif eq(fx_max, bx_max):
                        section_type = "Сечение D"
                    elif bx_max > fx_max and bx_min < fx_min:
                        section_type = "Сечение E"
                elif eq(fy_max, by_max):
                    if eq(fx_min, bx_min):
                        section_type = "Сечение B"
                    elif eq(fx_max, bx_max):
                        section_type = "Сечение C"
                    elif bx_max > fx_max and bx_min < fx_min:
                        section_type = "Сечение F"
                elif by_max > fy_max and by_min < fy_min:
                    section_type = "Сечение I"
            elif section_dir == "TopToBottom":
                # Инвертируем Y-границы
                if eq(fy_max, by_max):
                    if eq(fx_min, bx_min):
                        section_type = "Сечение А"
                    elif eq(fx_max, bx_max):
                        section_type = "Сечение D"
                    elif bx_max > fx_max and bx_min < fx_min:
                        section_type = "Сечение E"
                elif eq(fy_min, by_min):
                    if eq(fx_min, bx_min):
                        section_type = "Сечение B"
                    elif eq(fx_max, bx_max):
                        section_type = "Сечение C"
                    elif bx_max > fx_max and bx_min < fx_min:
                        section_type = "Сечение F"
                elif by_max > fy_max and by_min < fy_min:
                    section_type = "Сечение I"
        else:
            section_type = None
        if section_type:
            output.print_md(u"### 🟩 Тип сечения: **{}**".format(section_type))
            def get_section_insert_point(beam_center, floor_center, view):
                bx = view.CropBox.Transform.BasisX
                by = view.CropBox.Transform.BasisY
                bz = view.CropBox.Transform.BasisZ
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
            fam_name = "PR_RebarSection A,D"
            if section_type == "Сечение А":
                type_name = "Type A"
                insertfamily()
            elif section_type == "Сечение D":
                type_name = "Type D"
                insertfamily()
            elif section_type == "Сечение B":
                type_name = "Type B"
                insertfamily()
            elif section_type == "Сечение C":
                type_name = "Type C"
                insertfamily()
            elif section_type == "Сечение H":
                type_name = "Type H"
                insertfamily()
            elif section_type == "Сечение G":
                type_name = "Type G"
                insertfamily()
            elif section_type == "Сечение I":
                type_name = "Type I"
                insertfamily()
            elif section_type == "Сечение E":
                type_name = "Type E"
                insertfamily()
            elif section_type == "Сечение F":
                type_name = "Type F"
                insertfamily()
