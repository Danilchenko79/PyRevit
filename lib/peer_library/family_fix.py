# -*- coding: utf-8 -*-
"""Put a family's parameters in order (Revit only; the plan is family_diff.fix_plan).

    to_shared(fd, name, ext)      family parameter -> company shared parameter
    rename_shared(fd, name, ext)  shared parameter, old name -> company name, same GUID
    to_family(fd, name, new)      shared parameter -> plain family parameter
    rename(fd, name, new)         family parameter -> new name
    remove(fd, name)
Formulas, dimension labels and element associations stay (ReplaceParameter).

Checked in Revit 2024 (20.11.2026, copies of PEER-Library-Source):
- ReplaceParameter(family -> shared) with the same name fails ("Parameter
  replacement failed") - rename the family parameter first;
- shared -> shared with the same GUID and another name: shared -> family,
  delete the SharedParameterElement of that GUID (the document remembers the
  old name and gives it back), then family -> shared.
"""

import os
import shutil
import uuid

from Autodesk.Revit import DB

from peer_library import family_diff as D
from peer_library import family_check, log
from peer_library.revit_family import Guard, QuietOpen


def definitions(app, path):
    """{guid: ExternalDefinition} of a shared parameter file. Revit opens only
    the file set in the application, so it is switched for the moment."""
    old = app.SharedParametersFilename
    try:
        if path and os.path.normcase(path) != os.path.normcase(old or u''):
            app.SharedParametersFilename = path
        f = app.OpenSharedParameterFile()
        out = {}
        if f is not None:
            for g in f.Groups:
                for d in g.Definitions:
                    out[u'{0}'.format(d.GUID).lower()] = d
        return out
    finally:
        if (old or u'') != (app.SharedParametersFilename or u''):
            app.SharedParametersFilename = old


def _eid(element_id):
    v = getattr(element_id, 'Value', None)
    return int(v) if v is not None else element_id.IntegerValue


def _param(fm, name):
    for p in fm.GetParameters():
        if p.Definition.Name == name:
            return p
    return None


def _group(p):
    try:
        g = p.Definition.GetGroupTypeId()
        if g is not None and g.TypeId:
            return g
    except Exception:
        pass
    return DB.GroupTypeId.General


def _free_name(fm, base):
    names = set(p.Definition.Name for p in fm.GetParameters())
    name = base
    while name in names:
        name = u'{0}_{1}'.format(base, uuid.uuid4().hex[:4])
    return name


def to_shared(fd, name, ext):
    fm = fd.FamilyManager
    p = _param(fm, name)
    grp, inst = _group(p), p.IsInstance
    if ext.Name == name:
        fm.RenameParameter(p, _free_name(fm, name + u'__old'))
    return fm.ReplaceParameter(p, ext, grp, inst)


def to_family(fd, name, new_name):
    fm = fd.FamilyManager
    p = _param(fm, name)
    grp, inst, guid = _group(p), p.IsInstance, p.GUID
    tmp = fm.ReplaceParameter(p, _free_name(fm, u'PEER_tmp'), grp, inst)
    spe = DB.SharedParameterElement.Lookup(fd, guid)
    if spe is not None:
        fd.Delete(spe.Id)
    fm.RenameParameter(tmp, new_name)
    return tmp


def rename_shared(fd, name, ext):
    fm = fd.FamilyManager
    p = _param(fm, name)
    grp, inst = _group(p), p.IsInstance
    tmp = fm.ReplaceParameter(p, _free_name(fm, u'PEER_tmp'), grp, inst)
    spe = DB.SharedParameterElement.Lookup(fd, ext.GUID)
    if spe is not None:
        fd.Delete(spe.Id)                 # else Revit gives the old name back
    return fm.ReplaceParameter(tmp, ext, grp, inst)


def rename(fd, name, new_name):
    fm = fd.FamilyManager
    fm.RenameParameter(_param(fm, name), new_name)


