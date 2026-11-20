# -*- coding: utf-8 -*-
"""Check of revit_draw in a blank project in the background (connector / dev):
synthetic groups -> drafting view -> PDF. Nothing in the open projects changes.

    from column_rebar.tests import revit_draw_check
    print(revit_draw_check.run(app, families_folder, out_folder))
"""

import clr
import os

from System.Collections.Generic import List
from Autodesk.Revit.DB import (ElementId, ExportPaperFormat, Family, FilteredElementCollector,
                               PageOrientationType, PDFExportOptions, UnitSystem, ViewDrafting,
                               ViewFamily, ViewFamilyType, Viewport, ViewSheet, XYZ, ZoomType)

from column_rebar import code466, revit_collect, revit_draw, slots
from column_rebar.family_build import run as tx_run

WORK = r'C:\Users\user\Desktop\Families Dima\04 Rebar\2D Rebar\Column Reiforcement (work)'
SHAPES = r'C:\Users\user\Desktop\Families Dima\04 Rebar\2D Rebar\Rebar shapes Family'


def groups():
    """(marks, shape, b, h, qb, qh, dia, extra) - qb / qh as the families keep them."""
    rows = [
        (['1', '2', '3', '4'], code466.RECT, 400, 400, 2, 2, 16, {}),
        (['5'], code466.RECT, 600, 600, 3, 3, 20, {}),
        (['6', '7'], code466.RECT, 800, 800, 2, 2, 25, {}),
        (['8', '9', '10', '12'], code466.RECT, 1500, 600, 5, 1, 20, {}),
        (['11'], code466.RECT, 1000, 1000, 5, 5, 20, {'transverse': 'ties'}),
        (['13', '14', '15'], code466.ROUND2, 500, 1250, 3, 6, 20, {}),
        (['16'], code466.ROUND1, 600, 1000, 3, 4, 20, {}),
        (['17', '18'], code466.ROUND1, 800, 1400, 5, 5, 25, {}),
        (['A1'], code466.RECT, 300, 300, 0, 0, 16, {}),
        (['20', '21', '22', '23', '24', '25', '26'], code466.RECT, 500, 700, 2, 3, 20, {'stirrup_dia': 10}),
    ]
    out = []
    for marks, shape, b, h, qb, qh, d, ex in rows:
        g = {'marks': marks, 'ids': [], 'shape': shape, 'b': float(b), 'h': float(h), 'qb': float(qb),
             'qh': float(qh), 'dia': float(d), 'cover': 25.0, 'stirrup_dia': None, 'spacing': None,
             'dense': None, 'transverse': 'auto'}
        g.update(ex)
        out.append(g)
    return out


def run(app, folder, out_folder, sheet_width_mm=14850.0):
    if not os.path.isdir(out_folder):
        os.makedirs(out_folder)
    pd = app.NewProjectDocument(UnitSystem.Metric)
    lines = []
    try:
        def load():
            files = [os.path.join(folder, n + u'.rfa') for n in revit_draw.SECTION_FAMILY.values()]
            files += [os.path.join(WORK, n) for n in (u'PEER_Rebar_Shape 52.rfa', u'PEER_Rebar_Shape 60.rfa',
                                                      u'PEER_Rebar_Shape 62.rfa', u'PR_Column Number.rfa')]
            files += [os.path.join(SHAPES, n) for n in (u'Detail items_Tag Rebar.rfa',
                                                        u'Detail items_Tag Rebar(Text Quantity).rfa')]
            for f in files:
                pd.LoadFamily(f, clr.Reference[Family]())
        lines.append('load %s' % (tx_run(pd, 'load', load)[1:],))
        types = revit_draw.find_types(pd)
        lines.append('missing types: %s' % types['missing'])
        gs = groups()
        results = [revit_collect.design(g) for g in gs]
        pos = revit_draw.pack(gs, results, sheet_width_mm)
        report = {'notes': []}
        vft = [v for v in FilteredElementCollector(pd).OfClass(ViewFamilyType) if v.ViewFamily == ViewFamily.Drafting][0]
        st = {}

        def draw():
            v = ViewDrafting.Create(pd, vft.Id)
            v.Name = 'Column 150'
            v.Scale = 25
            st['v'] = v
            revit_draw.activate(types)
            for g, r, p in zip(gs, results, pos):
                if not r['stirrup'] or not r['bars']:
                    report['notes'].append(u'%s: not drawn (%s)' % (u','.join(g['marks']),
                                           u', '.join(m['code'] for m in r['messages'])))
                    continue
                a = revit_collect.design_args(g)
                vals = slots.params(r, g['b'], g['h'], a['cover'], g['dia'], a['nb'], a['nh'], g['shape'])
                revit_draw.draw_group(pd, v, g, r, vals, p, types, report)
        res = tx_run(pd, 'draw', draw)
        lines.append('draw %s' % (res[1:],))
        lines += [u'note: ' + n for n in report['notes']]
        if 'v' in st and res[1] == 'Committed':
            sheets = []

            def sheet():
                sh = ViewSheet.Create(pd, ElementId.InvalidElementId)
                sh.SheetNumber = 'D01'
                Viewport.Create(pd, sh.Id, st['v'].Id, XYZ(0, 0, 0))
                sheets.append(sh.Id)
            tx_run(pd, 'sheet', sheet)
            o = PDFExportOptions()
            o.FileName = 'draw_check'
            o.Combine = True
            o.PaperFormat = ExportPaperFormat.ISO_A1
            o.PaperOrientation = PageOrientationType.Landscape
            o.ZoomType = ZoomType.FitToPage
            lines.append('pdf %s' % pd.Export(out_folder, List[ElementId](sheets), o))
    finally:
        pd.Close(False)
    return u'\n'.join(lines)
