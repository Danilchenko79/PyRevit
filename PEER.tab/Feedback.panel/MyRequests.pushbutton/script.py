# -*- coding: utf-8 -*-
__title__ = "My\nRequests"
__author__ = "Dima D"
__doc__ = """WHAT IT DOES
Shows the requests you sent with Contact from this computer and their
status set by the head of the group: New, Accepted, In progress, Done,
Rejected - with a short comment.

The status is fetched from the group's table when the window opens
(Refresh fetches it again). Without internet the last known status is
shown. Requests not sent yet show "Waiting to send".
"""

from pyrevit import forms, script

from System.Data import DataTable

from peer_feedback import client, config, outbox, runs, sent, texts
from peer_feedback.transport import SendError

TITLE = u'PEER - My requests'


def _local_text(utc_text):
    t = runs.parse_time(utc_text)
    return runs.to_local(t).strftime('%d.%m.%Y %H:%M') if t else utc_text


def refresh():
    """Fetch statuses -> note line for the window."""
    cfg = config.load()
    entries = sent.items()
    if not entries:
        return u'No requests sent from this computer yet.'
    if not config.is_configured(cfg):
        return u'The receiver is not set up on this computer - showing the last known status.'
    try:
        changed = sent.merge(client.statuses([x['id'] for x in entries], cfg))
    except SendError as ex:
        if u'bad_request' in u'{0}'.format(ex):
            return (u'The receiver does not report statuses yet - the head of the group '
                    u'needs to update it (feedback/SETUP.md). Showing the last known status.')
        return u'No connection to the receiver - showing the last known status.'
    if changed:
        return u'Updated just now: {0} request(s) changed.'.format(len(changed))
    return u'Updated just now.'


def build_table():
    queued = set()
    for _path, item in outbox.items():
        try:
            queued.add(item['data']['id'])
        except (KeyError, TypeError):
            pass
    labels = dict((c, l) for c, l, _h in texts.TOPICS)
    table = DataTable()
    for col in sent.COLUMNS:
        table.Columns.Add(col)
    for row in sent.table_rows(sent.items(), queued, labels, _local_text):
        r = table.NewRow()
        for col, val in zip(sent.COLUMNS, row):
            r[col] = val
        table.Rows.Add(r)
    return table


class MyRequestsWindow(forms.WPFWindow):
    def __init__(self, xaml_path):
        forms.WPFWindow.__init__(self, xaml_path)
        self.load()

    def load(self):
        from System.Windows import Visibility
        note = refresh()
        self.lbl_note.Text = note
        table = build_table()
        self.grid.ItemsSource = table.DefaultView
        self.lbl_empty.Visibility = Visibility.Collapsed if table.Rows.Count else Visibility.Visible

    def on_refresh(self, sender, args):
        self.load()

    def on_close(self, sender, args):
        self.Close()


MyRequestsWindow(script.get_bundle_file('MyRequestsForm.xaml')).ShowDialog()
