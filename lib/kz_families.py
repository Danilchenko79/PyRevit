# -*- coding: utf-8 -*-
"""kz_families — автосоздание 2D-семейств стандарта КЖ через Revit API.

Создаются (если их ещё нет в проекте):
    KZ_Dot       — точка продольного стержня в сечении: залитый круг Ø30 мм
                   (модельных; 1.2 мм бумаги при 1:25). Без параметров —
                   диаметр стержня сообщает тег (марка погонной = Ø).
    KZ_RebarLine — штрих арматуры плиты: линия длиной Length (instance,
                   флексится подписанным размером), рисуется от точки
                   вставки в +X.

Массивы и лейблы тегов через API не создаются (краши/нет API) — эти два
примитива нарочно без них. .rfa сохраняются в lib/KZ_Families/.
"""

import math
import os

from Autodesk.Revit.DB import (
    FilteredElementCollector, FamilySymbol, Transaction, XYZ, Line, Arc,
    CurveLoop, FilledRegion, FilledRegionType, ReferencePlane, View, ViewPlan,
    ReferenceArray, GroupTypeId, SpecTypeId, IFamilyLoadOptions,
)
from System.Collections.Generic import List

FT_MM = 304.8

DOT_NAME = u'KZ_Dot'
LINE_NAME = u'KZ_RebarLine'
DOT_RADIUS_MM = 15.0
LINE_DEFAULT_MM = 900.0


def to_ft(v):
    return v / FT_MM


def find_symbol(doc, family_name):
    for fs in FilteredElementCollector(doc).OfClass(FamilySymbol):
        try:
            if fs.FamilyName == family_name:
                return fs
        except Exception:
            pass
    return None


class _LoadOpts(IFamilyLoadOptions):
    def OnFamilyFound(self, familyInUse, overwriteParameterValues):
        overwriteParameterValues.Value = True
        return True

    def OnSharedFamilyFound(self, sharedFamily, familyInUse, source,
                            overwriteParameterValues):
        overwriteParameterValues.Value = True
        return True


def _template_path(app):
    base = app.FamilyTemplatePath
    cands = [os.path.join(base, u'Metric Detail Item.rft')]
    try:
        for f in os.listdir(base):
            fl = f.lower()
            if fl.endswith(u'.rft') and u'detail item' in fl \
                    and u'line based' not in fl and u'tag' not in fl:
                cands.append(os.path.join(base, f))
    except Exception:
        pass
    for c in cands:
        if os.path.exists(c):
            return c
    return None


def _fam_view(famdoc):
    for v in FilteredElementCollector(famdoc).OfClass(View):
        try:
            if isinstance(v, ViewPlan) and not v.IsTemplate:
                return v
        except Exception:
            pass
    for v in FilteredElementCollector(famdoc).OfClass(View):
        if not v.IsTemplate:
            return v
    return None


def _center_planes(famdoc):
    """(вертикальная через 0, горизонтальная через 0) — базовые плоскости шаблона."""
    vert = horz = None
    for rp in FilteredElementCollector(famdoc).OfClass(ReferencePlane):
        n = rp.Normal
        if abs(n.X) > 0.9 and vert is None:
            vert = rp
        elif abs(n.Y) > 0.9 and horz is None:
            horz = rp
    return vert, horz


def _save_load(famdoc, doc, name, out_dir):
    if not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    path = os.path.join(out_dir, name + u'.rfa')
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            path = os.path.join(out_dir, name + u'_1.rfa')
    from Autodesk.Revit.DB import SaveAsOptions
    sao = SaveAsOptions()
    sao.OverwriteExistingFile = True
    famdoc.SaveAs(path, sao)
    famdoc.LoadFamily(doc, _LoadOpts())
    famdoc.Close(False)
    return path


