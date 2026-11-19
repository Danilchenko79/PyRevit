# -*- coding: utf-8 -*-
"""Library through the access service (Cloudflare Worker, see service/).

Same interface as backend_local. HTTPS with the personal key in
"Authorization: Bearer"; the service decides what the key may do.
In Revit the request goes through .NET HttpWebRequest (TLS 1.2 forced),
outside Revit through urllib. One retry on a network error. The key is
never written to logs or messages.
"""

import datetime
import io
import json
import os
import uuid

from peer_library import config, keystore, log
from peer_library.backend_base import (AccessError, Backend, ConflictError, LibraryError,
                                       NotFoundError, OfflineError)

TIMEOUT_S = 20
DOWNLOAD_TIMEOUT_S = 120

try:
    text_type = unicode  # noqa: F821
except NameError:
    text_type = str

try:
    import clr  # noqa: F401
    _DOTNET = True
except ImportError:
    _DOTNET = False


class HttpStatusError(Exception):
    def __init__(self, status, message):
        Exception.__init__(self, message)
        self.status = status


def _quote(path):
    try:
        from urllib import quote          # py2 / IronPython
    except ImportError:
        from urllib.parse import quote
    if isinstance(path, text_type):
        path = path.encode('utf-8')
    return quote(path, safe='/')


def _error_text(raw):
    try:
        if not isinstance(raw, text_type):
            raw = raw.decode('utf-8', 'replace')
        return json.loads(raw).get('error') or raw[:200]
    except Exception:
        return (raw or u'')[:200]


# ---- multipart (parts: name, filename or None, content: text or file path) ----------------
def _boundary():
    return '----PEERLibrary' + uuid.uuid4().hex


def _part_head(boundary, name, filename):
    h = u'--{0}\r\nContent-Disposition: form-data; name="{1}"'.format(boundary, name)
    if filename:
        h += u'; filename="{0}"\r\nContent-Type: application/octet-stream'.format(
            filename.replace(u'"', u''))
    return h + u'\r\n\r\n'


# ---- transport: .NET (Revit) ----------------------------------------------------
def _send_dotnet(method, url, key, json_body=None, parts=None, target=None, timeout=TIMEOUT_S):
    from System import Array, Byte
    from System.IO import File, FileMode, FileStream, StreamReader
    from System.Net import HttpWebRequest, SecurityProtocolType, ServicePointManager, WebException
    from System.Text import Encoding
    ServicePointManager.SecurityProtocol = ServicePointManager.SecurityProtocol | \
        SecurityProtocolType.Tls12
    req = HttpWebRequest.Create(url)
    req.Method = method
    req.Timeout = timeout * 1000
    req.ReadWriteTimeout = timeout * 1000
    if key:
        req.Headers.Add('Authorization', 'Bearer ' + key)
    req.UserAgent = 'PEER-Library'
    utf8 = Encoding.UTF8
    if json_body is not None:
        data = utf8.GetBytes(json.dumps(json_body, ensure_ascii=True))
        req.ContentType = 'application/json'
        req.ContentLength = data.Length
        s = req.GetRequestStream()
        s.Write(data, 0, data.Length)
        s.Close()
    elif parts is not None:
        b = _boundary()
        req.ContentType = 'multipart/form-data; boundary=' + b
        req.AllowWriteStreamBuffering = True
        s = req.GetRequestStream()
        for name, filename, content in parts:
            head = utf8.GetBytes(_part_head(b, name, filename))
            s.Write(head, 0, head.Length)
            if filename:
                fs = File.OpenRead(content)
                fs.CopyTo(s)
                fs.Close()
            else:
                d = utf8.GetBytes(content)
                s.Write(d, 0, d.Length)
            crlf = utf8.GetBytes(u'\r\n')
            s.Write(crlf, 0, crlf.Length)
        tail = utf8.GetBytes(u'--{0}--\r\n'.format(b))
        s.Write(tail, 0, tail.Length)
        s.Close()
    try:
        resp = req.GetResponse()
    except WebException as ex:
        if ex.Response is None:
            raise IOError(u'{0}'.format(ex.Message))
        r = ex.Response
        text = StreamReader(r.GetResponseStream(), utf8).ReadToEnd()
        status = int(r.StatusCode)
        r.Close()
        raise HttpStatusError(status, _error_text(text))
    try:
        if target:
            tmp = target + '.part'
            fs = FileStream(tmp, FileMode.Create)
            try:
                resp.GetResponseStream().CopyTo(fs)
            finally:
                fs.Close()
            return tmp
        return StreamReader(resp.GetResponseStream(), utf8).ReadToEnd()
    finally:
        resp.Close()


