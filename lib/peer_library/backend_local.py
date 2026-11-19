# -*- coding: utf-8 -*-
"""Library on a plain folder (office share or a test folder).

    <root>/PEER-Library/   .peer-library, index.json, changelog.json,
                           <group>/<ID>.rfa .json .png .txt, _Archive/
    <root>/PEER-Inbox/     <date>_<user>_<ID>/family.rfa proposal.json screenshot.png
                           _Done/

Rights come from the settings (role) - fine for the office trial; the real
protection is the access service (backend_http).

Publish is all-or-nothing: new files are staged, old ones moved aside, and
on any error the old files come back and the index is rebuilt.
"""

import datetime
import os
import re
import shutil
import time

from peer_library import index, jsonio
from peer_library.backend_base import (AccessError, Backend, ConflictError, LibraryError,
                                       NotFoundError, OfflineError, PROPOSAL_STATUSES)

LIBRARY = 'PEER-Library'
INBOX = 'PEER-Inbox'
DONE = '_Done'
LOCK = '.lock'
LOCK_STALE_S = 15 * 60
EXTS = ('.rfa', '.png', '.txt', '.json')


class LocalBackend(Backend):
    kind = 'local'

    def __init__(self, root, role='user', user=u'user'):
        self.root = root
        self.role = role
        self.user = user
        self.lib = os.path.join(root, LIBRARY)
        self.inbox = os.path.join(root, INBOX)

    # ---- helpers -------------------------------------------------------
    def _need_admin(self):
        if self.role != 'admin':
            raise AccessError(u'Only a library admin can do this.')

    def _check_root(self):
        if not self.root or not os.path.isdir(self.root):
            raise OfflineError(u'Library folder not reachable: {0}'.format(self.root))

    def _abs(self, path):
        parts = [p for p in path.replace('\\', '/').split('/') if p]
        if not parts or any(p in ('.', '..') for p in parts):
            raise NotFoundError(u'Bad library path: ' + path)
        return os.path.join(self.lib, *parts)

    def _lock(self):
        jsonio.makedirs(self.lib)
        path = os.path.join(self.lib, LOCK)
        for _ in range(20):
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, u'{0} {1}'.format(self.user, index.now()).encode('utf-8'))
                os.close(fd)
                return path
            except OSError:
                try:
                    if time.time() - os.path.getmtime(path) > LOCK_STALE_S:
                        os.remove(path)
                        continue
                except OSError:
                    continue
                time.sleep(0.5)
        raise ConflictError(u'Another admin is publishing right now - try again in a minute.')

    @staticmethod
    def _unlock(path):
        try:
            os.remove(path)
        except OSError:
            pass

    # ---- read ----------------------------------------------------------
    def auth(self):
        self._check_root()
        return {'name': self.user, 'role': self.role}

    def get_index(self):
        self._check_root()
        data = index.read_index(self.lib)
        if data is None:
            if not os.path.isdir(self.lib):
                return {'format': 1, 'built': u'', 'count': 0, 'families': []}
            data = index.build_index(self.lib)
        return data

    def get_changelog(self):
        self._check_root()
        return jsonio.read(os.path.join(self.lib, index.CHANGELOG), {}) or {'entries': []}

    def download(self, path, target):
        self._check_root()
        src = self._abs(path)
        if not os.path.isfile(src):
            raise NotFoundError(u'Not in the library: ' + path)
        jsonio.makedirs(os.path.dirname(target))
        tmp = target + '.part'
        shutil.copyfile(src, tmp)
        jsonio.replace(tmp, target)
        return target

    def next_version(self, family_id):
        cur = index.find_card(self.lib, family_id)
        return (cur['version'] if cur else 0) + 1

    # ---- publish -------------------------------------------------------
    def publish(self, card, rfa, png=None, catalog=None, note=u'', proposal_id=None):
        self._need_admin()
        self._check_root()
        problems = index.validate(card)
        if problems:
            raise LibraryError(u'Card is not valid: ' + u'; '.join(problems))
        for p in (rfa, png, catalog):
            if p and not os.path.isfile(p):
                raise LibraryError(u'File not found: ' + p)
        lock = self._lock()
        try:
            current = index.find_card(self.lib, card['id'])
            if current and current['id'] != card['id']:
                raise ConflictError(u'"{0}" exists as "{1}" - IDs differ only in case.'
                                    .format(card['id'], current['id']))
            expected = (current['version'] if current else 0) + 1
            if card['version'] != expected:
                raise ConflictError(u'"{0}" was published by someone else meanwhile '
                                    u'(expected version {1}, got {2}). Publish again.'
                                    .format(card['id'], expected, card['version']))
            new = index.next_card(current, card, self.user, note, rfa, png, catalog)
            self._swap(current, new, {'.rfa': rfa, '.png': png, '.txt': catalog})
            try:
                index.changelog_add(self.lib, {
                    'id': new['id'], 'name': new['name'], 'group': new['group'],
                    'version': new['version'], 'action': 'updated' if current else 'added',
                    'note': note, 'by': self.user, 'date': new['updated']})
            except Exception:
                pass      # the family is published; a lost feed line is not fatal
            if proposal_id:
                self.resolve_proposal(proposal_id, 'accepted',
                                      u'Published as {0} v{1}'.format(new['id'], new['version']))
            return new
        finally:
            self._unlock(lock)

    def _swap(self, current, new, files):
        """Replace the family files atomically-ish; rebuild index."""
        fid = new['id']
        stage = os.path.join(self.lib, '.staging', fid)
        backup = os.path.join(self.lib, '.backup', fid)
        for d in (stage, backup):
            if os.path.isdir(d):
                shutil.rmtree(d)
            os.makedirs(d)
        for ext, src in files.items():
            if src:
                shutil.copyfile(src, os.path.join(stage, fid + ext))
        jsonio.write(os.path.join(stage, fid + '.json'), new)
        old_dir = os.path.join(self.lib, index.folder_of(current)) if current else None
        new_dir = os.path.join(self.lib, index.folder_of(new))
        moved_old, placed_new = [], []
        try:
            if old_dir:
                for ext in EXTS:
                    p = os.path.join(old_dir, fid + ext)
                    if os.path.exists(p):
                        shutil.move(p, os.path.join(backup, fid + ext))
                        moved_old.append(ext)
            jsonio.makedirs(new_dir)
            for name in os.listdir(stage):
                dst = os.path.join(new_dir, name)
                shutil.move(os.path.join(stage, name), dst)
                placed_new.append(dst)
            index.build_index(self.lib)
        except Exception:
            for p in placed_new:
                try:
                    os.remove(p)
                except OSError:
                    pass
            for ext in moved_old:
                shutil.move(os.path.join(backup, fid + ext), os.path.join(old_dir, fid + ext))
            try:
                index.build_index(self.lib)
            except Exception:
                pass
            raise
        finally:
            for d in (stage, backup):
                shutil.rmtree(d, ignore_errors=True)

    def deprecate(self, family_id, note=u''):
        self._need_admin()
        lock = self._lock()
        try:
            cur = index.find_card(self.lib, family_id)
            if not cur:
                raise NotFoundError(u'Not in the library: ' + family_id)
            if cur.get('status') == 'deprecated':
                return cur
            src_dir = os.path.join(self.lib, index.folder_of(cur))
            cur = dict(cur)
            cur['status'] = 'deprecated'
            cur['history'] = list(cur.get('history') or []) + [
                {'v': cur['version'], 'date': index.today(), 'note': note or u'Deprecated',
                 'by': self.user}]
            dst_dir = os.path.join(self.lib, index.folder_of(cur))
            jsonio.makedirs(dst_dir)
            for ext in EXTS:
                p = os.path.join(src_dir, family_id + ext)
                if os.path.exists(p):
                    shutil.move(p, os.path.join(dst_dir, cur['id'] + ext))
            jsonio.write(os.path.join(dst_dir, cur['id'] + '.json'), cur)
            index.build_index(self.lib)
            index.changelog_add(self.lib, {'id': cur['id'], 'name': cur['name'],
                                           'group': cur['group'], 'version': cur['version'],
                                           'action': 'deprecated', 'note': note,
                                           'by': self.user, 'date': index.today()})
            return cur
        finally:
            self._unlock(lock)

    # ---- proposals -----------------------------------------------------
    def _proposal_dirs(self, include_done=True):
        out = []
        for base in ([self.inbox, os.path.join(self.inbox, DONE)] if include_done
                     else [self.inbox]):
            if not os.path.isdir(base):
                continue
            for name in sorted(os.listdir(base)):
                d = os.path.join(base, name)
                if name != DONE and os.path.isfile(os.path.join(d, 'proposal.json')):
                    out.append(d)
        return out

    def _read_proposal(self, d):
        p = jsonio.read(os.path.join(d, 'proposal.json'), {}) or {}
        p['id'] = os.path.basename(d)
        p['done'] = os.path.basename(os.path.dirname(d)) == DONE
        return p

    def _find_proposal(self, proposal_id):
        for d in self._proposal_dirs():
            if os.path.basename(d) == proposal_id:
                return d
        raise NotFoundError(u'Proposal not found: ' + proposal_id)

    def send_proposal(self, meta, rfa=None, screenshot=None):
        self._check_root()
        fileless = meta.get('kind') in ('request', 'issue')
        if rfa is None and not fileless:
            raise LibraryError(u'A family file is needed.')
        if rfa is not None and not os.path.isfile(rfa):
            raise LibraryError(u'File not found: ' + rfa)
        slug = re.sub(r'[^A-Za-z0-9_-]+', '-', meta.get('family_id') or meta.get('name') or 'family')
        slug = slug.strip('-')[:40] or 'family'
        user = re.sub(r'[^A-Za-z0-9_-]+', '', self.user)[:20] or 'user'
        stamp = datetime.datetime.now().strftime('%Y-%m-%d_%H%M%S')
        pid = u'{0}_{1}_{2}'.format(stamp, user, slug)
        d = os.path.join(self.inbox, pid)
        tmp = d + '.part'
        if os.path.isdir(tmp):
            shutil.rmtree(tmp)
        os.makedirs(tmp)
        if rfa:
            shutil.copyfile(rfa, os.path.join(tmp, 'family.rfa'))
        if screenshot and os.path.isfile(screenshot):
            shutil.copyfile(screenshot, os.path.join(tmp, 'screenshot.png'))
        data = dict(meta)
        data.update({'author': self.user, 'sent': index.now(), 'status': 'pending',
                     'comment': u'', 'resolved_by': u'', 'resolved': u'',
                     'source_file': os.path.basename(rfa) if rfa else u'',
                     'has_file': bool(rfa), 'has_screenshot': bool(screenshot)})
        jsonio.write(os.path.join(tmp, 'proposal.json'), data)
        os.rename(tmp, d)
        return pid

    def list_proposals(self, include_done=False):
        self._need_admin()
        self._check_root()
        return [self._read_proposal(d) for d in self._proposal_dirs(include_done)]

    def my_proposals(self):
        self._check_root()
        return [p for p in (self._read_proposal(d) for d in self._proposal_dirs())
                if (p.get('author') or u'').lower() == self.user.lower()]

    def download_proposal(self, proposal_id, target_dir):
        self._need_admin()
        d = self._find_proposal(proposal_id)
        jsonio.makedirs(target_dir)
        for name in os.listdir(d):
            shutil.copyfile(os.path.join(d, name), os.path.join(target_dir, name))
        rfa = os.path.join(target_dir, 'family.rfa')
        return rfa if os.path.isfile(rfa) else None

    def resolve_proposal(self, proposal_id, status, comment=u''):
        self._need_admin()
        if status not in PROPOSAL_STATUSES or status == 'pending':
            raise LibraryError(u'Unknown status: ' + status)
        if status == 'rejected' and not (comment or u'').strip():
            raise LibraryError(u'Write why the proposal is rejected.')
        d = self._find_proposal(proposal_id)
        path = os.path.join(d, 'proposal.json')
        data = jsonio.read(path, {}) or {}
        data.update({'status': status, 'comment': comment, 'resolved_by': self.user,
                     'resolved': index.now()})
        jsonio.write(path, data)
        done = os.path.join(self.inbox, DONE)
        if os.path.dirname(d) != done:
            jsonio.makedirs(done)
            shutil.move(d, os.path.join(done, os.path.basename(d)))
        return data

    # ---- card info, collections -------------------------------------------------
    INFO_FIELDS = ('name', 'tags', 'description', 'help_url', 'group', 'types', 'revit_category')

    def update_card(self, family_id, fields):
        self._need_admin()
        lock = self._lock()
        try:
            cur = index.find_card(self.lib, family_id)
            if not cur or cur['id'] != family_id:
                raise NotFoundError(u'Not in the library: ' + family_id)
            new = dict(cur)
            for k in self.INFO_FIELDS:
                if k in fields:
                    new[k] = fields[k]
            problems = index.validate(new)
            if problems:
                raise LibraryError(u'Card is not valid: ' + u'; '.join(problems))
            new['info_updated'] = index.now()
            old_dir = os.path.join(self.lib, index.folder_of(cur))
            new_dir = os.path.join(self.lib, index.folder_of(new))
            if old_dir != new_dir:
                jsonio.makedirs(new_dir)
                for ext in EXTS:
                    p = os.path.join(old_dir, family_id + ext)
                    if os.path.exists(p):
                        shutil.move(p, os.path.join(new_dir, family_id + ext))
            jsonio.write(os.path.join(new_dir, family_id + '.json'), new)
            index.build_index(self.lib)
            return new
        finally:
            self._unlock(lock)

    def get_collections(self):
        self._check_root()
        data = jsonio.read(os.path.join(self.lib, 'collections.json'), {}) or {}
        return {'format': 1, 'collections': list(data.get('collections') or [])}

    def put_collections(self, collections):
        self._need_admin()
        out = []
        for c in collections or []:
            name = (c.get('name') or u'').strip()
            if name:
                out.append({'id': c.get('id') or name, 'name': name,
                            'description': c.get('description') or u'',
                            'families': list(c.get('families') or []),
                            'updated': index.now(), 'by': self.user})
        data = {'format': 1, 'collections': out}
        jsonio.write(os.path.join(self.lib, 'collections.json'), data)
        return data
