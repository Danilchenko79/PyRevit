# -*- coding: utf-8 -*-
"""What a family load would break - plain Python, no Revit (tested in CPython).

A family signature (family_sig.signature makes it in Revit):
    {'name': u'..', 'category': u'Detail Items',
     'params': [{'name', 'shared', 'guid', 'instance', 'spec', 'formula', 'reporting'}],
     'types': [u'..'], 'nested': [{'name', 'category', 'shared'}]}

A finding is (level, code, text):
    'error'   - something in the project breaks (values, dimensions, tags, schedules)
    'warning' - look before you go on
    'info'    - fine to know
"""

import codecs

ERROR, WARNING, INFO = 'error', 'warning', 'info'
_RANK = {ERROR: 0, WARNING: 1, INFO: 2}
SKIP_PARAMS = ('PEER_Version',)          # library bookkeeping, not a design value
LIST_MAX = 6


# ---- helpers -----------------------------------------------------------------
def worst(findings):
    """Most serious level of the findings, or None."""
    levels = [f[0] for f in findings]
    for lv in (ERROR, WARNING, INFO):
        if lv in levels:
            return lv
    return None


def ordered(findings):
    return sorted(findings, key=lambda f: _RANK.get(f[0], 3))


def spec_name(spec):
    """'autodesk.spec.aec:length-2.0.0' -> 'length'."""
    s = (spec or u'').split(u':')[-1]
    return s.split(u'-')[0] or u'?'


def _kind(p):
    return (u'instance' if p.get('instance') else u'type') + (
        u', shared' if p.get('shared') else u'')


def _names(items, limit=LIST_MAX):
    items = list(items)
    text = u', '.join(u"'{0}'".format(x) for x in items[:limit])
    if len(items) > limit:
        text += u' (+{0})'.format(len(items) - limit)
    return text


def _norm(name):
    return u' '.join((name or u'').split()).lower()


def _params(sig):
    out = {}
    for p in (sig or {}).get('params') or []:
        if p.get('name') and p['name'] not in SKIP_PARAMS:
            out[p['name']] = p
    return out


# ---- project family -> library family -----------------------------------------
def compare(project, library, project_shared=None, project_names=None):
    """Findings for replacing `project` (signature of the family in the project)
    with `library`. project_shared = {guid: name} of the project's shared
    parameters; project_names = names (lower) of the families in the project."""
    res = []
    pc, lc = (project or {}).get('category'), (library or {}).get('category')
    if pc and lc and pc != lc:
        res.append((ERROR, 'category', u'Category: {0} in the project, {1} in the library. '
                    u'Revit does not change the category of a family that is in the project.'
                    .format(pc, lc)))
    pp, lp = _params(project), _params(library)
    lib_by_guid = dict((p['guid'], p) for p in lp.values() if p.get('shared') and p.get('guid'))
    lib_by_norm = dict((_norm(n), p) for n, p in lp.items())
    missing = []
    for name, p in sorted(pp.items()):
        lpar = lp.get(name)
        if lpar is None:
            same = lib_by_guid.get(p.get('guid')) if p.get('shared') else None
            if same is not None:
                res.append((INFO, 'renamed', u"'{0}' is called '{1}' in the library - the same "
                            u"shared parameter, values stay.".format(name, same['name'])))
                continue
            near = lib_by_norm.get(_norm(name))
            if near is not None:
                res.append((ERROR, 'spelling', u"'{0}' is spelled '{1}' in the library - Revit "
                            u"takes them as two parameters, the values are lost."
                            .format(name, near['name'])))
                continue
            missing.append(name)
            continue
        if p.get('shared') and lpar.get('shared'):
            if (p.get('guid') or u'').lower() != (lpar.get('guid') or u'').lower():
                res.append((ERROR, 'guid', u"'{0}': another shared parameter in the library "
                            u"(GUID {1} instead of {2}) - schedules, tags and filters of the "
                            u"project keep the old one and show nothing."
                            .format(name, lpar.get('guid'), p.get('guid'))))
                continue
        elif p.get('shared') != lpar.get('shared'):
            res.append((ERROR, 'shared_switch', u"'{0}': {1} parameter in the project, {2} in the "
                        u"library - tags and schedules that show it go empty.".format(
                            name, u'shared' if p.get('shared') else u'family',
                            u'shared' if lpar.get('shared') else u'family')))
            continue
        if spec_name(p.get('spec')) != spec_name(lpar.get('spec')):
            res.append((ERROR, 'spec', u"'{0}': {1} in the project, {2} in the library - the "
                        u"values are lost.".format(name, spec_name(p.get('spec')),
                                                    spec_name(lpar.get('spec')))))
            continue
        if bool(p.get('instance')) != bool(lpar.get('instance')):
            if p.get('instance'):
                text = (u"'{0}': instance parameter in the project, type parameter in the "
                        u"library - values set on single elements are replaced by one value "
                        u"per type.".format(name))
            else:
                text = (u"'{0}': type parameter in the project, instance parameter in the "
                        u"library - elements start from the value of their type.".format(name))
            res.append((WARNING, 'inst_type', text))
        if lpar.get('formula') and not p.get('formula') and not lpar.get('reporting'):
            res.append((WARNING, 'formula', u"'{0}' is calculated in the library ({1}) - values "
                        u"typed in the project are replaced.".format(name, lpar['formula'])))
    if missing:
        res.append((ERROR, 'param_missing', u'Not in the library family: {0} - their values in '
                    u'the project are lost, tags and schedules that show them go empty.'
                    .format(_names(missing))))
    new = sorted(n for n in lp if n not in pp and not (
        lp[n].get('shared') and lp[n].get('guid') in set(
            q.get('guid') for q in pp.values() if q.get('shared'))))
    if new:
        res.append((INFO, 'param_new', u'New in the library: {0}.'.format(_names(new))))
    res.extend(shared_conflicts(library, project_shared, skip=set(pp)))
    pt, lt = set((project or {}).get('types') or []), set((library or {}).get('types') or [])
    if pt - lt:
        res.append((INFO, 'types_extra', u'Types only in the project stay as they are: {0}.'
                    .format(_names(sorted(pt - lt)))))
    if lt - pt and project is not None:
        res.append((INFO, 'types_new', u'Types added from the library: {0}.'
                    .format(_names(sorted(lt - pt)))))
    names = set(project_names or [])
    for n in (library or {}).get('nested') or []:
        if n.get('shared') and n.get('name', u'').lower() in names:
            res.append((WARNING, 'nested', u"Nested shared family '{0}' is also in the project - "
                        u"the library version replaces it everywhere in the project."
                        .format(n['name'])))
    return ordered(res)


