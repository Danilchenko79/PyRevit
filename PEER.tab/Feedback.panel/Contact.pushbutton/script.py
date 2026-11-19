# -*- coding: utf-8 -*-
__title__ = "Contact"
__author__ = "Dima D"
__doc__ = """WHAT IT DOES
Sends a request, an idea or a bug report to the head of the group.
The request lands as a row in the group's table; its status
(accepted / in progress / done) comes back to PEER.

HOW TO USE
1. Pick a topic. For "Improve a button" and "Bug" pick the button too.
   Bug: pick the error from the list - the button and the full error
   text are filled in (a PEER error of the last 15 minutes is picked
   already). Text is then optional: Contact -> Send.
2. Describe what you need in a few sentences.
3. Optional: how often it happens and how long it takes each time -
   this is how requests are prioritised.
4. Send. Project, view, selected categories and versions are attached
   automatically (shown at the bottom of the window). No files, no
   geometry, no parameter values.

Works in the office and from home: no network drive needed. Without
internet the request is saved on this computer and sent automatically
on the next Revit start.

Shift+Click: check the connection, send queued requests, set the
receiver address and key.
"""

import datetime
import os

from pyrevit import forms, script

from System.Windows import Visibility

from peer_feedback import config, texts, payload, client, context, outbox, runs, sent

ACTION = 'request'
TITLE = u'PEER - Contact'
# a PEER error this fresh opens Contact on "Bug" with it picked
FRESH_ERROR_MIN = 15


def _tab_dir():
    # .../PEER.tab/Feedback.panel/Contact.pushbutton/script.py -> PEER.tab
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(os.path.dirname(here))


class ContactWindow(forms.WPFWindow):
    def __init__(self, xaml_path, ctx, buttons, fails, topic=None, button=None, error=0):
        forms.WPFWindow.__init__(self, xaml_path)
        self.ctx = ctx
        self.fails = list(fails)
        self.result = None
        t = texts.s

        self.Title = u'PEER - ' + t('title')
        self.lbl_title.Text = t('title')
        self.lbl_howto.Text = t('how_to')
        self.lbl_topic.Text = t('topic')
        self.lbl_button.Text = t('button')
        self.lbl_text.Text = t('text')
        self.lbl_frequency.Text = t('frequency')
        self.lbl_duration.Text = t('duration')
        self.lbl_context.Text = t('context')
        self.lbl_error.Text = t('error')
        self.lbl_error_hint.Text = t('error_hint')
        self.btn_ok.Content = t('send')
        self.btn_cancel.Content = t('cancel')

        self.topics = texts.TOPICS
        for _, label, _h in self.topics:
            self.cb_topic.Items.Add(label)

        self.buttons = [u''] + list(buttons)
        self.cb_button.Items.Add(t('no_button'))
        for b in buttons:
            self.cb_button.Items.Add(b)
        self.cb_button.SelectedIndex = 0
        if button and button in self.buttons:
            self.cb_button.SelectedIndex = self.buttons.index(button)

        self.freq = texts.FREQUENCY
        for _, label in self.freq:
            self.cb_frequency.Items.Add(label)
        self.cb_frequency.SelectedIndex = 0
        self.dur = texts.DURATION
        for _, label in self.dur:
            self.cb_duration.Items.Add(label)
        self.cb_duration.SelectedIndex = 0

        self.cb_error.Items.Add(t('no_error'))
        for f in self.fails:
            self.cb_error.Items.Add(runs.label(f))
        self.cb_error.SelectedIndex = error if 0 <= error <= len(self.fails) else 0

        codes = [c for c, _l, _h in self.topics]
        self.cb_topic.SelectedIndex = codes.index(topic) if topic in codes else 0
        self._update_topic()
        self._update_error()
        self.tb_text.Focus()

    # --- events ---
    def on_topic_changed(self, sender, args):
        self._update_topic()

    def on_error_changed(self, sender, args):
        self._update_error(pick_button=True)

    def _error(self):
        """The picked failure (only under Bug) or None."""
        i = self.cb_error.SelectedIndex
        if self._topic() != 'bug' or i < 1 or i > len(self.fails):
            return None
        return self.fails[i - 1]

    def _topic(self):
        return self.topics[max(0, self.cb_topic.SelectedIndex)][0]

    def _context(self):
        ctx = dict(self.ctx)
        f = self._error()
        ctx['error_script'] = f['script'] if f else u''
        ctx['error_text'] = f['error'] if f else u''
        return ctx

    def _update_error(self, pick_button=False):
        f = self._error()
        if f and pick_button and f['button'] in self.buttons:
            self.cb_button.SelectedIndex = self.buttons.index(f['button'])
        ctx = self._context()
        text = context.describe(ctx)
        if f:
            text += u'\nError: {0}'.format(runs.summary(f['error']) or f['script'])
        self.tb_context.Text = text
        self.lbl_text.Text = texts.s('text_bug' if f else 'text')

    def _update_topic(self):
        i = self.cb_topic.SelectedIndex
        if i < 0:
            return
        code, _label, hint = self.topics[i]
        self.lbl_hint.Text = hint
        show = code in texts.TOPICS_WITH_BUTTON
        self.pnl_button.Visibility = Visibility.Visible if show else Visibility.Collapsed
        bug = code == 'bug' and bool(self.fails)
        self.pnl_error.Visibility = Visibility.Visible if bug else Visibility.Collapsed
        self._update_error()

    def _fields(self):
        code = self.topics[max(0, self.cb_topic.SelectedIndex)][0]
        button = u''
        if code in texts.TOPICS_WITH_BUTTON:
            button = self.buttons[max(0, self.cb_button.SelectedIndex)]
        return {
            'topic': code,
            'text': self.tb_text.Text or u'',
            'error_text': self._context()['error_text'],
            'button': button,
            'frequency': self.freq[max(0, self.cb_frequency.SelectedIndex)][0],
            'duration': self.dur[max(0, self.cb_duration.SelectedIndex)][0],
        }

    def on_ok(self, sender, args):
        fields = self._fields()
        errors = payload.validate(fields)
        if errors:
            forms.alert(u'\n'.join(texts.s(e) for e in errors), title=TITLE)
            return
        self.result = fields
        self.result_context = self._context()
        self.DialogResult = True
        self.Close()

    def on_cancel(self, sender, args):
        self.DialogResult = False
        self.Close()