# ---- transport: urllib (tests, command line) --------------------------------------
def _send_urllib(method, url, key, json_body=None, parts=None, target=None, timeout=TIMEOUT_S):
    try:
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError, URLError
    except ImportError:
        from urllib2 import Request, urlopen, HTTPError, URLError
    headers = {'User-Agent': 'PEER-Library'}
    if key:
        headers['Authorization'] = 'Bearer ' + key
    body = None
    if json_body is not None:
        body = json.dumps(json_body, ensure_ascii=True).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    elif parts is not None:
        b = _boundary()
        buf = io.BytesIO()
        for name, filename, content in parts:
            buf.write(_part_head(b, name, filename).encode('utf-8'))
            if filename:
                with open(content, 'rb') as f:
                    buf.write(f.read())
            else:
                buf.write(content.encode('utf-8'))
            buf.write(b'\r\n')
        buf.write(u'--{0}--\r\n'.format(b).encode('utf-8'))
        body = buf.getvalue()
        headers['Content-Type'] = 'multipart/form-data; boundary=' + b
    req = Request(url, data=body, headers=headers)
    req.get_method = lambda: method
    try:
        resp = urlopen(req, timeout=timeout)
    except HTTPError as ex:
        raise HttpStatusError(ex.code, _error_text(ex.read()))
    except URLError as ex:
        raise IOError(u'{0}'.format(ex.reason))
    try:
        if target:
            tmp = target + '.part'
            with open(tmp, 'wb') as f:
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
            return tmp
        return resp.read().decode('utf-8')
    finally:
        resp.close()


def _send(*args, **kw):
    return (_send_dotnet if _DOTNET else _send_urllib)(*args, **kw)


