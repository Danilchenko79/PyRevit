# -*- coding: utf-8 -*-
"""Where each section goes on the drafting view. Pure Python, millimetres.

The old script stepped a fixed 2 m between sections, so the stirrup, ties
and tags of a wide section ran into the next one. Here every section has
its real extent around the insertion point (bottom left corner of the
concrete), and the rows are packed by it.

The offsets below are the ones the drawing code uses; keep them together.
"""

from column_rebar import grouping, rules

STIRRUP_CENTER_FACTOR = 1.5     # stirrup centre at x = 1.5 * B
TIE_OFFSET = 550.0              # vertical tie right of the stirrup
TIE_TAG_OFFSET = 200.0
TAG_WIDTH = 900.0               # room for a rebar tag text
TAG_HEIGHT = 150.0
H_TIE_OFFSET = 220.0            # horizontal tie above the section
H_TIE_TAG_OFFSET = 220.0
DIM_OFFSET = 152.4              # dimension lines left of / below the section
TITLE_DROP = 365.8              # section title below the bottom edge
MARKS_DROP = 55.0               # first row of marks below the title
MARK_ROW_STEP = 210.0
MARK_START = 210.0              # first mark symbol left of the left edge
GAP = 300.0                     # clear gap between neighbours


def section_extent(b, h, transverse, marks):
    """{left, right, down, up}: how far the drawing of one section reaches
    from its insertion point (all positive)."""
    right = b
    up = h + TAG_HEIGHT                       # section tag at the top right corner
    stirrup_right = b
    for t in transverse:
        if t['kind'] == rules.STIRRUP:
            stirrup_right = STIRRUP_CENTER_FACTOR * b + t['a'] / 2.0
            right = max(right, stirrup_right, STIRRUP_CENTER_FACTOR * b + 300.0 + TAG_WIDTH)
    stirrup_a = max([t['a'] for t in transverse if t['kind'] == rules.STIRRUP] or [b])
    for t in transverse:
        if t['kind'] != rules.TIE:
            continue
        if t['direction'] == rules.VERTICAL:
            x = STIRRUP_CENTER_FACTOR * b + TIE_OFFSET + stirrup_a / 2.0
            right = max(right, x + TIE_TAG_OFFSET + TAG_WIDTH)
        else:
            up = max(up, h + H_TIE_OFFSET + H_TIE_TAG_OFFSET + TAG_HEIGHT)
            right = max(right, b / 2.0 + TAG_WIDTH / 2.0)
    rows = grouping.mark_rows(grouping.marks_and_ranges(marks))
    left = DIM_OFFSET
    for row in rows:
        left = max(left, MARK_START + sum(it['width'] for it in row))
    down = TITLE_DROP + MARKS_DROP + MARK_ROW_STEP * max(1, len(rows))
    return {'left': left, 'right': right, 'down': down, 'up': up}


def pack(extents, max_width, gap=GAP):
    """[(x, y)] insertion points for sections with these extents.

    Left to right, a new row when the next one does not fit in max_width
    (one section wider than max_width still gets a row of its own).
    The first row hangs from y = 0 downwards; rows do not overlap."""
    rows, row, used = [], [], 0.0
    for i, e in enumerate(extents):
        w = e['left'] + e['right']
        if row and used + gap + w > max_width:
            rows.append(row)
            row, used = [], 0.0
        used += (gap if row else 0.0) + w
        row.append(i)
    if row:
        rows.append(row)
    out = [None] * len(extents)
    top = 0.0
    for row in rows:
        up = max(extents[i]['up'] for i in row)
        down = max(extents[i]['down'] for i in row)
        y = top - up
        x = 0.0
        for i in row:
            e = extents[i]
            out[i] = (x + e['left'], y)
            x += e['left'] + e['right'] + gap
        top = y - down - gap
    return out
