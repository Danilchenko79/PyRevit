# -*- coding: utf-8 -*-
"""End-to-end check of the new Create Column button without its window, in a
blank project in the background (nothing in the open projects changes):

  PEER library 3D columns (PEER-Library-Source) of several sizes, marks and
  reinforcement -> revit_collect groups (as the window) -> button.run (as Create)
  -> checks: the view, one section per group, labels on the 3D columns, the bar
  list -> the view on an A1 sheet in a PDF.

    from column_rebar.tests import revit_e2e
    print(revit_e2e.run(app, families_folder, out_folder))
"""

import clr
import os
import uuid

import System
from System.Collections.Generic import List
from Autodesk.Revit.DB import (BuiltInCategory, BuiltInParameter, ElementId, ExportPaperFormat,
                               ExternalDefinitionCreationOptions, Family, FamilyInstance,
                               FilteredElementCollector, GroupTypeId, Level, PageOrientationType,
                               PDFExportOptions, SpecTypeId, UnitSystem, Viewport, ViewSheet, XYZ,
                               ZoomType)
from Autodesk.Revit.DB.Structure import StructuralType

from column_rebar import button, grouping, revit_collect, revit_draw, revit_params
from column_rebar.family_build import FT, run as tx

LIB3D = r'C:\Users\user\Desktop\PEER-Library-Source\01_Framing'
WORK = r'C:\Users\user\Desktop\Families Dima\04 Rebar\2D Rebar\Column Reiforcement (work)'
SHAPES = r'C:\Users\user\Desktop\Families Dima\04 Rebar\2D Rebar\Rebar shapes Family'
# project parameters the office template has (same GUIDs as the families')
PROJECT_PARAMS = [
    ('Rebar_QuantityX', 'de7637e2-5111-4f6b-ba9d-b8394ea5d7c3', SpecTypeId.Number),
    ('Rebar_QuantityY', '79cc3e37-3043-4df5-8f0d-fc304127fc48', SpecTypeId.Number),
    ('Rebar_Diameter', '5498ba20-78b8-42d5-a4bf-f4ba6f5c16dd', SpecTypeId.BarDiameter),
    ('PR_Level', None, SpecTypeId.String.Text),
]
# (marks, family, b, h, qx, qy, dia) - qx / qy as the families keep them
COLUMNS = [
    (['1', '2', '3', '4'], 'R', 400, 400, 2, 2, 16),
    (['5'], 'R', 600, 600, 3, 3, 20),
    (['6', '7'], 'R', 800, 800, 2, 2, 25),
    (['8', '9'], 'R', 1500, 600, 5, 1, 20),
    (['10'], 'R', 300, 300, 3, 3, 25),            # red: too much steel - must be skipped
    (['11', '12', '13'], 'O', 500, 1250, 3, 6, 20),
    (['14'], 'R', 500, 700, 2, 3, 20),
    (['15'], 'R', 400, 400, 2, 2, 16),            # same as 1-4 - joins their group
    ([''], 'R', 400, 400, 2, 2, 16),              # no mark - not drawn
]


def _bind_params(pd, folder):
    path = os.path.join(folder, 'e2e_params.txt')
    if os.path.exists(path):
        os.remove(path)
    open(path, 'w').close()
    app = pd.Application
    old = app.SharedParametersFilename
    try:
        app.SharedParametersFilename = path
        f = app.OpenSharedParameterFile()
        g = f.Groups.Create('E2E')
        cats = app.Create.NewCategorySet()
        cats.Insert(pd.Settings.Categories.get_Item(BuiltInCategory.OST_StructuralColumns))
        for name, guid, spec in PROJECT_PARAMS:
            o = ExternalDefinitionCreationOptions(name, spec)
            o.GUID = System.Guid(guid) if guid else System.Guid(str(uuid.uuid4()))
            d = g.Definitions.Create(o)
            pd.ParameterBindings.Insert(d, app.Create.NewInstanceBinding(cats), GroupTypeId.Data)
    finally:
        app.SharedParametersFilename = old


