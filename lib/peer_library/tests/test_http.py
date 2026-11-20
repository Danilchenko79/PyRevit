# -*- coding: utf-8 -*-
"""Client <-> service end to end: the real worker (service/src/worker.js) runs
under node (service/test/dev_server.mjs) with in-memory R2 / D1.
Skipped when node is not on PATH."""

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, LIB)
SERVICE = os.path.join(os.path.dirname(LIB), 'service')

from peer_library import cache, config, index, keystore, rfa_info  # noqa: E402
from peer_library.backend_base import AccessError, ConflictError, OfflineError  # noqa: E402
from peer_library.backend_http import HttpBackend  # noqa: E402

NODE = shutil.which('node') if hasattr(shutil, 'which') else None


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p


@unittest.skipUnless(NODE, 'node not found')
class TestHttp(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='peerhttp_')
        self._env = dict(os.environ)
        os.environ['APPDATA'] = os.path.join(self.tmp, 'appdata')
        os.environ['LOCALAPPDATA'] = os.path.join(self.tmp, 'local')
        self.port = free_port()
        self.proc = subprocess.Popen([NODE, os.path.join(SERVICE, 'test', 'dev_server.mjs'),
                                      str(self.port)], stdout=subprocess.PIPE, cwd=SERVICE,
                                     universal_newlines=True)
        lines = {}
        while len(lines) < 3:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError('dev server did not start')
            k, v = line.strip().split(' ', 1)
            lines[k] = v
        self.admin_key, self.user_key = lines['ADMIN'], lines['USER']
        self.url = 'http://127.0.0.1:{0}'.format(self.port)

    def tearDown(self):
        self.stop()
        os.environ.clear()
        os.environ.update(self._env)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait()
        self.proc.stdout.close()

    def backend(self, key):
        cfg = config.load()
        cfg['url'] = self.url
        return HttpBackend(cfg, key=key)

    def file(self, name, data):
        p = os.path.join(self.tmp, name)
        with open(p, 'wb') as f:
            f.write(data)
        return p

    def publish(self, b, fid='PEER_Beam', data=b'rfa-1', **kw):
        card = index.new_card(id=fid, name=u'Балка', group='01_Framing', version=b.next_version(fid))
        return b.publish(card, self.file(fid + '.rfa', data), self.file(fid + '.png', b'png' + data),
                         note=kw.get('note', u''), proposal_id=kw.get('proposal_id'))

    # ---------------------------------------------------------------------
    def test_sign_in_saves_encrypted_key_and_role(self):
        b = self.backend(None)
        self.assertFalse(b.has_key())
        with self.assertRaises(AccessError):
            b.sign_in('peer_' + 'z' * 40)
        self.assertIsNone(keystore.load())
        info = b.sign_in(self.user_key)
        self.assertEqual(info['name'], 'Anna')
        self.assertEqual(keystore.load(), self.user_key)
        with open(keystore.key_file(), 'rb') as f:
            self.assertNotIn(self.user_key.encode('ascii'), f.read())   # DPAPI, not plain text
        cfg = config.load()
        self.assertEqual((cfg['role'], cfg['user']), ('user', 'Anna'))
        self.assertTrue(HttpBackend(dict(cfg, url=self.url)).offline_allowed())

    def test_publish_download_update(self):
        admin, user = self.backend(self.admin_key), self.backend(self.user_key)
        card = self.publish(admin)
        self.assertEqual(card['version'], 1)
        with self.assertRaises(AccessError):
            self.publish(user, 'PEER_Other')
        c = cache.Cache(os.path.join(self.tmp, 'cache'), user)
        idx, online = c.index()
        self.assertTrue(online)
        fam = idx['families'][0]
        p1 = c.get(fam)
        self.assertEqual(rfa_info.sha1(p1), fam['sha1'])
        self.assertTrue(c.get(fam, '.png'))
        card2 = self.publish(admin, data=b'rfa-2', note=u'вут')
        self.assertEqual(card2['version'], 2)
        idx2, _ = c.index()
        p2 = c.get(idx2['families'][0])
        # cached under the family name (Revit names the family after the file)
        self.assertEqual(os.path.basename(p2), 'PEER_Beam.rfa')
        self.assertEqual(p1, p2)
        self.assertEqual(rfa_info.sha1(p2), card2['sha1'])
        stale = index.new_card(id='PEER_Beam', group='01_Framing', version=2)
        with self.assertRaises(ConflictError):
            admin.publish(stale, self.file('x.rfa', b'x'))

    def test_index_downloaded_only_when_changed(self):
        admin, user = self.backend(self.admin_key), self.backend(self.user_key)
        self.publish(admin)
        got = []
        real = user.get_index_if_changed

        def spy(etag=None):
            data, tag = real(etag)
            got.append((etag, data is None))
            return data, tag
        user.get_index_if_changed = spy
        c = cache.Cache(os.path.join(self.tmp, 'cache'), user)
        first, _ = c.index()
        second, online = c.index()
        self.assertTrue(online)
        self.assertEqual(first, second)
        self.assertIsNone(got[0][0])                       # first time: no tag yet
        self.assertEqual((bool(got[1][0]), got[1][1]), (True, True))   # then 304
        self.publish(admin, data=b'rfa-2')
        third, _ = c.index()
        self.assertFalse(got[2][1])                         # changed: full index again
        self.assertEqual(third['families'][0]['version'], 2)
        # a damaged copy is downloaded again even if the tag still matches
        with open(os.path.join(self.tmp, 'cache', cache.INDEX_COPY), 'w') as f:
            f.write('{broken')
        self.assertEqual(c.index()[0]['families'][0]['version'], 2)
        self.assertEqual(len(c.changelog()['entries']), 2)
        self.assertEqual(len(c.changelog()['entries']), 2)  # second time from 304 + copy

    def test_proposals_and_reject(self):
        admin, user = self.backend(self.admin_key), self.backend(self.user_key)
        pid = user.send_proposal({'name': u'Балка с вутом', 'group': '01_Framing', 'kind': 'new',
                                  'reason': u'нужна'}, self.file('f.rfa', b'prop'),
                                 self.file('s.png', b'shot'))
        self.assertEqual(user.my_proposals()[0]['status'], 'pending')
        with self.assertRaises(AccessError):
            user.list_proposals()
        work = os.path.join(self.tmp, 'work')
        path = admin.download_proposal(pid, work)
        with open(path, 'rb') as f:
            self.assertEqual(f.read(), b'prop')
        self.assertTrue(os.path.isfile(os.path.join(work, 'screenshot.png')))
        self.publish(admin, 'PEER_Beam_Haunch', proposal_id=pid)
        self.assertEqual(user.my_proposals()[0]['status'], 'accepted')
        pid2 = user.send_proposal({'name': u'x'}, self.file('g.rfa', b'g'))
        admin.resolve_proposal(pid2, 'rejected', u'уже есть')
        mine = dict((p['id'], p) for p in user.my_proposals())
        self.assertEqual(mine[pid2]['comment'], u'уже есть')

    def test_package_release_end_to_end(self):
        """build -> upload -> publish; a colleague's PEER updates from stable, a
        PEER_dev beside it from beta; revoke the key -> no more updates."""
        import zipfile
        from peer_library import ext_update, pack, releases, version
        admin, user = self.backend(self.admin_key), self.backend(self.user_key)

        def package(ver, files, channel):
            src = os.path.join(self.tmp, 'src-{0}.zip'.format(ver))
            with zipfile.ZipFile(src, 'w') as z:
                for rel, data in files.items():
                    z.writestr(rel, data)
            out = os.path.join(self.tmp, 'PEER-{0}.zip'.format(ver))
            count, sha, size = pack.build(src, out, ver, channel)
            return out, sha, size

        def release(ver, files, channel, note):
            out, sha, size = package(ver, files, channel)
            admin.release_upload(releases.EXT, ver, out, sha)
            admin.release_publish(releases.EXT, ver, channel, note, sha)
            return out, sha, size

        base = {'startup.py': b's1', 'lib/peer_update.py': b'u = 1\n', 'lib/peer_library/ext_update.py': b'e = 1\n',
                'PEER.tab/bundle.yaml': b'layout', 'service/src/worker.js': b'not for colleagues',
                'PEER.tab/A.panel/B.pushbutton/OLD/x.py': b'old'}
        out, sha, size = package('2026.11.20.1', base, 'stable')
        with self.assertRaises(AccessError):
            user.release_upload(releases.EXT, '2026.11.20.1', out, sha)
        up = admin.release_upload(releases.EXT, '2026.11.20.1', out, sha)
        self.assertEqual((up['size'], up['sha1']), (size, sha))
        admin.release_publish(releases.EXT, '2026.11.20.1', 'stable', u'первый пакет', sha)

        ext = os.path.join(self.tmp, 'PEER.extension')
        dev = os.path.join(self.tmp, 'PEER_dev.extension')
        work, work_dev = os.path.join(self.tmp, 'update'), os.path.join(self.tmp, 'update_dev')
        os.makedirs(ext)
        os.makedirs(dev)
        self.assertEqual(ext_update.sync(dev, user, 'beta', work_dev)[0], 'none')      # nothing on dev yet
        status, det = ext_update.sync(ext, user, 'stable', work)
        self.assertEqual(status, 'updated', det)
        self.assertTrue(os.path.isfile(os.path.join(ext, 'PEER.tab', 'bundle.yaml')))
        self.assertFalse(os.path.exists(os.path.join(ext, 'service')))                # not packed
        self.assertFalse(os.path.exists(os.path.join(ext, 'PEER.tab', 'A.panel')))
        self.assertEqual(ext_update.sync(ext, user, 'stable', work), ('clean', u'2026.11.20.1'))

        # push to dev: PEER_dev gets it, PEER does not
        release('2026.11.20.2', dict(base, **{'startup.py': b's2_dev = 2'}), 'beta', u'проба')
        self.assertEqual(ext_update.sync(dev, user, 'beta', work_dev)[0], 'updated')
        self.assertTrue(os.path.isfile(os.path.join(dev, 'PEER_dev.tab', 'bundle.yaml')))
        self.assertFalse(os.path.exists(os.path.join(dev, 'PEER.tab')))
        self.assertEqual(version.text(dev, ''), u'2026.11.20.2 dev')
        self.assertEqual(ext_update.sync(ext, user, 'stable', work), ('clean', u'2026.11.20.1'))

        # merge to main: PEER gets it
        release('2026.11.20.3', dict(base, **{'startup.py': b's3'}), 'stable', u'второй')
        self.assertEqual(ext_update.sync(ext, user, 'stable', work)[0], 'updated')
        with open(os.path.join(ext, 'startup.py'), 'rb') as f:
            self.assertEqual(f.read(), b's3')
        self.assertEqual(ext_update.sync(dev, user, 'beta', work_dev), ('clean', u'2026.11.20.2'))

        admin.revoke_key('usr1')                       # the person left
        release('2026.11.20.4', dict(base, **{'startup.py': b's4'}), 'stable', u'третий')
        self.assertEqual(ext_update.sync(ext, user, 'stable', work)[0], 'nokey')
        with open(os.path.join(ext, 'startup.py'), 'rb') as f:
            self.assertEqual(f.read(), b's3')          # stays on what was downloaded before

    def test_template_release_end_to_end(self):
        """admin releases the template -> a colleague's computer gets the file,
        then the next version, with the note; products do not mix."""
        from peer_library import releases, template_sync
        admin, user = self.backend(self.admin_key), self.backend(self.user_key)
        folder = os.path.join(self.tmp, 'Templates')
        self.assertEqual(template_sync.sync(user, 'stable', folder)[0], 'none')
        for ver, data, note in (('1', b'rte one', u'первая версия'), ('2', b'rte two', u'исправлены фильтры')):
            f = self.file('PR_Template Concrete.rte', data)
            sha = rfa_info.sha1(f)
            admin.release_upload(releases.TEMPLATE, ver, f, sha)
            admin.release_publish(releases.TEMPLATE, ver, 'stable', note, sha, 'PR_Template Concrete.rte')
            status, det, notes = template_sync.sync(user, 'stable', folder)
            self.assertEqual(status, 'updated', det)
            self.assertEqual(notes[0], (ver, note))
            with open(template_sync.path(folder), 'rb') as fh:
                self.assertEqual(fh.read(), data)
        self.assertEqual(template_sync.installed(folder)['version'], '2')
        self.assertEqual(template_sync.sync(user, 'stable', folder)[0], 'clean')
        m, _ = user.release_manifest(releases.EXT)
        self.assertEqual(m['versions'], [])                        # the PEER package is another product

    def test_access_request_is_picked_up_without_a_window(self):
        from peer_library import access
        admin, nobody = self.backend(self.admin_key), self.backend(None)
        self.assertEqual(access.pick_up(nobody), 'none')
        r = nobody.request_access(u'Boris', u'remote office')
        keystore.save_request(r['id'], r['token'], u'Boris')
        self.assertEqual(access.pick_up(nobody), 'waiting')
        self.assertIsNone(keystore.load())
        admin.approve_access(r['id'], 'user')
        self.assertEqual(access.pick_up(nobody), 'signed')
        self.assertTrue(keystore.load().startswith('peer_'))
        self.assertIsNone(keystore.load_request())
        self.assertEqual(self.backend(keystore.load()).auth()['name'], u'Boris')
        # a declined request is forgotten
        keystore.forget()
        r = nobody.request_access(u'Chen', u'')
        keystore.save_request(r['id'], r['token'], u'Chen')
        admin.reject_access(r['id'])
        self.assertEqual(access.pick_up(self.backend(None)), 'rejected')
        self.assertIsNone(keystore.load_request())

    def test_library_panel_is_ready_right_after_signing_in(self):
        from peer_library import access
        admin = self.backend(self.admin_key)
        config.save_local(backend=u'http', url=self.url)
        admin.sign_in(self.user_key)                      # the colleague signs in on this "computer"
        self.assertFalse(access.library_ready())          # empty library: nothing to show
        self.assertTrue(access.refresh_index())
        self.assertFalse(access.library_ready())
        self.publish(self.backend(self.admin_key))
        self.assertTrue(access.refresh_index())
        self.assertTrue(access.library_ready())           # one family: the panel shows

    def test_auth_tells_the_service_the_peer_version(self):
        admin, user = self.backend(self.admin_key), self.backend(self.user_key)
        user.auth()
        row = [k for k in admin.list_keys() if k['id'] == 'usr1'][0]
        self.assertTrue(row['version'])                # 'git <sha>' or 'dev' in the working copy

    def test_keys_revoke(self):
        admin = self.backend(self.admin_key)
        k = admin.add_key(u'Борис', 'user')
        boris = self.backend(k['key'])
        self.assertEqual(boris.auth()['name'], u'Борис')
        self.assertIn(k['id'], [r['id'] for r in admin.list_keys()])
        admin.revoke_key(k['id'])
        with self.assertRaises(AccessError):
            boris.auth()
        self.assertEqual(self.backend(self.user_key).auth()['role'], 'user')

    def test_request_access_flow(self):
        newbie, admin = self.backend(None), self.backend(self.admin_key)
        r = newbie.request_access(u'Борис', u'удалённо')
        keystore.save_request(r['id'], r['token'], u'Борис')
        self.assertEqual(keystore.load_request()[2], u'Борис')
        self.assertEqual(newbie.access_status(r['id'], r['token'])['status'], 'pending')
        self.assertEqual([x['name'] for x in admin.list_access_requests()], [u'Борис'])
        admin.approve_access(r['id'], 'user')
        st = newbie.access_status(r['id'], r['token'])
        self.assertEqual(st['status'], 'delivered')
        info = newbie.sign_in(st['key'])
        self.assertEqual((info['name'], info['role']), (u'Борис', 'user'))
        self.assertEqual(keystore.load(), st['key'])
        self.assertNotIn('key', newbie.access_status(r['id'], r['token']))

    def test_card_info_collections_stats_requests(self):
        admin, user = self.backend(self.admin_key), self.backend(self.user_key)
        self.publish(admin)
        with self.assertRaises(AccessError):
            user.update_card('PEER_Beam', {'name': u'x'})
        c = admin.update_card('PEER_Beam', {'name': u'Балка', 'tags': [u'балка'], 'types': ['B1']})
        self.assertEqual((c['name'], c['version'], c['types']), (u'Балка', 1, ['B1']))
        admin.put_collections([{'name': u'Старт', 'families': ['PEER_Beam']}])
        cc = cache.Cache(os.path.join(self.tmp, 'cache'), user)
        self.assertEqual(cc.collections()[0]['families'], ['PEER_Beam'])
        idx, _ = cc.index()
        cc.get(idx['families'][0])
        self.assertEqual(cc.stats()['PEER_Beam']['downloads'], 1)
        pid = user.send_proposal({'kind': 'request', 'name': u'Анкер M24', 'reason': u'нужен'})
        self.assertIsNone(admin.download_proposal(pid, os.path.join(self.tmp, 'w')))
        admin.resolve_proposal(pid, 'accepted', u'добавлен')
        self.assertEqual(user.my_proposals()[0]['status'], 'accepted')
        self.stop()
        self.assertEqual(cc.collections()[0]['name'], u'Старт')      # offline: saved copy

    def test_offline_grace(self):
        admin, user = self.backend(self.admin_key), self.backend(None)
        self.publish(admin)
        user.sign_in(self.user_key)
        c = cache.Cache(os.path.join(self.tmp, 'cache'), user)
        idx, _ = c.index()
        fam = idx['families'][0]
        c.get(fam)
        self.stop()                                    # service unreachable
        idx2, online = c.index()
        self.assertFalse(online)
        self.assertTrue(os.path.isfile(c.get(fam)))
        with self.assertRaises(OfflineError):
            c.get(dict(fam, id='PEER_X', sha1='0' * 40, files={'.rfa': '01_Framing/PEER_X/v1.rfa'}))
        user.cfg['last_ok'] = '2020-01-01T00:00:00'    # checked too long ago
        with self.assertRaises(AccessError):
            c.index()


if __name__ == '__main__':
    unittest.main()