# ------------------------------------------------------------ Shift+Click --
def _settings():
    cfg = config.load()
    queued = outbox.count()
    opts = [u'Check connection',
            u'Send queued requests now ({0})'.format(queued),
            u'Receiver address and key']
    state = u'set' if config.is_configured(cfg) else u'NOT SET'
    pick = forms.CommandSwitchWindow.show(
        opts, message=u'Receiver: {0}.  Queued on this computer: {1}.'.format(state, queued),
        title=u'PEER - Contact settings')
    if not pick:
        return
    if pick.startswith(u'Check'):
        ok, text = client.ping(cfg)
        forms.alert(text, title=u'PEER - connection ' + (u'OK' if ok else u'FAILED'),
                    warn_icon=not ok)
    elif pick.startswith(u'Send'):
        n_sent, left = client.flush(cfg)
        forms.alert(u'Sent: {0}. Still queued: {1}.'.format(n_sent, left),
                    title=TITLE, warn_icon=bool(left))
    else:
        url = forms.ask_for_string(
            default=cfg['url'], title=u'PEER - receiver address',
            prompt=u'Receiver URL (ends with /exec):')
        if url is None:
            return
        key = forms.ask_for_string(
            default=cfg['key'], title=u'PEER - receiver key',
            prompt=u'Receiver key (PEER_KEY):')
        if key is None:
            return
        cfg = config.save_local(url=url.strip(), key=key.strip())
        ok, text = client.ping(cfg)
        if ok:
            n_sent, left = client.flush(cfg)
            text += u'\nQueued requests sent: {0}, left: {1}.'.format(n_sent, left)
        forms.alert(text, title=u'PEER - connection ' + (u'OK' if ok else u'FAILED'),
                    warn_icon=not ok)


# ------------------------------------------------------------------- main --
def _recent_failures():
    try:
        return runs.recent_failures()
    except Exception:
        return []


def main():
    try:
        shift = __shiftclick__  # noqa: F821
    except NameError:
        shift = False
    if shift:
        _settings()
        return

    cfg = config.load()
    ctx = context.collect(__revit__)  # noqa: F821
    buttons = payload.list_buttons(_tab_dir())
    fails = _recent_failures()
    topic, error = None, 0
    if fails:
        age = datetime.datetime.utcnow() - fails[0]['time']
        if age < datetime.timedelta(minutes=FRESH_ERROR_MIN):
            topic, error = 'bug', 1
    win = ContactWindow(script.get_bundle_file('ContactForm.xaml'), ctx, buttons, fails,
                        topic=topic, error=error)
    if error:
        win._update_error(pick_button=True)
    win.ShowDialog()
    if not win.DialogResult or not win.result:
        return

    req = payload.make_request(win.result, win.result_context)
    status = client.submit(ACTION, req, cfg)
    try:
        sent.add(req)
    except Exception:
        pass
    if status == client.SENT:
        forms.alert(texts.s('sent'), title=TITLE, warn_icon=False)
    elif status == client.NOT_CONFIGURED:
        forms.alert(texts.s('not_configured'), title=TITLE)
    else:
        forms.alert(texts.s('queued'), title=TITLE)


main()
