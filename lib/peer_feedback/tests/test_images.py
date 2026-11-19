# -*- coding: utf-8 -*-
"""Pictures in a request: payload rules (the .NET encoding runs only in Revit)."""
import base64

import pytest

from peer_feedback import client, payload

from test_feedback import CTX, FakeReceiver, home, receiver  # noqa: F401  (fixtures)

JPG = base64.b64encode(b'\xff\xd8' + b'x' * 1000 + b'\xff\xd9').decode('ascii')


def test_request_with_pictures():
    r = payload.make_request({'topic': 'bug', 'text': u'see picture', 'button': u'Walls / WallRebar2D'},
                             CTX, images=[JPG, JPG])
    assert [a['name'] for a in r['attachments']] == [u'image-1.jpg', u'image-2.jpg']
    assert all(a['type'] == u'image/jpeg' and a['data'] == JPG for a in r['attachments'])


def test_request_without_pictures_has_no_key():
    assert 'attachments' not in payload.make_request({'topic': 'idea', 'text': u'x'}, CTX)


@pytest.mark.parametrize('images', [
    [JPG] * (payload.MAX_IMAGES + 1),
    ['not base64 !'],
    [u''],
    ['A' * (payload.MAX_IMAGE_B64 + 4)],
])
def test_bad_pictures_rejected(images):
    with pytest.raises(ValueError):
        payload.make_request({'topic': 'idea', 'text': u'x'}, CTX, images=images)


def test_pictures_reach_receiver_and_use_long_timeout(receiver, monkeypatch):
    seen = {}
    real = client.post_json

    def spy(url, body, timeout_s):
        seen['timeout'] = timeout_s
        return real(url, body, timeout_s)
    monkeypatch.setattr(client, 'post_json', spy)
    r = payload.make_request({'topic': 'idea', 'text': u'x'}, CTX, images=[JPG])
    assert client.submit('request', r, receiver.cfg()) == client.SENT
    assert receiver.rows[r['id']]['attachments'][0]['data'] == JPG
    assert seen['timeout'] >= 90
