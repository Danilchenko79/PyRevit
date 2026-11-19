# -*- coding: utf-8 -*-
"""peer_feedback without Revit: payload, outbox, config, client over real HTTP."""
import io
import json
import os
import threading

try:
    from http.server import BaseHTTPRequestHandler, HTTPServer
except ImportError:  # pragma: no cover
    from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer

import pytest

from peer_feedback import client, config, outbox, payload, texts

LIB = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TAB = os.path.join(os.path.dirname(LIB), 'PEER.tab')

CTX = {'user': u'Дима', 'machine': u'PC-01', 'project': u'בניין A',
       'revit_version': u'2024.2', 'pyrevit_version': u'4.8.16',
       'peer_version': u'2f5f2f8', 'view': u'Level 1 (FloorPlan)',
       'selection': u'Walls x3', 'error_script': u'', 'error_text': u''}


@pytest.fixture
def home(tmp_path, monkeypatch):
    """%APPDATA% and %TEMP% in a temp folder; no repo settings."""
    monkeypatch.setenv('APPDATA', str(tmp_path / 'appdata'))
    monkeypatch.setenv('TEMP', str(tmp_path / 'temp'))
    monkeypatch.setattr(config, 'REPO_FILE', str(tmp_path / 'repo_settings.json'))
    return tmp_path


# ---------------------------------------------------------------- payload --

def test_make_request_fields_and_unicode():
    r = payload.make_request(
        {'topic': 'automation', 'text': u'  Хочу кнопку для разрезов  ',
         'frequency': 'weekly', 'duration': '5to30'},
        CTX, request_id='a' * 32, created_at=u'2026-11-19T10:00:00Z')
    assert r['id'] == 'a' * 32
    assert r['text'] == u'Хочу кнопку для разрезов'
    assert r['project'] == u'בניין A'
    assert r['button'] == u''
    assert set(r) == set(('id', 'created_at') + payload.USER_FIELDS + payload.CONTEXT_FIELDS)
    json.dumps(r, ensure_ascii=False)


def test_make_request_clips_long_text():
    r = payload.make_request({'topic': 'idea', 'text': u'x' * 9000}, CTX)
    assert len(r['text']) == payload.MAX_TEXT
    assert r['text'].endswith(u'…')
    assert len(r['id']) == 32


@pytest.mark.parametrize('fields', [
    {'topic': 'nope', 'text': u'x'},
    {'topic': 'idea', 'text': u'x', 'frequency': 'hourly'},
    {'topic': 'idea', 'text': u'x', 'duration': '1h'},
])
def test_make_request_rejects_unknown_codes(fields):
    with pytest.raises(ValueError):
        payload.make_request(fields, CTX)


def test_validate():
    assert payload.validate({'topic': 'idea', 'text': u'  '}) == ['err_text']
    assert payload.validate({'topic': 'bug', 'text': u'crash', 'button': u''}) == ['err_button']
    assert payload.validate({'topic': 'bug', 'text': u'crash', 'button': u'Walls / WallRebar2D'}) == []
    for e in ('err_text', 'err_button'):
        assert texts.s(e, 'ru') and texts.s(e, 'en')


def test_texts_complete_for_both_languages():
    for key, d in texts.STRINGS.items():
        assert d.get('en') and d.get('ru'), key
    for code, t in texts.TOPICS:
        assert t['en'][0] and t['ru'][0], code
    assert texts.norm_lang('he') == 'en'
    # receiver checks topics against its own list - keep them identical
    gs = io.open(os.path.join(os.path.dirname(LIB), 'feedback', 'receiver', 'Code.gs'),
                 encoding='utf-8').read()
    for code in texts.TOPIC_CODES:
        assert "'%s'" % code in gs


def test_list_buttons_real_tab():
    names = payload.list_buttons(TAB)
    assert u'Feedback / Contact' in names
    assert u'Documentation / WinTag' in names          # .stack level dropped
    assert any(n.startswith(u'Reinforcement / RebarShape / ') for n in names)
    assert not any(u'.pushbutton' in n or u'.panel' in n for n in names)
    assert names == sorted(names, key=lambda x: x.lower())


