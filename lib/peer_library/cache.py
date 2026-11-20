# -*- coding: utf-8 -*-
"""Local copy of the library: %LOCALAPPDATA%/PEER/Library, same layout.

get(card, ext): returns a local path whose sha1 matches the card. A missing
or changed file is downloaded again. Without a connection a matching cached
file still works; a missing one raises OfflineError.
"""

import io
import os

from peer_library import index, jsonio, rfa_info
from peer_library.backend_base import AccessError, LibraryError, OfflineError

HASH_FIELD = {'.rfa': 'sha1', '.png': 'png_sha1', '.txt': 'catalog_sha1'}
INDEX_COPY = 'index.json'
CHANGELOG_COPY = 'changelog.json'


class CorruptError(LibraryError):
    pass


class Cache(object):

    def __init__(self, folder, backend):
        self.folder = folder
        self.backend = backend
        self.online = None

    def local_path(self, card, ext):
        """Always <cache>/<group>/<ID><ext>: Revit names a family after its file,
        and LoadFamilySymbol wants the catalog <ID>.txt next to <ID>.rfa.
        (The service keeps versions as <group>/<ID>/v<N>.rfa - that is only
        the download address.)"""
        return os.path.join(self.folder, index.folder_of(card), card['id'] + ext)

    def _fetch(self, copy, plain, if_changed):
        """Download a JSON file of the library and keep the copy. With a service
        that sends ETags the copy is downloaded only when it changed."""
        tag_file = copy + '.etag'
        if if_changed is None:
            data = plain()
            jsonio.write(copy, data)
            return data
        old = None
        if os.path.isfile(copy) and os.path.isfile(tag_file):
            try:
                with io.open(tag_file, 'r', encoding='utf-8') as f:
                    old = f.read().strip() or None
            except (IOError, OSError):
                old = None
        data, tag = if_changed(old)
        if data is None:                                    # 304: the copy is current
            data = jsonio.read(copy)
            if data is not None:
                return data
            data, tag = if_changed(None)                    # copy unreadable: full download
        jsonio.write(copy, data)
        try:
            if tag:
                with io.open(tag_file, 'w', encoding='utf-8') as f:
                    f.write(u'{0}'.format(tag))
            elif os.path.isfile(tag_file):
                os.remove(tag_file)
        except (IOError, OSError):
            pass
        return data

    def index(self):
        """(index, online). Falls back to the last downloaded index."""
        copy = os.path.join(self.folder, INDEX_COPY)
        try:
            data = self._fetch(copy, self.backend.get_index,
                               getattr(self.backend, 'get_index_if_changed', None))
            self.online = True
            return data, True
        except AccessError:
            raise                       # key revoked / not signed in: no offline copy
        except OfflineError:
            self.online = False
        except (IOError, OSError, LibraryError):
            if not os.path.exists(copy):
                raise
            self.online = False
        allowed = getattr(self.backend, 'offline_allowed', None)
        if allowed is not None and not allowed():
            raise AccessError(u'No connection, and the library key was last checked more than '
                              u'14 days ago. Connect to the internet to continue.')
        data = jsonio.read(copy)
        if data is None:
            raise OfflineError(u'No connection to the library and no saved copy yet.')
        return data, False

    def changelog(self):
        copy = os.path.join(self.folder, CHANGELOG_COPY)
        try:
            return self._fetch(copy, self.backend.get_changelog,
                               getattr(self.backend, 'get_changelog_if_changed', None))
        except Exception:
            return jsonio.read(copy, {'entries': []}) or {'entries': []}

    def _remember(self, name, fetch, default):
        """Fetch from the storage and keep a copy; offline -> the copy."""
        copy = os.path.join(self.folder, name)
        try:
            data = fetch()
            jsonio.write(copy, data)
            return data
        except Exception:
            data = jsonio.read(copy)
            return data if data is not None else default

    def collections(self):
        return self._remember('collections.json', self.backend.get_collections,
                              {'collections': []}).get('collections') or []

    def stats(self):
        return self._remember('stats.json', self.backend.get_stats,
                              {'families': {}}).get('families') or {}

    def has(self, card, ext='.rfa'):
        path = self.local_path(card, ext)
        want = card.get(HASH_FIELD[ext])
        return os.path.isfile(path) and (not want or rfa_info.sha1(path) == want)

    def get(self, card, ext='.rfa'):
        rel = index.rel_path(card, ext)
        path = self.local_path(card, ext)
        want = card.get(HASH_FIELD[ext]) or u''
        if ext != '.rfa' and not want:
            return None                                     # no preview / no catalog
        if os.path.isfile(path) and (not want or rfa_info.sha1(path) == want):
            return path
        try:
            self.backend.download(rel, path)
        except OfflineError:
            if os.path.isfile(path):
                raise CorruptError(u'"{0}": the saved copy differs from the library and there '
                                   u'is no connection to download it again.'.format(card['id']))
            raise OfflineError(u'"{0}" was never downloaded on this computer and there is '
                               u'no connection to the library.'.format(card['id']))
        if want and rfa_info.sha1(path) != want:
            try:
                os.remove(path)
            except OSError:
                pass
            raise CorruptError(u'"{0}": the downloaded file does not match the library '
                               u'(still syncing or changed by hand). Try again later.'
                               .format(card['id']))
        return path
