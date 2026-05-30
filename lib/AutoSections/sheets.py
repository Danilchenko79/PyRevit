# -*- coding: utf-8 -*-
"""Lay the real section views out on sheets in a simple grid.

Model-side only - opens its own transaction. `per_sheet` views per sheet,
arranged on a near-square grid. Spacing is fixed; this is a quick layout, not a
scale-aware packing.
"""

import math

from Autodesk.Revit.DB import (
    Transaction, ViewSheet, Viewport, XYZ,
)

from AutoSections.convert import to_ft

SPACING = 450.0      # mm between viewport centres


def layout_on_sheets(doc, tb_id, views, per_sheet):
    """Place `views` on sheets, `per_sheet` each. Returns (placed, errors).

    `placed` is the list of created ViewSheet; `errors` collects per-sheet
    failures without aborting the rest.
    """
    placed, errors = [], []
    if not views:
        return placed, errors

    cols = int(math.ceil(math.sqrt(per_sheet)))
    spacing = to_ft(SPACING)

    t = Transaction(doc, 'AutoSections - Place sections on sheets')
    t.Start()
    try:
        chunk, sheet_no = [], 1
        for i, view in enumerate(views):
            chunk.append(view)
            if len(chunk) == per_sheet or i == len(views) - 1:
                try:
                    sheet = ViewSheet.Create(doc, tb_id)
                    sheet.Name = 'AUTO SECTIONS {:02d}'.format(sheet_no)
                    x0, y0 = spacing, cols * spacing
                    for j, v in enumerate(chunk):
                        r, c = j // cols, j % cols
                        pt = XYZ(x0 + c * spacing, y0 - r * spacing, 0)
                        if Viewport.CanAddViewToSheet(doc, sheet.Id, v.Id):
                            Viewport.Create(doc, sheet.Id, v.Id, pt)
                    placed.append(sheet)
                    sheet_no += 1
                except Exception as e:
                    errors.append('sheet: {}'.format(str(e)))
                chunk = []
        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise
    return placed, errors
