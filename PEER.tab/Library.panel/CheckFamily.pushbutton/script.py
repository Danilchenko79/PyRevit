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
        rep = family_check.document_report(doc, cfg, app, doc.Title)
    else:
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
        else:
            if not forms.alert(strings.FCHECK_PICK, title=strings.APP, yes=True, no=True):
                return
            folder = forms.pick_folder(title=strings.FCHECK_FOLDER)
            if not folder:
                return
            with forms.ProgressBar(title=strings.FCHECK_PROGRESS, cancellable=True) as pb:
                def progress(i, n):
                    pb.update_progress(i, n)
                    return not pb.cancelled
                rep = family_check.folder_report(app, folder, cfg, progress)
    from peer_library.ui_check import LoadCheckWindow
    LoadCheckWindow(rep).ShowDialog()


try:
    main()
except Exception as ex:
    log.write(u'check family', exc=True)
    forms.alert(u'{0}'.format(ex), title=strings.APP)