def shared_conflicts(library, project_shared, skip=()):
    """The library family brings a shared parameter whose name the project
    already uses for another GUID -> two parameters with one name."""
    res = []
    if not project_shared:
        return res
    by_name = {}
    for g, n in project_shared.items():
        by_name.setdefault(n, set()).add((g or u'').lower())
    for name, p in sorted(_params(library).items()):
        if not p.get('shared') or name in skip:
            continue
        g = (p.get('guid') or u'').lower()
        others = by_name.get(name)
        if others and g not in others:
            res.append((ERROR, 'guid_project', u"'{0}': the project already has a shared "
                        u"parameter '{0}' with another GUID - after the load there are two "
                        u"parameters named '{0}' and schedules/filters see only one."
                        .format(name)))
        elif g in project_shared and project_shared[g] != name:
            res.append((INFO, 'guid_name', u"'{0}' is called '{1}' in the project (same GUID)."
                        .format(name, project_shared[g])))
    return res


# ---- result of a trial load (load_check.trial) --------------------------------
def trial_findings(trial, overwrite=False):
    """trial = {'failed': [texts], 'warnings': [texts],
                'deleted': {'dimensions': n, 'tags': n, 'instances': n, 'other': n},
                'lost': {name: [instances, types]}, 'changed': {name: [instances, types]},
                'instances': n, 'types': n, 'sampled': n or None}"""
    res = []
    if not trial:
        return res
    for t in trial.get('failed') or []:
        res.append((ERROR, 'failed', u'Revit refuses the load: {0}'.format(t)))
    resolved = []
    for t in trial.get('resolved') or []:
        t = (t or u'').strip().rstrip(u'.')
        if t and t not in resolved:
            resolved.append(t)
    if resolved:
        res.append((ERROR, 'needs_delete', u'Revit can load it only by deleting elements ({0}). '
                    u'Update refuses it; "Update anyway" deletes them.'.format(u' | '.join(resolved[:2]))))
    d = trial.get('deleted') or {}
    for key, what in (('dimensions', u'dimension(s) on this family'), ('tags', u'tag(s)'),
                      ('instances', u'placed element(s) of this family')):
        if d.get(key):
            res.append((ERROR, 'deleted_' + key, u'{0} {1} would be deleted.'.format(d[key], what)))
    if d.get('other'):
        cats = trial.get('other_categories') or []
        res.append((ERROR, 'deleted_other', u'{0} other element(s) would be deleted{1}.'.format(
            d['other'], u' ({0})'.format(u', '.join(cats)) if cats else u'')))
    lost = trial.get('lost') or {}
    if lost:
        res.append((ERROR, 'values_lost', u'Values lost: {0}.'.format(_counts(lost))))
    changed = trial.get('changed') or {}
    if changed:
        if overwrite:
            res.append((INFO, 'values_reset', u'Values set back to the library: {0}.'
                        .format(_counts(changed))))
        else:
            res.append((WARNING, 'values_changed', u'Values that change: {0}.'
                        .format(_counts(changed))))
    warns = []
    for t in trial.get('warnings') or []:
        if t not in warns:
            warns.append(t)
    if warns:
        res.append((WARNING, 'revit_warnings', u'Revit warns: {0}'.format(
            u' | '.join(warns[:3]) + (u' (+{0})'.format(len(warns) - 3) if len(warns) > 3 else u''))))
    return ordered(res)


