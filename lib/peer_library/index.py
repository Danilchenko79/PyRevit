# -*- coding: utf-8 -*-
"""Family card (<ID>.json), index.json and changelog.json.

Card = everything the library window needs, so Revit never opens a .rfa
for search or preview. index.json is rebuilt from all cards on every
publish; delete it and build_index() restores it.
"""

import datetime
import os

from peer_library import checks_file, groups, jsonio, rfa_info

INDEX = 'index.json'
CHANGELOG = 'changelog.json'
MARKER = '.peer-library'
CHANGELOG_KEEP = 1000
NEW_DAYS = 14

CARD_DEFAULTS = {
    'id': u'',
    'name': u'',
    'group': u'',
    'revit_category': u'',
    'tags': [],
    'version': 0,
    'updated': u'',
    'revit': checks_file.LIBRARY_REVIT,
    'author': u'',
    'description': u'',
    'type_catalog': False,
    'sha1': u'',
    'png_sha1': u'',
    'catalog_sha1': u'',
    'size': 0,
    'help_url': u'',
    'status': u'active',
    'history': [],
}
STATUSES = ('active', 'deprecated')


def today():
    return datetime.date.today().isoformat()


def now():
    return datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')


def new_card(**fields):
    card = dict((k, (list(v) if isinstance(v, list) else v)) for k, v in CARD_DEFAULTS.items())
    for k, v in fields.items():
        card[k] = v
    if not card['name']:
        card['name'] = card['id']
    return card


def validate(card):
    """List of problems (empty = valid)."""
    p = []
    for k in ('id', 'name', 'group'):
        if not card.get(k):
            p.append(u'missing field: ' + k)
    for x in checks_file.check_name(card.get('id') or u''):
        p.append(u'id: ' + x)
    if card.get('group') and card['group'] not in groups.GROUP_IDS:
        p.append(u'unknown group: ' + card['group'])
    v = card.get('version')
    if not isinstance(v, int) or isinstance(v, bool) or v < 1:
        p.append(u'version must be an integer >= 1')
    if card.get('status', 'active') not in STATUSES:
        p.append(u'unknown status: {0}'.format(card.get('status')))
    if not isinstance(card.get('tags', []), list):
        p.append(u'tags must be a list')
    return p


def folder_of(card):
    return groups.ARCHIVE if card.get('status') == 'deprecated' else card['group']


def rel_path(card, ext):
    """Path inside PEER-Library, '/' separated. The service stores every
    version under its own key (card['files']: '01_Framing/PEER_Beam/v3.rfa');
    a plain folder library uses '01_Framing/PEER_Beam.rfa'."""
    files = card.get('files') or {}
    if files.get(ext):
        return files[ext]
    return u'{0}/{1}{2}'.format(folder_of(card), card['id'], ext)


def scan_cards(lib_root):
    """All cards in group folders and _Archive."""
    cards = []
    for folder in groups.GROUP_IDS + [groups.ARCHIVE]:
        d = os.path.join(lib_root, folder)
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if not name.lower().endswith('.json'):
                continue
            card = jsonio.read(os.path.join(d, name))
            if isinstance(card, dict) and card.get('id'):
                cards.append(card)
    return cards


def find_card(lib_root, family_id):
    low = family_id.lower()
    for c in scan_cards(lib_root):
        if c['id'].lower() == low:
            return c
    return None


def build_index(lib_root):
    cards = scan_cards(lib_root)
    order = dict((g, i) for i, g in enumerate(groups.GROUP_IDS + [groups.ARCHIVE]))
    cards.sort(key=lambda c: (order.get(folder_of(c), 99), c['id'].lower()))
    data = {'format': 1, 'built': now(), 'count': len(cards), 'families': cards}
    jsonio.write(os.path.join(lib_root, INDEX), data)
    marker = os.path.join(lib_root, MARKER)
    if not os.path.exists(marker):
        jsonio.write(marker, {'format': 1})
    return data


def read_index(lib_root):
    return jsonio.read(os.path.join(lib_root, INDEX))


def next_card(current, draft, user, note, rfa, png=None, catalog=None):
    """Card for a publish: version = current + 1, history appended, hashes set.

    draft: fields from the publish form (id, name, group, tags, description,
    help_url, revit_category). draft['version'] must equal the new version
    (it was written into the family as PEER_Version before upload).
    """
    card = new_card()
    if current:
        card.update(current)
        card['history'] = list(current.get('history') or [])
    for k, v in draft.items():
        if k in CARD_DEFAULTS and k not in ('history', 'sha1', 'png_sha1', 'catalog_sha1', 'size'):
            card[k] = v
    card['version'] = (current['version'] if current else 0) + 1
    card['status'] = 'active'
    card['updated'] = today()
    card['author'] = card.get('author') or user
    card['sha1'] = rfa_info.sha1(rfa)
    card['size'] = os.path.getsize(rfa)
    card['png_sha1'] = rfa_info.sha1(png) if png else u''
    card['catalog_sha1'] = rfa_info.sha1(catalog) if catalog else u''
    card['type_catalog'] = bool(catalog)
    card['history'].append({'v': card['version'], 'date': card['updated'],
                            'note': note or (u'First version' if not current else u''),
                            'by': user})
    return card


def changelog_add(lib_root, entry):
    path = os.path.join(lib_root, CHANGELOG)
    data = jsonio.read(path, {}) or {}
    entries = list(data.get('entries') or [])
    e = dict(entry)
    e.setdefault('time', now())
    entries.append(e)
    data = {'format': 1, 'entries': entries[-CHANGELOG_KEEP:]}
    jsonio.write(path, data)
    return data


def is_new(card, today_date=None):
    """Published or updated within NEW_DAYS."""
    try:
        d = datetime.datetime.strptime(card.get('updated') or u'', '%Y-%m-%d').date()
    except ValueError:
        return False
    t = today_date or datetime.date.today()
    return 0 <= (t - d).days < NEW_DAYS