# ----------------------------------------------------------------- outbox --

def test_outbox_put_items_remove(tmp_path):
    base = str(tmp_path)
    a = {'action': 'request', 'data': {'id': 'a' * 32, 'text': u'один'}}
    b = {'action': 'request', 'data': {'id': 'b' * 32, 'text': u'два'}}
    pa = outbox.put(a, base)
    os.utime(pa, (1, 1))                       # a is older
    outbox.put(b, base)
    got = outbox.items(base)
    assert [it['data']['id'] for _, it in got] == ['a' * 32, 'b' * 32]
    assert got[0][1]['data']['text'] == u'один'
    outbox.put(a, base)                        # same id overwrites, no duplicate
    assert outbox.count(base) == 2
    assert outbox.remove(got[1][0])
    assert outbox.count(base) == 1


def test_outbox_skips_broken_file_and_bad_id(tmp_path):
    base = str(tmp_path)
    os.makedirs(outbox.folder(base))
    with open(os.path.join(outbox.folder(base), 'broken.json'), 'w') as f:
        f.write('{not json')
    assert outbox.items(base) == []
    with pytest.raises(ValueError):
        outbox.put({'action': 'request', 'data': {'id': '../..'}}, base)


def test_outbox_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(outbox, 'MAX_ITEMS', 2)
    base = str(tmp_path)
    for c in 'abc':
        outbox.put({'action': 'request', 'data': {'id': c * 32}}, base)
    assert outbox.count(base) == 2


# ----------------------------------------------------------------- config --

def test_config_local_overrides_repo(home):
    with io.open(config.REPO_FILE, 'w', encoding='utf-8') as f:
        f.write(u'{"url": "https://repo/exec", "key": "repokey", "lang": "ru"}')
    cfg = config.load()
    assert (cfg['url'], cfg['key'], cfg['lang']) == ('https://repo/exec', 'repokey', 'ru')
    assert config.is_configured(cfg)
    cfg = config.save_local(key=u'localkey', bogus=1)
    assert (cfg['url'], cfg['key']) == ('https://repo/exec', 'localkey')
    assert 'bogus' not in json.load(io.open(config.local_file(), encoding='utf-8'))


def test_config_defaults_and_http_not_allowed(home):
    cfg = config.load()
    assert cfg['url'] == u'' and not config.is_configured(cfg)
    assert not config.is_configured(dict(cfg, url='http://x/exec', key='k'))


def test_repo_settings_file_ships_empty():
    """The public repo must not carry a key by accident."""
    data = json.load(io.open(os.path.join(LIB, 'peer_feedback', 'settings.json'), encoding='utf-8'))
    assert data.get('key', '') == ''


def test_peer_version(tmp_path):
    git = tmp_path / '.git'
    (git / 'refs' / 'heads').mkdir(parents=True)
    (git / 'HEAD').write_text(u'ref: refs/heads/main\n')
    (git / 'refs' / 'heads' / 'main').write_text(u'2f5f2f8abcdef\n')
    assert config.peer_version(str(tmp_path)) == '2f5f2f8'
    (git / 'refs' / 'heads' / 'main').unlink()
    (git / 'packed-refs').write_text(u'# pack\n68e9e31ffff refs/heads/main\n')
    assert config.peer_version(str(tmp_path)) == '68e9e31'
    assert config.peer_version(str(tmp_path / 'none')) == 'unknown'


# --------------------------------------------- client over a fake receiver --