def remove(fd, name):
    fm = fd.FamilyManager
    fm.RemoveParameter(_param(fm, name))


def run_one(fd, label, fn):
    """fn() in its own guarded transaction. Returns None or the error text."""
    Guard.last_errors = []
    tx = DB.Transaction(fd, u'PEER: {0}'.format(label)[:80])
    o = tx.GetFailureHandlingOptions()
    o.SetFailuresPreprocessor(Guard())
    o.SetClearAfterRollback(True)
    tx.SetFailureHandlingOptions(o)
    tx.Start()
    err = None
    try:
        fn()
        tx.Commit()
    except Exception as ex:
        err = u'{0}'.format(getattr(ex, 'Message', None) or ex)
    finally:
        if tx.HasStarted() and not tx.HasEnded():
            tx.RollBack()
    if err is None and tx.GetStatus() != DB.TransactionStatus.Committed:
        err = u'; '.join(Guard.last_errors[:1]) or u'rolled back'
    return err


def apply(fd, actions, defs):
    """Runs the actions one by one (one Undo for all in the family editor).
    Returns [(action, None | error text)]."""
    out = []
    tg = DB.TransactionGroup(fd, u'PEER: fix family parameters')
    tg.Start()
    try:
        for a in actions:
            op, name = a['op'], a['name']
            ext = defs.get(a.get('guid') or u'')
            if op in ('to_shared', 'rename_shared') and ext is None:
                out.append((a, u'not in the shared parameter file'))
                continue
            fn = {'to_shared': lambda: to_shared(fd, name, ext),
                  'rename_shared': lambda: rename_shared(fd, name, ext),
                  'to_family': lambda: to_family(fd, name, a['new']),
                  'rename': lambda: rename(fd, name, a['new']),
                  'remove': lambda: remove(fd, name)}.get(op)
            out.append((a, run_one(fd, a.get('text') or op, fn) if fn else u'unknown action'))
    finally:
        if tg.HasStarted() and not tg.HasEnded():
            tg.Assimilate()               # transactions above are all closed
    return out


def fix_folder(app, folder, cfg, out_folder, progress=None, remove_unused=False):
    """Fixed copies of every family under folder that has something to fix,
    same sub-folders, in out_folder (the sources are never written). Returns
    (rows [(file, action text, 'ok' | error)], number of files saved)."""
    shared, spath = family_check.shared_file(app, cfg)
    if not shared:
        raise Exception(u'No company shared parameter file: {0}'.format(spath or u'-'))
    defs = definitions(app, spath)
    files = family_check.family_files(folder)
    rows, saved = [], 0
    from peer_library import family_sig
    for i, path in enumerate(files):
        if progress is not None and progress(i, len(files)) is False:
            break
        rel = os.path.relpath(path, folder)
        fd = None
        try:
            with QuietOpen(app):
                fd = app.OpenDocumentFile(path)
            acts = D.fix_plan(family_sig.signature(fd), shared, remove_unused)
            if not acts:
                continue
            res = apply(fd, acts, defs)
            for a, err in res:
                rows.append((rel, a['text'], err or u'ok'))
            if any(err is None for a, err in res):
                target = os.path.join(out_folder, rel)
                if not os.path.isdir(os.path.dirname(target)):
                    os.makedirs(os.path.dirname(target))
                so = DB.SaveAsOptions()
                so.OverwriteExistingFile = True
                so.MaximumBackups = 1
                fd.SaveAs(target, so)
                saved += 1
        except Exception as ex:
            log.write(u'fix {0}'.format(path), exc=True)
            rows.append((rel, u'-', u'{0}'.format(ex)))
        finally:
            if fd is not None:
                try:
                    fd.Close(False)
                except Exception:
                    log.write(u'close {0}'.format(path), exc=True)
    for root, dirs, fs in os.walk(out_folder):
        for f in fs:
            if family_check._is_backup(f):
                try:
                    os.remove(os.path.join(root, f))
                except OSError:
                    pass
    return rows, saved
