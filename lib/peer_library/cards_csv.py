# -*- coding: utf-8 -*-
"""Card info <-> CSV for editing many families in Excel (admin).

export(cards, path): id, name, group, tags (separated by ';'), description,
help_url, revit_category (read only), version (read only). UTF-8 with BOM -
Excel opens Hebrew / Russian correctly.
changes(cards, path): [{'id', 'fields'}] - only fields that differ; unknown
IDs and bad groups are reported, not applied.
py2/py3 neutral (no csv module: IronPython's csv does not handle unicode).
"""

import io

from peer_library import groups
from peer_library.catalog import _cells

COLUMNS = ['id', 'name', 'group', 'tags', 'description', 'help_url', 'revit_category', 'version']
EDITABLE = ('name', 'group', 'tags', 'description', 'help_url')


def _q(value):
    text = u'{0}'.format(value if value is not None else u'')
    text = text.replace(u'\r\n', u' / ').replace(u'\n', u' / ').replace(u'\r', u' ')
    if any(ch in text for ch in u',"') or text != text.strip():
        text = u'"' + text.replace(u'"', u'""') + u'"'
    return text


def export(cards, path):
    lines = [u','.join(COLUMNS)]
    for c in sorted(cards, key=lambda x: (x.get('group') or u'', x['id'].lower())):
        row = [c['id'], c.get('name') or u'', c.get('group') or u'',
               u'; '.join(c.get('tags') or []), c.get('description') or u'',
               c.get('help_url') or u'', c.get('revit_category') or u'', c.get('version') or u'']
        lines.append(u','.join(_q(v) for v in row))
    with io.open(path, 'w', encoding='utf-8-sig', newline=u'') as f:
        f.write(u'\r\n'.join(lines) + u'\r\n')
    return len(lines) - 1


def _read(path):
    with io.open(path, 'r', encoding='utf-8-sig') as f:
        text = f.read()
    rows = [_cells(line) for line in text.splitlines() if line.strip()]
    if not rows:
        return []
    head = [h.strip().lower() for h in rows[0]]
    if head[:1] != ['id']:
        # Excel in some locales saves with ';' - try that
        rows = [[c.strip() for c in line.split(u';')] for line in text.splitlines() if line.strip()]
        head = [h.strip().lower() for h in rows[0]]
    out = []
    for r in rows[1:]:
        out.append(dict((head[i], r[i] if i < len(r) else u'') for i in range(len(head))))
    return out


def changes(cards, path):
    """(changes, problems)."""
    by_id = dict((c['id'], c) for c in cards)
    out, problems = [], []
    for row in _read(path):
        fid = (row.get('id') or u'').strip()
        if not fid:
            continue
        card = by_id.get(fid)
        if card is None:
            problems.append(u'{0}: not in the library'.format(fid))
            continue
        fields = {}
        for k in EDITABLE:
            if k not in row:
                continue
            new = row[k].strip()
            if k == 'tags':
                new_tags = [t.strip() for t in new.replace(u',', u';').split(u';') if t.strip()]
                if new_tags != list(card.get('tags') or []):
                    fields['tags'] = new_tags
                continue
            if k == 'group' and new not in groups.GROUP_IDS:
                problems.append(u'{0}: unknown group "{1}"'.format(fid, new))
                continue
            if k == 'name' and not new:
                problems.append(u'{0}: empty name'.format(fid))
                continue
            if new != (card.get(k) or u''):
                fields[k] = new
        if fields:
            out.append({'id': fid, 'fields': fields})
    return out, problems
