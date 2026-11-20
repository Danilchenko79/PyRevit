# -*- coding: utf-8 -*-
"""Check a Revit shared parameter file and write a corrected COPY (CPython).

    py -3 lib/peer_library/tools/fop_check.py <PR_FOPv4.txt> <output folder> [--rename GUID=NewName ...] [--drop GUID ...]

The original file is only read. Output: <name>.fixed.txt (same encoding and
line ends as the original) and <name>.report.csv.
Checks: characters Revit does not accept in a parameter name, names that
appear twice (other GUID), names that differ only in case / spaces, spaces at
the ends or doubled, a GUID that appears twice.
"""
from __future__ import print_function

import argparse
import codecs
import collections
import csv
import io
import os
import re
import sys

FORBIDDEN = u'\\:{}[]|;<>?`~'          # Revit refuses these in parameter names


def read(path):
    raw = io.open(path, 'rb').read()
    if raw.startswith(codecs.BOM_UTF16_LE) or raw.startswith(codecs.BOM_UTF16_BE):
        enc = 'utf-16'
    elif raw.startswith(codecs.BOM_UTF8):
        enc = 'utf-8-sig'
    else:
        enc = 'utf-8'
    text = raw.decode(enc)
    nl = u'\r\n' if u'\r\n' in text else u'\n'
    return text, enc, nl


def params(text):
    """[(line index, guid, name, datatype, group id)]"""
    out = []
    for i, line in enumerate(text.splitlines()):
        if line.startswith(u'PARAM\t'):
            f = line.split(u'\t')
            out.append((i, f[1].lower(), f[2], f[3], f[5]))
    return out


def groups(text):
    return dict((l.split(u'\t')[1], l.split(u'\t')[2]) for l in text.splitlines() if l.startswith(u'GROUP\t'))


def norm(name):
    return re.sub(u'\\s+', u' ', name.strip()).lower()


def findings(text):
    """[(level, check, guid, name, group, text)]"""
    rows = params(text)
    grp = groups(text)
    out = []
    by_name, by_norm, by_guid = collections.defaultdict(list), collections.defaultdict(list), collections.Counter()
    for i, guid, name, dtype, gid in rows:
        by_name[name].append((guid, gid))
        by_norm[norm(name)].append(name)
        by_guid[guid] += 1
    for i, guid, name, dtype, gid in rows:
        g = grp.get(gid, gid)
        bad = sorted(set(c for c in name if c in FORBIDDEN))
        if bad:
            out.append((u'error', u'forbidden_char', guid, name, g,
                        u'{0} in a parameter name: Revit refuses it when a name is typed, and lost letters '
                        u'(α, β, Cyrillic) end up as ?.'.format(u' '.join(bad))))
        if name != name.strip() or u'  ' in name:
            out.append((u'warning', u'spaces', guid, name, g, u'Spaces at the ends or doubled.'))
        if len(by_name[name]) > 1:
            others = u', '.join(x[0] for x in by_name[name] if x[0] != guid)
            out.append((u'error', u'same_name', guid, name, g,
                        u'The same name with another GUID ({0}): Revit shows two parameters with one name, '
                        u'schedules and tags take only one of them.'.format(others)))
        elif len(set(by_norm[norm(name)])) > 1:
            out.append((u'warning', u'twin', guid, name, g,
                        u'Differs only in case / spaces from: ' +
                        u', '.join(sorted(set(by_norm[norm(name)]) - set([name])))))
        if by_guid[guid] > 1:
            out.append((u'error', u'same_guid', guid, name, g, u'This GUID appears more than once.'))
    return out


def fixed(text, nl, renames, drops):
    """(new text, [(guid, old name, action)])"""
    done, lines = [], []
    for line in text.splitlines():
        if line.startswith(u'PARAM\t'):
            f = line.split(u'\t')
            guid = f[1].lower()
            if guid in drops:
                done.append((guid, f[2], u'removed'))
                continue
            if guid in renames and renames[guid] != f[2]:
                done.append((guid, f[2], u'renamed to ' + renames[guid]))
                f[2] = renames[guid]
                line = u'\t'.join(f)
        lines.append(line)
    return nl.join(lines) + nl, done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('fop')
    ap.add_argument('out')
    ap.add_argument('--rename', action='append', default=[], help='GUID=NewName')
    ap.add_argument('--drop', action='append', default=[], help='GUID')
    a = ap.parse_args()
    text, enc, nl = read(a.fop)
    renames = {}
    for r in a.rename:
        g, n = r.split('=', 1)
        renames[g.lower()] = n
    drops = set(g.lower() for g in a.drop)
    known = set(p[1] for p in params(text))
    missing = [g for g in list(renames) + list(drops) if g not in known]
    if missing:
        sys.exit('No such GUID in the file: ' + ', '.join(missing))
    if not os.path.isdir(a.out):
        os.makedirs(a.out)
    base = os.path.splitext(os.path.basename(a.fop))[0]
    before = findings(text)
    new_text, done = fixed(text, nl, renames, drops)
    after = findings(new_text)
    out_file = os.path.join(a.out, base + '.fixed.txt')
    with io.open(out_file, 'wb') as f:
        f.write(codecs.BOM_UTF16_LE + new_text.encode('utf-16-le') if enc == 'utf-16' else new_text.encode(enc))
    rep = os.path.join(a.out, base + '.report.csv')
    with io.open(rep, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['when', 'level', 'check', 'guid', 'name', 'group', 'text'])
        for r in before:
            w.writerow(['before'] + list(r))
        for g, n, act in done:
            w.writerow(['change', 'info', 'fixed', g, n, '', act])
        for r in after:
            w.writerow(['after'] + list(r))
    print('PARAMS', len(params(text)), '->', len(params(new_text)))
    print('BEFORE', len(before), 'AFTER', len(after), 'CHANGES', len(done))
    print('FIXED', out_file)
    print('REPORT', rep)


if __name__ == '__main__':
    main()
