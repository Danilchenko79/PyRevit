# -*- coding: utf-8 -*-
"""Before a family that is already in the project is replaced: what breaks.

check(doc, path, family_id, ...) -> Report
    1. parameters of the family in the project vs the library file
       (names, shared GUIDs, instance/type, units, category, nested shared
       families, shared parameters already in the project);
    2. trial load: the real load inside a transaction group that is rolled
       back - dimensions / tags / elements Revit would delete, parameter
       values that would be lost or changed, Revit's warnings and errors.
Nothing in the project changes. Revit only; the rules are in family_diff.
"""

import os
import tempfile

import clr
from Autodesk.Revit import DB

from peer_library import family_diff as D
from peer_library import family_sig, loader, log, strings
from peer_library.revit_family import Guard

MAX_VALUES = 3000            # elements whose parameter values are compared


class Report(object):
    """kind 'update' - replacing a family in a project (load_check.check);
    kind 'family' - the Check Family button (summary / note: free text)."""

    def __init__(self, family_id, findings, trial=None, not_library=False, kind='update',
                 summary=u'', note=u''):
        self.family_id = family_id
        self.findings = D.ordered(findings)
        self.trial = trial
        self.not_library = not_library
        self.kind = kind
        self.summary = summary
        self.note = note
        self.project_png = None
        self.library_png = None

    @property
    def level(self):
        return D.worst(self.findings)

    @property
    def blocking(self):
        return self.level == D.ERROR

    @property
    def needs_look(self):
        """Ask the person before loading: errors, warnings, or a family that
        did not come from the library (the drawing itself may differ)."""
        return self.not_library or self.level in (D.ERROR, D.WARNING)

    def first_problem(self):
        for lv, code, text in self.findings:
            if lv in (D.ERROR, D.WARNING):
                return text
        return u''

    def text(self):
        lines = [u'{0}: {1}'.format(self.family_id, verdict(self))]
        s = self.summary or D.trial_summary(self.trial)
        if s:
            lines.append(s)
        for lv, code, t in self.findings:
            lines.append(u'[{0}] {1}'.format(lv, t))
        if self.note:
            lines.append(self.note)
        return u'\n'.join(lines)


def verdict(report):
    lv = report.level
    if report.kind == 'family':
        return {D.ERROR: strings.FCHECK_ERRORS, D.WARNING: strings.FCHECK_WARNINGS}.get(
            lv, strings.FCHECK_CLEAN)
    if lv == D.ERROR:
        return strings.CHECK_BREAKS
    if lv == D.WARNING:
        return strings.CHECK_WARNINGS
    return strings.CHECK_CLEAN


def check(doc, path, family_id, type_names=None, overwrite=False, not_library=False,
          previews_to=None):
    """Report, or None when the family is not in the project."""
    fam = loader.find_family(doc, family_id)
    if fam is None:
        return None
    findings = []
    png = None
    if previews_to:
        if not os.path.isdir(previews_to):
            os.makedirs(previews_to)
        png = os.path.join(previews_to, u'project_{0}.png'.format(_eid(fam.Id)))
    psig = family_sig.project_signature(doc, fam, png)
    try:
        lsig = family_sig.file_signature(doc.Application, path)
    except Exception as ex:
        log.write(u'library signature {0}'.format(family_id), exc=True)
        lsig = None
        findings.append((D.WARNING, 'no_library_sig', strings.CHECK_NO_FILE.format(ex)))
    if lsig is not None and type_names:
        lsig['types'] = list(type_names)          # a catalog loads only the ticked types
    if psig is None:
        findings.append((D.INFO, 'no_project_sig', strings.CHECK_NOT_EDITABLE))
    if psig is not None and lsig is not None:
        findings.extend(D.compare(psig, lsig, family_sig.project_shared(doc),
                                  set(loader.project_families(doc))))
    trial = trial_load(doc, path, family_id, type_names, overwrite)
    findings = D.soften(findings, trial) + D.trial_findings(trial, overwrite)
    if not_library:
        findings.append((D.WARNING, 'not_library', strings.CHECK_NOT_LIBRARY))
    rep = Report(family_id, findings, trial, not_library)
    rep.project_png = (psig or {}).get('preview')
    return rep


# ---- trial load ----------------------------------------------------------------
def _eid(element_id):
    v = getattr(element_id, 'Value', None)
    return int(v) if v is not None else element_id.IntegerValue


def _val(p):
    if not p.HasValue:
        return None
    st = p.StorageType
    if st == DB.StorageType.Double:
        return round(p.AsDouble(), 9)
    if st == DB.StorageType.Integer:
        return p.AsInteger()
    if st == DB.StorageType.String:
        return p.AsString() or None
    if st == DB.StorageType.ElementId:
        return u'{0}'.format(p.AsElementId())
    return None


def _values(element):
    """{name: (guid, value)} of the non-built-in parameters (family, shared,
    project parameters) of one element."""
    out = {}
    for p in element.Parameters:
        try:
            if _eid(p.Id) < 0:
                continue
            g = u''
            if p.IsShared:
                g = u'{0}'.format(p.GUID).lower()
            out[p.Definition.Name] = (g, _val(p))
        except Exception:
            pass
    return out


def _ids(doc, cls):
    return set(_eid(i) for i in DB.FilteredElementCollector(doc).OfClass(cls).ToElementIds())