class FakeReceiver(object):
    """Behaves like feedback/receiver/Code.gs doPost (key, ping, dedupe)."""

    def __init__(self, key='k1'):
        self.key = key
        self.rows = {}
        self.calls = 0
        self.down = False
        rec = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                rec.calls += 1
                n = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(n).decode('utf-8'))
                if rec.down:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(b'<html>Google error</html>')
                    return
                if body.get('key') != rec.key:
                    ans = {'ok': False, 'error': 'bad_key'}
                elif body['action'] == 'ping':
                    ans = {'ok': True, 'pong': True}
                elif body['action'] == 'request':
                    d = body['data']
                    if not d.get('text'):
                        ans = {'ok': False, 'error': 'bad_request', 'detail': 'empty text'}
                    else:
                        dup = d['id'] in rec.rows
                        rec.rows[d['id']] = d
                        ans = {'ok': True, 'id': d['id'], 'duplicate': dup}
                else:
                    ans = {'ok': False, 'error': 'bad_request'}
                out = json.dumps(ans).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        self.server = HTTPServer(('127.0.0.1', 0), H)
        self.url = 'http://127.0.0.1:%d/exec' % self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.thread.start()

    def cfg(self, key=None):
        # is_configured() insists on https; tests talk plain http to localhost
        return {'url': self.url, 'key': key or self.key, 'lang': 'en', 'timeout_s': 5}

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def receiver(home, monkeypatch):
    monkeypatch.setattr(config, 'is_configured',
                        lambda cfg=None: bool((cfg or config.load())['url']) and bool((cfg or config.load())['key']))
    r = FakeReceiver()
    yield r
    r.close()


def _req(text=u'Хочу кнопку'):
    return payload.make_request({'topic': 'automation', 'text': text}, CTX)


def test_submit_sent_removes_from_outbox(receiver):
    req = _req()
    assert client.submit('request', req, receiver.cfg()) == client.SENT
    assert receiver.rows[req['id']]['text'] == u'Хочу кнопку'
    assert receiver.rows[req['id']]['project'] == u'בניין A'
    assert outbox.count() == 0


def test_submit_offline_then_flush_once(receiver):
    req = _req()
    offline = dict(receiver.cfg(), url='http://127.0.0.1:1/exec')
    assert client.submit('request', req, offline) == client.QUEUED
    assert outbox.count() == 1
    sent, left = client.flush(receiver.cfg())
    assert (sent, left) == (1, 0)
    assert list(receiver.rows) == [req['id']]
    assert client.flush(receiver.cfg()) == (0, 0)


def test_bad_key_keeps_item(receiver):
    assert client.submit('request', _req(), receiver.cfg(key='old')) == client.QUEUED
    assert outbox.count() == 1 and not receiver.rows
    assert client.flush(receiver.cfg()) == (1, 0)


def test_bad_request_is_dropped(receiver):
    req = _req()
    req['text'] = u''
    assert client.submit('request', req, receiver.cfg()) == client.QUEUED
    assert outbox.count() == 0


def test_receiver_html_error_keeps_item_and_stops_flush(receiver):
    receiver.down = True
    for _ in range(3):
        client.submit('request', _req(), receiver.cfg())
    calls = receiver.calls
    assert client.flush(receiver.cfg()) == (0, 3)
    assert receiver.calls == calls + 1          # stopped after the first failure
    receiver.down = False
    assert client.flush(receiver.cfg()) == (3, 0)
    assert len(receiver.rows) == 3


def test_not_configured_queues(home):
    assert client.submit('request', _req(), config.load()) == client.NOT_CONFIGURED
    assert outbox.count() == 1
    assert client.flush() == (0, 1)


def test_ping(receiver):
    ok, text = client.ping(receiver.cfg())
    assert ok and 'ms' in text
    ok, text = client.ping(receiver.cfg(key='wrong'))
    assert not ok and 'bad_key' in text


def test_flush_async_in_background(receiver, monkeypatch):
    client.submit('request', _req(), dict(receiver.cfg(), url='http://127.0.0.1:1/exec'))
    monkeypatch.setattr(config, 'load', lambda: dict(receiver.cfg()))
    t = client.flush_async()
    assert t is not None
    t.join(10)
    assert outbox.count() == 0 and len(receiver.rows) == 1


def test_receiver_gs_contract():
    """Code.gs in node with fake Google services. Skipped without node."""
    import shutil
    import subprocess
    node = shutil.which('node')
    if not node:
        pytest.skip('node not installed')
    js = os.path.join(os.path.dirname(LIB), 'feedback', 'receiver', 'test_receiver.js')
    res = subprocess.run([node, js], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stdout + res.stderr