def run(app, folder, out_folder):
    if not os.path.isdir(out_folder):
        os.makedirs(out_folder)
    pd = app.NewProjectDocument(UnitSystem.Metric)
    lines = []
    try:
        fams = {}

        def setup():
            _bind_params(pd, out_folder)
            for key, n in (('R', 'PEER-Concrete-Column-Rectangular'), ('O', 'PEER-Concrete-Column-Rectangular Rounded')):
                r = clr.Reference[Family]()
                pd.LoadFamily(os.path.join(LIB3D, n + '.rfa'), r)
                fams[key] = r.Value
            for f in [os.path.join(folder, n + u'.rfa') for n in revit_draw.SECTION_FAMILY.values()] + \
                    [os.path.join(WORK, n) for n in (u'PEER_Rebar_Shape 52.rfa', u'PEER_Rebar_Shape 60.rfa',
                                                     u'PEER_Rebar_Shape 62.rfa', u'PR_Column Number.rfa')] + \
                    [os.path.join(SHAPES, n) for n in (u'Detail items_Tag Rebar.rfa',
                                                       u'Detail items_Tag Rebar(Text Quantity).rfa')]:
                pd.LoadFamily(f, clr.Reference[Family]())
            lvl = Level.Create(pd, 0)
            types = {}
            x = 0.0
            for marks, key, b, h, qx, qy, d in COLUMNS:
                tk = (key, b, h)
                if tk not in types:
                    base = pd.GetElement(list(fams[key].GetFamilySymbolIds())[0])
                    t = base.Duplicate('%dx%d' % (b, h))
                    t.LookupParameter('GeneralWidth').Set(b / FT)
                    t.LookupParameter('GeneralDepth').Set(h / FT)
                    t.Activate()
                    types[tk] = t
                for m in marks:
                    c = pd.Create.NewFamilyInstance(XYZ(x / FT, 0, 0), types[tk], lvl, StructuralType.Column)
                    x += 3000
                    c.LookupParameter('Mark').Set(m)
                    c.LookupParameter('PR_Level').Set(u'L1')
                    c.LookupParameter('Rebar_QuantityX').Set(float(qx))
                    c.LookupParameter('Rebar_QuantityY').Set(float(qy))
                    c.LookupParameter('Rebar_Diameter').Set(d / FT)
        r = tx(pd, 'setup', setup)
        lines.append('setup %s' % (r[1:],))
        # the window's part
        cols = revit_collect.level_columns(pd, u'L1')
        groups, no_mark = grouping.make_groups(cols)
        lines.append('columns %d, groups %d, without mark %d, levels %s' %
                     (len(cols), len(groups), len(no_mark), revit_collect.levels(pd)))
        for g in groups:
            lines.append('  %s %s %dx%d qb=%d qh=%d D%g cover=%g' % (g['shape'], ','.join(g['marks']), g['b'],
                                                                    g['h'], g['qb'], g['qh'], g['dia'], g['cover']))
        choice = {'level': u'L1', 'view': u'Column 150', 'width_cm': 59.4, 'groups': grouping.merge_groups(groups)}
        out = button.run(pd, choice, os.path.join(folder), lambda t: True, require_families=False)
        lines.append(button.summary(out, choice['view']))
        if out['ok']:
            v = out['view']
            secs = [e for e in FilteredElementCollector(pd, v.Id).OfClass(FamilyInstance)
                    if e.Symbol.FamilyName in revit_draw.SECTION_FAMILY.values()]
            lines.append('sections on the view: %d (drawn %d)' % (len(secs), out['drawn']))
            labels = []
            for c in FilteredElementCollector(pd).OfCategory(BuiltInCategory.OST_StructuralColumns).WhereElementIsNotElementType():
                p = revit_params.param(c, revit_params.LABEL)
                labels.append((c.LookupParameter('Mark').AsString(), p.AsString() if p is not None else None))
            lines.append('labels: %s' % sorted(labels))
            # a second run on the same view must replace, not add
            out2 = button.run(pd, choice, folder, lambda t: True, require_families=False)
            secs2 = [e for e in FilteredElementCollector(pd, v.Id).OfClass(FamilyInstance)
                     if e.Symbol.FamilyName in revit_draw.SECTION_FAMILY.values()]
            lines.append('second run: ok=%s, sections %d, error %s' % (out2['ok'], len(secs2), out2['error']))
            sheets = []

            def sheet():
                sh = ViewSheet.Create(pd, ElementId.InvalidElementId)
                sh.SheetNumber = 'E2E'
                Viewport.Create(pd, sh.Id, v.Id, XYZ(0, 0, 0))
                sheets.append(sh.Id)
            tx(pd, 'sheet', sheet)
            o = PDFExportOptions()
            o.FileName = 'e2e'
            o.Combine = True
            o.PaperFormat = ExportPaperFormat.ISO_A1
            o.PaperOrientation = PageOrientationType.Landscape
            o.ZoomType = ZoomType.FitToPage
            lines.append('pdf %s' % pd.Export(out_folder, List[ElementId](sheets), o))
    finally:
        pd.Close(False)
    return u'\n'.join(lines)