def _build_dot(app, doc, out_dir):
    tpl = _template_path(app)
    if tpl is None:
        raise Exception(u'не найден шаблон Metric Detail Item.rft')
    famdoc = app.NewFamilyDocument(tpl)
    t = Transaction(famdoc, u'KZ_Dot')
    t.Start()
    try:
        view = _fam_view(famdoc)
        frt = FilteredElementCollector(famdoc).OfClass(FilledRegionType).FirstElement()
        if frt is None:
            raise Exception(u'нет FilledRegionType в шаблоне')
        r = to_ft(DOT_RADIUS_MM)
        c = XYZ(0, 0, 0)
        loop = CurveLoop()
        loop.Append(Arc.Create(c, r, 0.0, math.pi, XYZ.BasisX, XYZ.BasisY))
        loop.Append(Arc.Create(c, r, math.pi, 2.0 * math.pi,
                               XYZ.BasisX, XYZ.BasisY))
        loops = List[CurveLoop]()
        loops.Add(loop)
        FilledRegion.Create(famdoc, frt.Id, view.Id, loops)
        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        famdoc.Close(False)
        raise
    return _save_load(famdoc, doc, DOT_NAME, out_dir)


def _build_line(app, doc, out_dir):
    tpl = _template_path(app)
    if tpl is None:
        raise Exception(u'не найден шаблон Metric Detail Item.rft')
    famdoc = app.NewFamilyDocument(tpl)
    t = Transaction(famdoc, u'KZ_RebarLine')
    t.Start()
    try:
        view = _fam_view(famdoc)
        fm = famdoc.FamilyManager
        if fm.Types.Size < 1:
            fm.NewType(u'KZ')
        param = fm.AddParameter(u'Length', GroupTypeId.Geometry,
                                SpecTypeId.Length, True)
        L = to_ft(LINE_DEFAULT_MM)
        fm.Set(param, L)
        cv, ch = _center_planes(famdoc)
        rp = famdoc.FamilyCreate.NewReferencePlane(
            XYZ(L, -1.0, 0), XYZ(L, 1.0, 0), XYZ(0, 0, 1), view)
        rp.Name = u'KZ_Right'
        # подписанный размер: центр -> правая плоскость = Length
        ra = ReferenceArray()
        ra.Append(cv.GetReference())
        ra.Append(rp.GetReference())
        dim_line = Line.CreateBound(XYZ(0, 0.5, 0), XYZ(L, 0.5, 0))
        dim = famdoc.FamilyCreate.NewDimension(view, dim_line, ra)
        dim.FamilyLabel = param
        # сам штрих: по горизонтальной оси, концы привязаны к плоскостям
        dl = famdoc.FamilyCreate.NewDetailCurve(
            view, Line.CreateBound(XYZ(0, 0, 0), XYZ(L, 0, 0)))
        gc = dl.GeometryCurve
        try:
            famdoc.FamilyCreate.NewAlignment(view, gc.Reference,
                                             ch.GetReference())
        except Exception:
            pass
        try:
            famdoc.FamilyCreate.NewAlignment(
                view, gc.GetEndPointReference(0), cv.GetReference())
            famdoc.FamilyCreate.NewAlignment(
                view, gc.GetEndPointReference(1), rp.GetReference())
        except Exception:
            pass
        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        famdoc.Close(False)
        raise
    return _save_load(famdoc, doc, LINE_NAME, out_dir)


def ensure_families(doc, warn):
    """Гарантирует KZ_Dot и KZ_RebarLine в проекте. Возвращает (dot, line)."""
    app = doc.Application
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           u'KZ_Families')
    dot = find_symbol(doc, DOT_NAME)
    line = find_symbol(doc, LINE_NAME)
    if dot is None:
        try:
            _build_dot(app, doc, out_dir)
            dot = find_symbol(doc, DOT_NAME)
        except Exception as e:
            warn.append(u'создание {}: {}'.format(DOT_NAME, e))
    if line is None:
        try:
            _build_line(app, doc, out_dir)
            line = find_symbol(doc, LINE_NAME)
        except Exception as e:
            warn.append(u'создание {}: {}'.format(LINE_NAME, e))
    return dot, line
