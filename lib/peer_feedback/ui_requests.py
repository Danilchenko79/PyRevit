# -*- coding: utf-8 -*-
"""My requests: the requests sent with Feedback from this computer and their
status set by the head of the group (New, Accepted, In progress, Done,
Rejected - with a short comment). Opened from the Feedback window.

The status is fetched from the group's table when the window opens (Refresh
fetches it again). Without internet the last known status is shown. Requests
not sent yet show "Waiting to send".
"""

import clr

from pyrevit import forms

# System.Data is not loaded in Revit 2024 by default ("No module named Data")
clr.AddReference('System.Data')
from System.Data import DataTable  # noqa: E402

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
    queued = outbox.ids()
    rejected = outbox.rejected_ids()
    labels = dict((c, l) for c, l, _h in texts.TOPICS)
    table = DataTable()
    for col in sent.COLUMNS:
        table.Columns.Add(col)
    for row in sent.table_rows(sent.items(), queued, labels, _local_text, rejected):
        r = table.NewRow()
        for col, val in zip(sent.COLUMNS, row):
            r[col] = val
        table.Rows.Add(r)
    return table


class MyRequestsWindow(forms.WPFWindow):
    """Shows the last known statuses at once, fetches new ones in a thread."""

    def __init__(self, xaml_path):
        forms.WPFWindow.__init__(self, xaml_path)
        self.busy = False
        self.closed = False
        self.Closed += self._on_closed
        self.show_table()
        self.load()

    def show_table(self):
        from System.Windows import Visibility
        table = build_table()
        self.grid.ItemsSource = table.DefaultView
        self.lbl_empty.Visibility = Visibility.Collapsed if table.Rows.Count else Visibility.Visible

    def load(self):
        import threading
        from System import TimeSpan
        from System.Windows.Threading import DispatcherTimer
        if self.busy:
            return
        self.busy = True
        self.btn_refresh.IsEnabled = False
        self.lbl_note.Text = u'Updating statuses...'
        box = {}

        def run():
            try:
                box['note'] = refresh()
            except Exception as ex:
                box['note'] = u'Update failed: {0}'.format(ex)

        worker = threading.Thread(target=run, name='peer_myrequests_refresh')
        worker.daemon = True
        worker.start()
        timer = DispatcherTimer()
        timer.Interval = TimeSpan.FromMilliseconds(200)

        def tick(s, e):
            if worker.is_alive():
                return
            timer.Stop()
            self.busy = False
            if self.closed:
                return
            self.lbl_note.Text = box.get('note', u'')
            self.btn_refresh.IsEnabled = True
            self.show_table()

        timer.Tick += tick
        timer.Start()

    def on_refresh(self, sender, args):
        self.load()

    def on_close(self, sender, args):
        self.Close()

    def _on_closed(self, sender, args):
        self.closed = True


def show(xaml_path, owner=None):
    win = MyRequestsWindow(xaml_path)
    if owner is not None:
        win.Owner = owner
    win.ShowDialog()