def soften(findings, trial):
    """A parameter that is missing / of another kind in the library breaks
    nothing when the trial load found no values that get lost (and checked
    every element)."""
    if not trial or trial.get('failed') or trial.get('lost') or trial.get('sampled'):
        return findings
    out = []
    for lv, code, text in findings:
        if lv == ERROR and code in ('param_missing', 'spec', 'spelling'):
            out.append((WARNING, code, text + u' No values are set in this project.'))
        else:
            out.append((lv, code, text))
    return ordered(out)


def _counts(d):
    parts = []
    for name in sorted(d, key=lambda k: -sum(d[k])):
        n_inst, n_type = d[name]
        bits = []
        if n_inst:
            bits.append(u'{0} element{1}'.format(n_inst, u'' if n_inst == 1 else u's'))
        if n_type:
            bits.append(u'{0} type{1}'.format(n_type, u'' if n_type == 1 else u's'))
        parts.append(u"'{0}' in {1}".format(name, u' and '.join(bits)))
    text = u', '.join(parts[:LIST_MAX])
    if len(parts) > LIST_MAX:
        text += u' (+{0} parameters)'.format(len(parts) - LIST_MAX)
    return text


def trial_summary(trial):
    """'12 elements, 3 types of this family in the project' (+ sampled note)."""
    if not trial:
        return u''
    text = u'{0} placed element{1}, {2} type{3} in the project'.format(
        trial.get('instances', 0), u'' if trial.get('instances') == 1 else u's',
        trial.get('types', 0), u'' if trial.get('types') == 1 else u's')
    if trial.get('sampled'):
        text += u' (values checked on {0} of them)'.format(trial['sampled'])
    return text


# ---- one family on its own (Check family button, Publish) -----------------------
def hygiene_findings(sig, library_names=None):
    """Names that differ only in case / spaces, parameters nothing uses,
    nested shared families named like library families."""
    res = []
    params = (sig or {}).get('params') or []
    seen = {}
    for p in params:
        seen.setdefault(_norm(p['name']), []).append(p['name'])
    for names in seen.values():
        if len(names) > 1 and _real_twins(names):
            res.append((WARNING, 'twins', u'Parameters that differ only in case or spaces: {0} - '
                        u'people (and filters) take them for one.'.format(_names(names))))
    for p in params:
        if p['name'] != p['name'].strip() or u'  ' in p['name']:
            res.append((WARNING, 'spaces', u"'{0}' has extra spaces in its name.".format(p['name'])))
    unused = [p['name'] for p in params if p.get('unused')]
    if unused:
        res.append((INFO, 'unused', u'Not used by any dimension, element or formula: {0}.'
                    .format(_names(unused))))
    lib = set(n.lower() for n in (library_names or []))
    for n in (sig or {}).get('nested') or []:
        if n.get('shared') and n.get('name', u'').lower() in lib:
            res.append((WARNING, 'nested_library', u"Nested shared family '{0}' has the name of a "
                        u"library family - in a project both are one family: make sure this is "
                        u"the library version.".format(n['name'])))
    if not any(p['name'] in SKIP_PARAMS for p in params):
        res.append((INFO, 'no_version', u'No PEER_Version yet - Publish adds it.'))
    return ordered(res)


def _real_twins(names):
    """'b' / 'B', 'r1' / 'R1', 'Washer d' / 'Washer D' are a drawing convention (two
    dimensions), not a typo: case differences in 1-2 letter words do not count."""
    first = names[0]
    for other in names[1:]:
        if first.strip() != u' '.join(first.split()) or other.strip() != u' '.join(other.split()):
            return True                                    # doubled spaces inside
        a, b = first.split(), other.split()
        if any(x != y and len(x) > 2 for x, y in zip(a, b)):
            return True
    return False


def shared_file_self(shared, file_name=u'the company shared parameter file'):
    """Problems of the company file itself: one name for several parameters,
    names with '?' (characters lost when the file was rewritten)."""
    res = []
    if not shared:
        return res
    for name, guids in sorted(shared['by_name'].items()):
        if len(guids) > 1:
            res.append((WARNING, 'file_twins', u"{0}: '{1}' is the name of {2} different parameters "
                        u"({3}) - a project shows them under one name.".format(
                            file_name, name, len(guids), u', '.join(sorted(guids)))))
    lost = sorted(n for n in shared['by_name'] if u'?' in n)
    if lost:
        res.append((WARNING, 'file_lost_chars', u"{0}: names with '?' (letters lost when the file was "
                    u"rewritten): {1}.".format(file_name, _names(lost))))
    return res


