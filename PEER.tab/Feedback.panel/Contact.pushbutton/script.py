# -*- coding: utf-8 -*-
__title__ = "Contact"
__author__ = "Dima D"
__doc__ = """WHAT IT DOES
Sends a request, an idea or a bug report to the head of the group.
The request lands as a row in the group's table; its status
(accepted / in progress / done) comes back to PEER.

HOW TO USE
1. Pick a topic. For "Improve a button" and "Bug" pick the button too.
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

import os

from pyrevit import forms, script

from System.Windows import Visibility

from peer_feedback import config, texts, payload, client, context, outbox

ACTION = 'request'


def _tab_dir():
    # .../PEER.tab/Feedback.panel/Contact.pushbutton/script.py -> PEER.tab
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(os.path.dirname(here))


class ContactWindow(forms.WPFWindow):
    def __init__(self, xaml_path, ctx, buttons, topic=None, button=None):
        forms.WPFWindow.__init__(self, xaml_path)
        self.ctx = ctx
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
        self.btn_ok.Content = t('send')
        self.btn_cancel.Content = t('cancel')
        self.tb_context.Text = context.describe(ctx)

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

        codes = [c for c, _l, _h in self.topics]
        self.cb_topic.SelectedIndex = codes.index(topic) if topic in codes else 0
        self._update_topic()
        self.tb_text.Focus()

    # --- events ---
    def on_topic_changed(self, sender, args):
        self._update_topic()

    def _update_topic(self):
        i = self.cb_topic.SelectedIndex
        if i < 0:
            return
        code, _label, hint = self.topics[i]
        self.lbl_hint.Text = hint
        show = code in texts.TOPICS_WITH_BUTTON
        self.pnl_button.Visibility = Visibility.Visible if show else Visibility.Collapsed

    def _fields(self):
        code = self.topics[max(0, self.cb_topic.SelectedIndex)][0]
        button = u''
        if code in texts.TOPICS_WITH_BUTTON:
            button = self.buttons[max(0, self.cb_button.SelectedIndex)]
        return {
            'topic': code,
            'text': self.tb_text.Text or u'',
            'button': button,
            'frequency': self.freq[max(0, self.cb_frequency.SelectedIndex)][0],
            'duration': self.dur[max(0, self.cb_duration.SelectedIndex)][0],
        }

    def on_ok(self, sender, args):
        fields = self._fields()
        errors = payload.validate(fields)
        if errors:
            forms.alert(u'\n'.join(texts.s(e) for e in errors),
                        title=u'PEER - Contact')
            return
        self.result = fields
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
        forms.alert(text, title=u'PEER - connection ' + (u'OK' if ok else u'FAILED'))
    elif pick.startswith(u'Send'):
        sent, left = client.flush(cfg)
        forms.alert(u'Sent: {0}. Still queued: {1}.'.format(sent, left),
                    title=u'PEER - Contact')
    else:
        url = forms.ask_for_string(
            default=cfg['url'], title=u'PEER - receiver address',
            prompt=u'Web app address of the receiver (Apps Script -> Deploy -> '
                   u'Web app URL, ends with /exec). Stored on this computer only.')
        if url is None:
            return
        key = forms.ask_for_string(
            default=cfg['key'], title=u'PEER - receiver key',
            prompt=u'Key = Script Property PEER_KEY of the receiver.')
        if key is None:
            return
        cfg = config.save_local(url=url.strip(), key=key.strip())
        ok, text = client.ping(cfg)
        if ok:
            sent, left = client.flush(cfg)
            text += u'\nQueued requests sent: {0}, left: {1}.'.format(sent, left)
        forms.alert(text, title=u'PEER - connection ' + (u'OK' if ok else u'FAILED'))


# ------------------------------------------------------------------- main --
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
    win = ContactWindow(script.get_bundle_file('ContactForm.xaml'), ctx, buttons)
    win.ShowDialog()
    if not win.DialogResult or not win.result:
        return

    req = payload.make_request(win.result, ctx)
    status = client.submit(ACTION, req, cfg)
    if status == client.SENT:
        forms.alert(texts.s('sent'), title=u'PEER - Contact')
    elif status == client.NOT_CONFIGURED:
        forms.alert(texts.s('not_configured'), title=u'PEER - Contact')
    else:
        forms.alert(texts.s('queued'), title=u'PEER - Contact')


main()