def trial_load(doc, path, family_id, type_names=None, overwrite=False):
    """The load inside a TransactionGroup that is always rolled back.
    Returns the dict family_diff.trial_findings reads."""
    fam = loader.find_family(doc, family_id)
    if fam is None:
        return None
    sym_ids = list(fam.GetFamilySymbolIds())
    inst_ids = []
    for sid in sym_ids:
        inst_ids.extend(DB.FilteredElementCollector(doc)
                        .WherePasses(DB.FamilyInstanceFilter(doc, sid)).ToElementIds())
    sym_set = set(_eid(i) for i in sym_ids)
    inst_set = set(_eid(i) for i in inst_ids)
    watch = list(sym_ids) + list(inst_ids)[:MAX_VALUES]
    before = {}
    for i in watch:
        e = doc.GetElement(i)
        if e is not None:
            before[_eid(i)] = (i, _values(e))
    dims, tags = _ids(doc, DB.Dimension), _ids(doc, DB.IndependentTag)
    # what else could go: visible elements that depend on the family. A reload
    # also deletes and recreates hundreds of hidden family internals (and the
    # Family element itself when the file is another family) - not reported.
    deps = {}
    try:
        for i in fam.GetDependentElements(None):
            k = _eid(i)
            if k in sym_set or k in inst_set or k in dims or k in tags:
                continue
            e = doc.GetElement(i)
            if e is None or isinstance(e, (DB.Family, DB.ElementType)) or e.Category is None:
                continue
            deps[k] = e.Category.Name
    except Exception:
        log.write(u'dependents {0}'.format(family_id), exc=True)
    deleted = []

    def on_changed(sender, args):
        try:
            if args.GetDocument().Equals(doc):
                deleted.extend(_eid(x) for x in args.GetDeletedElementIds())
        except Exception:
            pass

    res = {'failed': [], 'warnings': [], 'deleted': {}, 'lost': {}, 'changed': {},
           'instances': len(inst_ids), 'types': len(sym_ids),
           'sampled': MAX_VALUES if len(inst_ids) > MAX_VALUES else None}
    app = doc.Application
    tg = DB.TransactionGroup(doc, u'PEER Library: check {0}'.format(family_id))
    tg.Start()
    app.DocumentChanged += on_changed
    try:
        # as "Update anyway" would do it: what Revit can fix by deleting is
        # deleted (and counted); a plain Update refuses such a load instead
        try:
            loader.load_family(doc, path, family_id, overwrite, type_names, delete_broken=True)
        except Exception as ex:
            res['failed'] = list(Guard.last_errors) or [u'{0}'.format(ex)]
        res['warnings'] = list(Guard.last_warnings)
        res['resolved'] = list(Guard.last_resolved)
        if not res['failed']:
            gone = set(deleted)
            d = {'dimensions': len(gone & dims), 'tags': len(gone & tags),
                 'instances': len(gone & inst_set)}
            other = [deps[k] for k in gone if k in deps]
            d['other'] = len(other)
            res['deleted'] = dict((k, v) for k, v in d.items() if v)
            res['other_categories'] = sorted(set(other))
            res['lost'], res['changed'] = _diff_values(doc, before, sym_set, gone)
    finally:
        try:
            app.DocumentChanged -= on_changed
        except Exception:
            pass
        if tg.HasStarted() and not tg.HasEnded():
            tg.RollBack()                  # the load's own transaction is always closed by now
    return res


def _diff_values(doc, before, sym_set, gone):
    lost, changed = {}, {}
    for key, (eid, vals) in before.items():
        if key in gone:
            continue
        e = doc.GetElement(eid)
        if e is None:
            continue
        now = _values(e)
        slot = 1 if key in sym_set else 0
        for name, (g, v) in vals.items():
            if v is None:
                continue
            after = now.get(name)
            if after is None or (g and after[0] and after[0] != g):
                lost.setdefault(name, [0, 0])[slot] += 1
            elif after[1] != v:
                changed.setdefault(name, [0, 0])[slot] += 1
    return lost, changed


# ---- previews / load next to it --------------------------------------------------
def preview_folder():
    return os.path.join(tempfile.gettempdir(), u'peer_lib_check')


def rename_aside(doc, family_id):
    """Renames the family in the project to '<name> (project)' (or ... 2, 3)
    so the library family loads next to it. Returns the new name."""
    fam = loader.find_family(doc, family_id)
    if fam is None:
        return None
    names = set(f.Name.lower() for f in DB.FilteredElementCollector(doc).OfClass(DB.Family))
    base = u'{0} (project)'.format(fam.Name)
    name, k = base, 2
    while name.lower() in names:
        name = u'{0} {1}'.format(base, k)
        k += 1
    tx = loader._tx(doc, u'PEER Library: keep {0}'.format(fam.Name))
    tx.Start()
    try:
        try:
            fam.Name = name
        except Exception:
            clr.GetClrType(DB.Element).GetProperty('Name').SetValue(fam, name, None)
        tx.Commit()
    finally:
        if tx.HasStarted() and not tx.HasEnded():
            tx.RollBack()
    if tx.GetStatus() != DB.TransactionStatus.Committed:
        raise Exception(strings.CHECK_RENAME_FAILED.format(fam.Name))
    return name
