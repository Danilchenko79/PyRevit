# -*- coding: utf-8 -*-
"""Columns -> groups (table rows) and their marks. Pure Python, millimetres.

A group is every column with the same shape, size and reinforcement. One
column with another value is its own group - a new row in the table.
"""

from column_rebar import rules

# Width a mark symbol (PR_Column Number) takes on the view, model mm at 1:25.
MARK_WIDTH = 210.0
RANGE_WIDTH = 500.0
MARKS_PER_ROW = 5
RANGES_PER_ROW = 2


def mark_sort_key(mark):
    """Numbers first by value, then the other marks by text."""
    s = u'{0}'.format(mark).strip()
    if s.isdigit():
        return (0, int(s), u'')
    return (1, 0, s)


def sorted_marks(marks):
    return sorted(marks, key=mark_sort_key)


def valid_mark(mark):
    """The mark as text, or None when the column has none ('', 'N/A')."""
    s = (mark or u'').strip()
    return s if s and s != u'N/A' else None


def marks_and_ranges(marks):
    """[{num, num2, num_plus, width}] for the mark symbols.

    3 or more numbers in a row are one range symbol (num - num2);
    the rest one symbol each; marks that are not numbers go last."""
    nums, others = [], []
    for m in marks:
        s = u'{0}'.format(m).strip()
        if s.isdigit():
            nums.append(int(s))
        else:
            others.append(s)
    nums = sorted(set(nums))
    out, i = [], 0
    while i < len(nums):
        seq = [nums[i]]
        while i + 1 < len(nums) and nums[i + 1] == nums[i] + 1:
            i += 1
            seq.append(nums[i])
        if len(seq) >= 3:
            out.append({'num': str(seq[0]), 'num2': str(seq[-1]),
                        'num_plus': True, 'width': RANGE_WIDTH})
        else:
            for n in seq:
                out.append({'num': str(n), 'num2': None,
                            'num_plus': False, 'width': MARK_WIDTH})
        i += 1
    for m in sorted(set(others)):
        out.append({'num': m, 'num2': None, 'num_plus': False, 'width': MARK_WIDTH})
    return out


def mark_rows(items):
    """The mark symbols split into rows: 5 in a row, and a range starts a
    new row once the row already has 2 symbols."""
    rows, row = [], []
    for it in items:
        if len(row) >= MARKS_PER_ROW or (len(row) >= RANGES_PER_ROW and it['num_plus']):
            rows.append(row)
            row = []
        row.append(it)
    if row:
        rows.append(row)
    return rows


def group_key(c):
    """Columns with the same key are one group. Sizes to 0.1 mm, so the
    float noise of a unit conversion does not split a group."""
    return (c['shape'], round(c['b'], 1), round(c['h'], 1),
            int(round(c['qb'])), int(round(c['qh'])), round(c['dia'], 1)) + extra_key(c)


# Item 9: what the 3D column carries besides the bars - a column with another
# value is another row (decision A).
EXTRA = ('cover', 'stirrup_dia', 'spacing', 'dense', 'transverse')


def extra_key(c):
    out = []
    for k in EXTRA:
        v = c.get(k)
        out.append(round(v, 1) if isinstance(v, float) else v)
    return tuple(out)


def group_sort_key(g):
    """Table and drawing order: by shape, then bigger section first."""
    return (rules.SHAPE_ORDER.get(g['shape'], 99), -g['b'] * g['h'],
            -(g['qb'] + g['qh']), -g['dia'])


def make_groups(columns):
    """(groups, no_mark) from columns {id, mark, shape, b, h, qb, qh, dia}.

    groups   [{shape, b, h, qb, qh, dia, marks, ids}] in table order
    no_mark  ids of the columns without a mark (they are in no group)"""
    by_key, order, no_mark = {}, [], []
    for c in columns:
        mark = valid_mark(c.get('mark'))
        if mark is None:
            no_mark.append(c['id'])
            continue
        k = group_key(c)
        g = by_key.get(k)
        if g is None:
            g = by_key[k] = {'shape': c['shape'], 'b': c['b'], 'h': c['h'],
                             'qb': int(round(c['qb'])), 'qh': int(round(c['qh'])),
                             'dia': c['dia'], 'marks': [], 'ids': []}
            for f_ in EXTRA:                 # not k: k is the group key here
                g[f_] = c.get(f_)
            order.append(k)
        g['marks'].append(mark)
        g['ids'].append(c['id'])
    groups = [by_key[k] for k in order]
    groups.sort(key=group_sort_key)
    return groups, no_mark


def merge_groups(groups):
    """Rows that ended up equal (after a split in the table) are one group again."""
    by_key, order = {}, []
    for g in groups:
        k = group_key(g)
        if k in by_key:
            by_key[k]['marks'].extend(g['marks'])
            by_key[k]['ids'].extend(g['ids'])
        else:
            n = dict(g)
            n['marks'], n['ids'] = list(g['marks']), list(g['ids'])
            by_key[k] = n
            order.append(k)
    out = [by_key[k] for k in order]
    out.sort(key=group_sort_key)
    return out


def split_group(groups, idx):
    """Group idx as one row per mark; the other rows stay."""
    out = []
    for i, g in enumerate(groups):
        if i != idx or len(g['marks']) < 2:
            out.append(g)
            continue
        for mark, cid in sorted(zip(g['marks'], g['ids']),
                                key=lambda p: mark_sort_key(p[0])):
            n = dict(g)
            n['marks'], n['ids'] = [mark], [cid]
            out.append(n)
    return out


def duplicate_marks(columns):
    """{mark: [ids]} of the marks used by more than one column."""
    seen = {}
    for c in columns:
        mark = valid_mark(c.get('mark'))
        if mark is not None:
            seen.setdefault(mark, []).append(c['id'])
    return dict((m, ids) for m, ids in seen.items() if len(ids) > 1)
