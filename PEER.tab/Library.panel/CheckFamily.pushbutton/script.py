# -*- coding: utf-8 -*-
__title__ = "Check\nfamily"
__author__ = "Dima D"
__doc__ = """WHAT IT DOES
Checks a family while you make or fix it, before Publish or before a
bulk import - nothing in the family is changed:
- shared parameters against the company shared parameter file (the same
  name with another GUID gives two parameters in projects: schedules,
  tags and filters break);
- family parameters that should be the company's shared ones;
- every type regenerates;
- names that differ only in case or spaces, parameters nothing uses;
- nested shared families named like library families.

WHERE
- in the family editor: the open family;
- in a project: the family of the selected element or type;
- nothing selected: a whole folder of .rfa files (list saved as CSV).
"""

from pyrevit import forms, revit

from peer_library import config, family_check, log, strings


def selected_family(doc):
    from Autodesk.Revit import DB
    for e in revit.get_selection().elements:
        if isinstance(e, DB.Family):
            return e
        if isinstance(e, DB.FamilySymbol):
            return e.Family
        sym = getattr(e, 'Symbol', None)
        if isinstance(sym, DB.FamilySymbol):
            return sym.Family
    return None


def main():
    doc = revit.doc
    if doc is None:
        forms.alert(strings.NO_DOC, title=strings.APP)
        return
    app = doc.Application
    cfg = config.load()
    if doc.IsFamilyDocument:
        open_family(doc, app, cfg)
        return
    fam = selected_family(doc)
    if fam is not None:
        if not fam.IsEditable:
            forms.alert(strings.FCHECK_NOT_EDITABLE, title=strings.APP)
            return
        fd = doc.EditFamily(fam)
        try:
            rep = family_check.document_report(fd, cfg, app, fam.Name)
        finally:
            fd.Close(False)
        rep.fixes = []                          # fixing happens in the family editor
        rep.note = (rep.note + u'\n' if rep.note else u'') + strings.FIX_IN_EDITOR
        show(rep)
        return
    if not forms.alert(strings.FCHECK_PICK, title=strings.APP, yes=True, no=True):
        return
    folder = forms.pick_folder(title=strings.FCHECK_FOLDER)
    if not folder:
        return
    with forms.ProgressBar(title=strings.FCHECK_PROGRESS, cancellable=True) as pb:
        rep = family_check.folder_report(app, folder, cfg, _progress(pb))
    if show(rep) == 'fix':
        fix_folder(app, cfg, folder)


def _progress(pb):
    def progress(i, n):
        pb.update_progress(i, n)
        return not pb.cancelled
    return progress


def show(rep):
    from peer_library.ui_check import LoadCheckWindow
    w = LoadCheckWindow(rep)
    w.ShowDialog()
    return w.choice


def open_family(fd, app, cfg):
    """Family editor: check -> fix / change a parameter -> check again."""
    from peer_library import family_fix, ui_fix
    defs = None
    while True:
        rep = family_check.document_report(fd, cfg, app, fd.Title)
        rep.can_change = True
        choice = show(rep)
        if choice not in ('fix', 'change'):
            return
        if defs is None:
            defs = family_fix.definitions(app, rep.shared_path) if rep.shared_path else {}
        if choice == 'fix':
            ui_fix.show_results(family_fix.apply(fd, rep.fixes, defs))
        else:
            res = ui_fix.change_parameter(fd, defs)
            if res:
                ui_fix.show_results(res)


def fix_folder(app, cfg, folder):
    import os
    from peer_library import family_check as fc, family_fix
    out = forms.pick_folder(title=strings.FIX_OUT_FOLDER)
    if not out:
        return
    a, b = os.path.normcase(os.path.abspath(out)), os.path.normcase(os.path.abspath(folder))
    if a == b or a.startswith(b + os.sep):
        forms.alert(strings.FIX_SAME_FOLDER, title=strings.APP)
        return
    with forms.ProgressBar(title=strings.FCHECK_PROGRESS, cancellable=True) as pb:
        rows, saved = family_fix.fix_folder(app, folder, cfg, out, _progress(pb))
    csv = fc.write_csv(os.path.join(out, u'_family_fix.csv'), [(r[0], r[2], u'', r[1]) for r in rows])
    forms.alert(strings.FIX_FOLDER_DONE.format(saved, out, csv), title=strings.APP)


try:
    main()
except Exception as ex:
    log.write(u'check family', exc=True)
    forms.alert(u'{0}'.format(ex), title=strings.APP)