# ---- backend ------------------------------------------------------------------------
class HttpBackend(Backend):
    kind = 'http'

    def __init__(self, cfg, key=None):
        self.cfg = cfg
        self.url = (cfg.get('url') or u'').rstrip('/')
        self.key = key if key is not None else keystore.load()
        self.user = cfg.get('user') or u''
        self.role = cfg.get('role') or u'user'

    # ---- plumbing ---------------------------------------------------------
    def has_key(self):
        return bool(self.key)

    def _call(self, method, path, json_body=None, parts=None, target=None, timeout=TIMEOUT_S,
              auth=True):
        if not self.url.startswith('https://') and not self.url.startswith('http://127.0.0.1'):
            raise LibraryError(u'The library address is not set (https://...).')
        if auth and not self.key:
            raise AccessError(u'Sign in with your PEER library key.')
        url = self.url + path
        last = None
        for attempt in (1, 2):
            try:
                return _send(method, url, self.key if auth else None, json_body, parts, target,
                             timeout)
            except HttpStatusError as ex:
                if ex.status == 401:
                    raise AccessError(u'{0}'.format(ex))
                if ex.status == 403:
                    raise AccessError(u'{0}'.format(ex))
                if ex.status == 404:
                    raise NotFoundError(u'{0}'.format(ex))
                if ex.status == 429:
                    raise LibraryError(u'{0}'.format(ex))
                if ex.status == 409:
                    raise ConflictError(u'{0}'.format(ex))
                if ex.status >= 500 and attempt == 1:
                    last = ex
                    continue
                raise LibraryError(u'{0}'.format(ex))
            except (IOError, OSError) as ex:
                last = ex
                log.write(u'http {0} {1}: {2} (attempt {3})'.format(method, path, ex, attempt))
        raise OfflineError(u'No connection to the library service ({0}).'.format(last))

    def _get_json(self, path):
        return json.loads(self._call('GET', path))

    def offline_allowed(self):
        """Cached library may be used offline for OFFLINE_DAYS after the last key check."""
        try:
            t = datetime.datetime.strptime(self.cfg.get('last_ok') or u'', '%Y-%m-%dT%H:%M:%S')
        except ValueError:
            return False
        return datetime.datetime.now() - t < datetime.timedelta(days=config.OFFLINE_DAYS)

    # ---- read -----------------------------------------------------------------
    def auth(self):
        data = self._get_json('/auth')
        self.user, self.role = data.get('name') or u'', data.get('role') or u'user'
        try:
            self.cfg = config.save_local(user=self.user, role=self.role,
                                         last_ok=datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S'))
        except Exception:
            log.write(u'save auth state', exc=True)
        return data

    def sign_in(self, key):
        """Check a key on the service; saved (DPAPI) only if it works."""
        old = self.key
        self.key = (key or u'').strip()
        try:
            data = self.auth()
        except Exception:
            self.key = old
            raise
        keystore.save(self.key)
        return data

    def get_index(self):
        return self._get_json('/index')

    def get_changelog(self):
        return self._get_json('/changelog')

    def download(self, path, target):
        folder = os.path.dirname(target)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)
        tmp = self._call('GET', '/file/' + _quote(path), target=target, timeout=DOWNLOAD_TIMEOUT_S)
        if os.path.exists(target):
            os.remove(target)
        os.rename(tmp, target)
        return target

    def next_version(self, family_id):
        low = family_id.lower()
        for c in self.get_index().get('families', []):
            if c['id'].lower() == low:
                return c['version'] + 1
        return 1

    # ---- admin ----------------------------------------------------------------
    def publish(self, card, rfa, png=None, catalog=None, note=u'', proposal_id=None):
        parts = [('card', None, json.dumps(card, ensure_ascii=True)),
                 ('note', None, note or u''),
                 ('rfa', card['id'] + '.rfa', rfa)]
        if png:
            parts.append(('png', card['id'] + '.png', png))
        if catalog:
            parts.append(('catalog', card['id'] + '.txt', catalog))
        if proposal_id:
            parts.append(('proposal_id', None, proposal_id))
        return json.loads(self._call('POST', '/publish', parts=parts, timeout=DOWNLOAD_TIMEOUT_S))

    def deprecate(self, family_id, note=u''):
        return json.loads(self._call('POST', '/deprecate', json_body={'id': family_id, 'note': note}))

    # ---- proposals ------------------------------------------------------------
    def send_proposal(self, meta, rfa=None, screenshot=None):
        parts = [('meta', None, json.dumps(meta, ensure_ascii=True))]
        if rfa:
            parts.append(('rfa', 'family.rfa', rfa))
        if screenshot:
            parts.append(('screenshot', 'screenshot.png', screenshot))
        return json.loads(self._call('POST', '/inbox', parts=parts,
                                     timeout=DOWNLOAD_TIMEOUT_S))['id']

    def list_proposals(self, include_done=False):
        return self._get_json('/inbox?done=1' if include_done else '/inbox')

    def my_proposals(self):
        return self._get_json('/inbox/mine')

    def download_proposal(self, proposal_id, target_dir):
        if not os.path.isdir(target_dir):
            os.makedirs(target_dir)
        rfa = os.path.join(target_dir, 'family.rfa')
        info = dict((p['id'], p) for p in self.list_proposals(include_done=True)).get(proposal_id, {})
        if info.get('has_file', True):
            self.download_to('/inbox/{0}/family.rfa'.format(_quote(proposal_id)), rfa)
        else:
            rfa = None
        if info.get('has_screenshot'):
            try:
                self.download_to('/inbox/{0}/screenshot.png'.format(_quote(proposal_id)),
                                 os.path.join(target_dir, 'screenshot.png'))
            except LibraryError:
                pass
        return rfa

    def download_to(self, path, target):
        tmp = self._call('GET', path, target=target, timeout=DOWNLOAD_TIMEOUT_S)
        if os.path.exists(target):
            os.remove(target)
        os.rename(tmp, target)
        return target

    def resolve_proposal(self, proposal_id, status, comment=u''):
        """rejected (comment required) / accepted - for requests and issues;
        a family proposal is accepted by publishing it."""
        return json.loads(self._call('POST', '/resolve', json_body={
            'id': proposal_id, 'status': status, 'comment': comment}))

    # ---- card info, collections, popularity ---------------------------------------
    def update_card(self, family_id, fields):
        return json.loads(self._call('POST', '/card', json_body={'id': family_id,
                                                                 'fields': fields}))

    def get_collections(self):
        return self._get_json('/collections')

    def put_collections(self, collections):
        return json.loads(self._call('PUT', '/collections',
                                     json_body={'collections': collections}))

    def get_stats(self, days=90):
        return self._get_json('/stats?days={0}'.format(int(days)))

    # ---- keys (admin) ---------------------------------------------------------
    def list_keys(self):
        return self._get_json('/keys')

    def add_key(self, name, role):
        return json.loads(self._call('POST', '/keys', json_body={'name': name, 'role': role}))

    def revoke_key(self, key_id):
        return json.loads(self._call('DELETE', '/keys/' + _quote(key_id)))

    def audit(self, limit=200):
        return self._get_json('/audit?limit={0}'.format(int(limit)))

    # ---- access requests ------------------------------------------------------
    def request_access(self, name, note=u''):
        """No key needed. Returns {'id', 'token', 'status'}; keep id + token."""
        return json.loads(self._call('POST', '/access/request', auth=False,
                                     json_body={'name': name, 'note': note}))

    def access_status(self, request_id, token):
        """{'status': pending|approved|rejected|delivered, 'key': once when delivered}."""
        return json.loads(self._call('POST', '/access/status', auth=False,
                                     json_body={'id': request_id, 'token': token}))

    def list_access_requests(self):
        return self._get_json('/access')

    def approve_access(self, request_id, role='user'):
        return json.loads(self._call('POST', '/access/approve',
                                     json_body={'id': request_id, 'role': role}))

    def reject_access(self, request_id):
        return json.loads(self._call('POST', '/access/reject', json_body={'id': request_id}))
