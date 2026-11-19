# -*- coding: utf-8 -*-
"""What the script adds to a request by itself. Revit only.

Only names are sent - project title, view name, element categories - never
file paths, geometry or parameter values of the client's model.
Every field is collected separately: one failing field never stops a send.
"""

from peer_feedback import config, payload


def _try(fn, default=u''):
    try:
        v = fn()
        return default if v is None else v
    except Exception:
        return default


def _revit_version(app):
    num = _try(lambda: app.VersionNumber)
    sub = _try(lambda: app.SubVersionNumber)   # 2023.1.2 etc.
    build = _try(lambda: app.VersionBuild)
    v = sub or num
    return u'{0} ({1})'.format(v, build) if build else payload.u(v)


def _pyrevit_version():
    try:
        from pyrevit.versionmgr import get_pyrevit_version
        return get_pyrevit_version().get_formatted()
    except Exception:
        return u''


def _selection(uidoc, doc, limit=10):
    """'Walls x3, Floors x1' - categories of the selected elements."""
    ids = list(uidoc.Selection.GetElementIds())
    if not ids:
        return u''
    counts = {}
    for eid in ids:
        el = doc.GetElement(eid)
        cat = _try(lambda: el.Category.Name) if el is not None else u''
        cat = cat or u'(no category)'
        counts[cat] = counts.get(cat, 0) + 1
    parts = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    text = u', '.join(u'{0} x{1}'.format(k, n) for k, n in parts[:limit])
    if len(parts) > limit:
        text += u', ...'
    return text


def _view(doc):
    v = doc.ActiveView
    if v is None:
        return u''
    return u'{0} ({1})'.format(v.Name, v.ViewType)


def collect(uiapp, error_script=u'', error_text=u''):
    """-> dict with payload.CONTEXT_FIELDS."""
    from System import Environment
    app = uiapp.Application
    uidoc = _try(lambda: uiapp.ActiveUIDocument, None)
    doc = _try(lambda: uidoc.Document, None) if uidoc is not None else None
    ctx = {
        'user': _try(lambda: app.Username) or _try(lambda: Environment.UserName),
        'machine': _try(lambda: Environment.MachineName),
        'project': _try(lambda: doc.Title) if doc is not None else u'',
        'revit_version': _try(lambda: _revit_version(app)),
        'pyrevit_version': _pyrevit_version(),
        'peer_version': config.peer_version(),
        'view': _try(lambda: _view(doc)) if doc is not None else u'',
        'selection': _try(lambda: _selection(uidoc, doc)) if doc is not None else u'',
        'error_script': error_script,
        'error_text': error_text,
    }
    win_user = _try(lambda: Environment.UserName)
    if win_user and win_user != ctx['user']:
        ctx['user'] = u'{0} ({1})'.format(ctx['user'], win_user)
    return dict((k, payload.u(v)) for k, v in ctx.items())


def describe(ctx):
    """Lines shown in the window: what will be attached (no surprises)."""
    rows = [
        (u'User', ctx.get('user')), (u'Computer', ctx.get('machine')),
        (u'Project', ctx.get('project')), (u'View', ctx.get('view')),
        (u'Selection', ctx.get('selection')),
        (u'Revit', ctx.get('revit_version')),
        (u'pyRevit', ctx.get('pyrevit_version')),
        (u'PEER', ctx.get('peer_version')),
    ]
    return u'\n'.join(u'{0}: {1}'.format(k, v) for k, v in rows if v)