# ---- what Fix family can put right by itself -------------------------------------
def fix_plan(sig, shared, remove_unused=False):
    """Actions for family_fix.apply, each a dict with 'op', 'name', 'text':
    rename_shared - shared parameter with an old name -> the company file's
                    name (same GUID: projects keep their values);
    to_shared     - family parameter whose name the company file has as one
                    shared parameter -> that shared parameter (formulas and
                    dimensions stay);
    remove        - parameter nothing uses (only when asked).
    A name with '?' in the company file is damaged - not used as a target."""
    acts = []
    if not sig:
        return acts
    by_guid = (shared or {}).get('by_guid') or {}
    by_name = (shared or {}).get('by_name') or {}
    names = set(p['name'] for p in sig.get('params') or [])
    for p in sig.get('params') or []:
        name, g = p['name'], (p.get('guid') or u'').lower()
        if p.get('shared') and g in by_guid:
            new = by_guid[g][0]
            if new != name and u'?' not in new and new not in names and len(by_name.get(new, ())) == 1:
                acts.append({'op': 'rename_shared', 'name': name, 'guid': g, 'new': new,
                             'text': u"'{0}' -> '{1}' (same shared parameter)".format(name, new)})
        elif not p.get('shared') and len(by_name.get(name, ())) == 1:
            g2 = list(by_name[name])[0]
            acts.append({'op': 'to_shared', 'name': name, 'guid': g2, 'new': name,
                         'text': u"'{0}' -> the company shared parameter '{0}'".format(name)})
        elif remove_unused and p.get('unused'):
            acts.append({'op': 'remove', 'name': name, 'text': u"remove '{0}' (nothing uses it)".format(name)})
    return acts


def types_findings(broken):
    """broken = [(type name, Revit's error text)] from switching to each type."""
    res = []
    for name, text in broken or []:
        res.append((WARNING, 'type_broken', u"Type '{0}' does not regenerate: {1}".format(name, text)))
    return res


# ---- company shared parameter file ---------------------------------------------
def read_shared_file(path):
    """Revit shared parameter file -> {'by_guid': {guid: (name, datatype)},
    'by_name': {name: set(guids)}}. Revit writes it as UTF-16; UTF-8 also read."""
    with open(path, 'rb') as f:
        raw = f.read()
    if raw[:2] in (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE):
        text = raw.decode('utf-16')
    elif raw[:3] == codecs.BOM_UTF8:
        text = raw[3:].decode('utf-8')
    else:
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError:
            text = raw.decode('cp1252', 'replace')
    by_guid, by_name = {}, {}
    for line in text.splitlines():
        if not line.startswith(u'PARAM\t'):
            continue
        cols = line.split(u'\t')
        if len(cols) < 4:
            continue
        g, name, dtype = cols[1].strip().lower(), cols[2], cols[3]
        by_guid[g] = (name, dtype)
        by_name.setdefault(name, set()).add(g)
    return {'by_guid': by_guid, 'by_name': by_name}


def shared_file_findings(sig, shared, file_name=u'the company shared parameter file'):
    """A family's own parameters against the company shared parameter file."""
    res = []
    if not shared or not sig:
        return res
    by_guid, by_name = shared['by_guid'], shared['by_name']
    by_norm = {}
    for n in by_name:
        by_norm.setdefault(_norm(n), n)
    not_in = []
    for name, p in sorted(_params(sig).items()):
        g = (p.get('guid') or u'').lower()
        if p.get('shared'):
            if g in by_guid:
                if by_guid[g][0] != name:
                    res.append((WARNING, 'file_name', u"'{0}' is called '{1}' in {2} (same GUID)."
                                .format(name, by_guid[g][0], file_name)))
            elif name in by_name:
                res.append((ERROR, 'file_guid', u"'{0}': GUID {1} is not the one in {2} ({3}) - "
                            u"projects get two parameters '{0}'.".format(
                                name, g, file_name, u', '.join(sorted(by_name[name])))))
            else:
                not_in.append(name)
        else:
            twin = name if name in by_name else by_norm.get(_norm(name))
            if twin:
                res.append((WARNING, 'should_share', u"'{0}' is a family parameter, but {1} has a "
                            u"shared '{2}' - tags and schedules cannot show this one."
                            .format(name, file_name, twin)))
    if not_in:
        res.append((WARNING, 'file_missing', u'Shared parameters not in {0}: {1}.'
                    .format(file_name, _names(not_in))))
    return ordered(res)
