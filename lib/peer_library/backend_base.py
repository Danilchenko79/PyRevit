# -*- coding: utf-8 -*-
"""Storage interface. Windows call only these methods, so switching between a
plain folder (backend_local) and the access service (backend_http) is one
setting.

Paths inside the library are '/'-separated, relative to PEER-Library:
'01_Framing/PEER_Beam.rfa'.
"""


class LibraryError(Exception):
    """Message is one line for the user; details go to the log."""


class OfflineError(LibraryError):
    pass


class AccessError(LibraryError):
    """status: 401 = the service does not know the key (revoked), 403 = not allowed
    (or a proxy / firewall in between) - only 401 means the key is gone."""
    def __init__(self, message=u'', status=None):
        LibraryError.__init__(self, message)
        self.status = status


class ConflictError(LibraryError):
    pass


class NotFoundError(LibraryError):
    pass


PROPOSAL_STATUSES = ('pending', 'accepted', 'rejected')


class Backend(object):
    kind = 'base'

    def auth(self):
        """{'name': .., 'role': 'user'|'admin'}; raises AccessError."""
        raise NotImplementedError

    def get_index(self):
        raise NotImplementedError

    def get_changelog(self):
        raise NotImplementedError

    def download(self, path, target):
        """Copy library file `path` to local file `target`."""
        raise NotImplementedError

    def next_version(self, family_id):
        """Version the next publish of family_id gets (1 for a new family)."""
        raise NotImplementedError

    def publish(self, card, rfa, png=None, catalog=None, note=u'', proposal_id=None):
        """Admin. card['version'] must equal next_version(card['id']).
        Returns the stored card."""
        raise NotImplementedError

    def deprecate(self, family_id, note=u''):
        raise NotImplementedError

    def update_card(self, family_id, fields):
        """Admin: name / tags / description / help_url / group / types without a new version."""
        raise NotImplementedError

    def get_collections(self):
        """{'collections': [{'id', 'name', 'description', 'families': [ids]}]}"""
        raise NotImplementedError

    def put_collections(self, collections):
        """Admin: replace all collections."""
        raise NotImplementedError

    def get_stats(self, days=90):
        """{'families': {id: {'downloads': n, 'users': n}}} - {} where not tracked."""
        return {'families': {}}

    def send_proposal(self, meta, rfa=None, screenshot=None):
        """Any user. Returns proposal id. meta['kind']: new / fix (with a file),
        request / issue (no file)."""
        raise NotImplementedError

    def list_proposals(self, include_done=False):
        """Admin: every proposal."""
        raise NotImplementedError

    def my_proposals(self):
        raise NotImplementedError

    def download_proposal(self, proposal_id, target_dir):
        """Admin: proposal files into target_dir. Returns path of the .rfa."""
        raise NotImplementedError

    def resolve_proposal(self, proposal_id, status, comment=u''):
        """Admin: status 'accepted' | 'rejected' (comment required)."""
        raise NotImplementedError
