# -*- coding: utf-8 -*-
"""Template passport: what is inside a project template, as data - and the
readable difference between two versions (pure Python, tested without Revit).

A passport is {section: {item name: {field: value}}}, for example
    {"view_templates": {"PEER GR": {"scale": 50, "detail": "Fine", "filters": ["Bx", "By"]}},
     "filters":        {"Bx": {"categories": ["Rebar"], "rules": "PR_Set_HE != B"}},
     "families":       {"PR_Tag Rebar": {"category": "Structural Rebar Tags", "version": 3}},
     "rebar_shapes":   {"21E": {"hooks": "0/0"}},
     "line_styles":    {...}, "project_parameters": {...}, "schedules": {...}}
The Revit side (which collects it from a .rte) writes it to JSON; the JSON
lives in git, so every template version has a text history.
"""

SECTION_TITLES = [
    ('view_templates', u'View templates'),
    ('filters', u'Filters'),
    ('families', u'Families'),
    ('rebar_shapes', u'Rebar shapes'),
    ('rebar_types', u'Rebar bar types'),
    ('schedules', u'Schedules'),
    ('project_parameters', u'Project parameters'),
    ('line_styles', u'Line styles'),
    ('fill_patterns', u'Fill patterns'),
    ('text_types', u'Text types'),
    ('dimension_types', u'Dimension types'),
    ('sheets', u'Sheets'),
    ('views', u'Views'),
]


def _show(v):
    if isinstance(v, (list, tuple)):
        return u', '.join(u'{0}'.format(x) for x in v) or u'-'
    if v is None or v == u'':
        return u'-'
    if v is True:
        return u'yes'
    if v is False:
        return u'no'
    return u'{0}'.format(v)


def _list_change(old, new):
    """'+ a, b; - c' for two lists compared as sets (order changes ignored)."""
    o, n = [u'{0}'.format(x) for x in old], [u'{0}'.format(x) for x in new]
    add = [x for x in n if x not in o]
    gone = [x for x in o if x not in n]
    parts = []
    if add:
        parts.append(u'added ' + u', '.join(add))
    if gone:
        parts.append(u'removed ' + u', '.join(gone))
    return u'; '.join(parts)


def diff(old, new):
    """[(section key, kind, item, [detail lines])], kind: added / removed / changed.
    Sections in SECTION_TITLES order, unknown sections after them, items by name."""
    old, new = old or {}, new or {}
    order = [k for k, _ in SECTION_TITLES]
    keys = [k for k in order if k in old or k in new] + \
        sorted(k for k in set(old) | set(new) if k not in order)
    out = []
    for sec in keys:
        a, b = old.get(sec) or {}, new.get(sec) or {}
        if not isinstance(a, dict) or not isinstance(b, dict):
            continue
        for name in sorted(set(a) | set(b), key=lambda s: s.lower()):
            if name not in a:
                out.append((sec, 'added', name, []))
            elif name not in b:
                out.append((sec, 'removed', name, []))
            else:
                x, y = a[name] or {}, b[name] or {}
                if not isinstance(x, dict) or not isinstance(y, dict):
                    if x != y:
                        out.append((sec, 'changed', name, [u'{0} -> {1}'.format(_show(x), _show(y))]))
                    continue
                lines = []
                for f in sorted(set(x) | set(y)):
                    p, q = x.get(f), y.get(f)
                    if p == q:
                        continue
                    if isinstance(p, (list, tuple)) and isinstance(q, (list, tuple)):
                        ch = _list_change(p, q)
                        if ch:
                            lines.append(u'{0}: {1}'.format(f, ch))
                    else:
                        lines.append(u'{0}: {1} -> {2}'.format(f, _show(p), _show(q)))
                if lines:
                    out.append((sec, 'changed', name, lines))
    return out


def title(section):
    return dict(SECTION_TITLES).get(section) or section.replace(u'_', u' ').capitalize()


def text(changes, limit=None):
    """Readable change list (Markdown) - the draft of the release note."""
    if not changes:
        return u'No differences.'
    lines, last = [], None
    shown = changes if limit is None else changes[:limit]
    for sec, kind, name, details in shown:
        if sec != last:
            if lines:
                lines.append(u'')
            lines.append(u'**{0}**'.format(title(sec)))
            last = sec
        mark = {'added': u'+', 'removed': u'-', 'changed': u'~'}[kind]
        lines.append(u'{0} {1}{2}'.format(mark, name, (u': ' + u'; '.join(details)) if details else u''))
    if limit is not None and len(changes) > limit:
        lines.append(u'')
        lines.append(u'... and {0} more'.format(len(changes) - limit))
    return u'\n'.join(lines)


def summary(changes):
    """'3 added, 1 removed, 5 changed'"""
    n = {'added': 0, 'removed': 0, 'changed': 0}
    for c in changes:
        n[c[1]] += 1
    return u', '.join(u'{0} {1}'.format(n[k], k) for k in ('added', 'removed', 'changed') if n[k]) or u'no differences'


def outdated_families(pp, cards):
    """Families of the template older than the library, or not from it:
    [(name, template version or None, library version or None)]. cards: {id.lower(): card}."""
    out = []
    for name, info in sorted(((pp or {}).get('families') or {}).items(), key=lambda kv: kv[0].lower()):
        card = (cards or {}).get(name.lower())
        tv = (info or {}).get('version') if isinstance(info, dict) else None
        if card is None:
            continue
        lv = card.get('version')
        if tv is None or (lv is not None and tv < lv):
            out.append((name, tv, lv))
    return out
