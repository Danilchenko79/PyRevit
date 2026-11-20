# -*- coding: utf-8 -*-
__title__ = "Feedback"
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

from peer_feedback import config, texts, payload, client, context, outbox, runs, sent, images

ACTION = 'request'
TITLE = u'PEER - Contact'
# a PEER error this fresh opens Contact on "Bug" with it picked
FRESH_ERROR_MIN = 15
# window closed while the request was still being sent
BACKGROUND = 'background'


def _tab_dir():
    # .../PEER.tab/Feedback.panel/<stack>/Contact.pushbutton/script.py -> PEER.tab
    here = os.path.dirname(os.path.abspath(__file__))
    while here and not here.lower().endswith('.tab'):      # the button may sit in a stack
        up = os.path.dirname(here)
        if up == here:
            break
        here = up
    return here


class ContactWindow(forms.WPFWindow):
    def __init__(self, xaml_path, cfg, ctx, buttons, fails, topic=None, button=None, error=0):
        forms.WPFWindow.__init__(self, xaml_path)
        self.cfg = cfg
        self.ctx = ctx
        self.fails = list(fails)
        self.request = None       # the request dict once Send was pressed
        self.status = None        # client.SENT / QUEUED / ... / BACKGROUND
        self.sending = False
        self.closed = False
        self.images = []          # [(BitmapSource, base64 JPEG)]
        self.Closed += self._on_closed
        t = texts.s

        self.Title = TITLE
        self.lbl_title.Text = t('title')
        self.lbl_howto.Text = t('how_to')
        self.lbl_topic.Text = t('topic')
        self.lbl_button.Text = t('button')
        self.lbl_placeholder.Text = t('placeholder')
        self.lbl_images.Text = t('images')
        self.lbl_images_hint.Text = t('images_hint')
        self.btn_add_image.Content = t('add_image')
        self.lbl_frequency.Text = t('frequency')
        self.lbl_duration.Text = t('duration')
        self.exp_context.Header = t('context')
        self.lbl_error.Text = t('error')
        self.lbl_error_hint.Text = t('error_hint')
        self.btn_ok.Content = t('send')
        self.btn_cancel.Content = t('cancel')
        self.lbl_status.Text = t('shortcut')

        # topic / frequency / time as pills
        self.topic_pills = self._pills(self.pnl_topics, 'topic',
                                       [(c, l, h) for c, l, h in texts.TOPICS],
                                       self.on_topic_checked)
        self.freq_pills = self._pills(self.pnl_frequency, 'freq',
                                      [(c, l, None) for c, l in texts.FREQUENCY if c],
                                      None)
        self.dur_pills = self._pills(self.pnl_duration, 'dur',
                                     [(c, l, None) for c, l in texts.DURATION if c],
                                     None)

        self.buttons = [u''] + list(buttons)
        self.cb_button.Items.Add(t('no_button'))
        for b in buttons:
            self.cb_button.Items.Add(b)
        self.cb_button.SelectedIndex = 0
        if button and button in self.buttons:
            self.cb_button.SelectedIndex = self.buttons.index(button)

        self.cb_error.Items.Add(t('no_error'))
        for f in self.fails:
            self.cb_error.Items.Add(runs.label(f))
        self.cb_error.SelectedIndex = error if 0 <= error <= len(self.fails) else 0

        self._check(self.topic_pills, topic if topic in texts.TOPIC_CODES else texts.TOPIC_CODES[0])
        self._update_topic()
        self._update_error()
        self.tb_text.Focus()

    # --- pills ---
    def _pills(self, panel, group, items, on_checked):
        from System.Windows.Controls import RadioButton
        style = self.FindResource('Pill')
        out = []
        for code, label, hint in items:
            rb = RadioButton()
            rb.Content = label
            rb.GroupName = group
            rb.Style = style
            rb.Tag = code
            if hint:
                rb.ToolTip = hint
            if on_checked is not None:
                rb.Checked += on_checked
            panel.Children.Add(rb)
            out.append(rb)
        return out

    @staticmethod
    def _checked(pills, default=u''):
        for rb in pills:
            if rb.IsChecked:
                return rb.Tag
        return default

    @staticmethod
    def _check(pills, code):
        for rb in pills:
            if rb.Tag == code:
                rb.IsChecked = True

    # --- events ---
    def on_topic_checked(self, sender, args):
        self._update_topic()

    def on_error_changed(self, sender, args):
        self._update_error(pick_button=True)

    def on_text_changed(self, sender, args):
        empty = not (self.tb_text.Text or u'')
        self.lbl_placeholder.Visibility = Visibility.Visible if empty else Visibility.Collapsed

    def on_key(self, sender, args):
        from System.Windows.Input import Key, Keyboard, ModifierKeys
        ctrl = (Keyboard.Modifiers & ModifierKeys.Control) == ModifierKeys.Control
        if not ctrl:
            return
        if args.Key == Key.Return:
            args.Handled = True
            self.on_ok(sender, args)
        elif args.Key == Key.V and images.clipboard_has_image():
            # Excel / Word put text AND a picture on the clipboard: in the
            # text box the text wins; a screenshot (picture only) is attached
            if self.tb_text.IsKeyboardFocusWithin and images.clipboard_has_text():
                return
            args.Handled = True
            self._add(images.from_clipboard())

    def on_drag_over(self, sender, args):
        from System.Windows import DataFormats, DragDropEffects
        ok = args.Data.GetDataPresent(DataFormats.FileDrop)
        # .None is a Python keyword: getattr
        args.Effects = DragDropEffects.Copy if ok else getattr(DragDropEffects, 'None')
        args.Handled = True

    def on_drop(self, sender, args):
        from System.Windows import DataFormats
        if args.Data.GetDataPresent(DataFormats.FileDrop):
            self._add(images.from_files(list(args.Data.GetData(DataFormats.FileDrop))))

    def on_add_image(self, sender, args):
        from Microsoft.Win32 import OpenFileDialog
        dlg = OpenFileDialog()
        dlg.Filter = u'Images|*.png;*.jpg;*.jpeg;*.bmp;*.gif;*.tif;*.tiff'
        dlg.Multiselect = True
        if dlg.ShowDialog(self):
            self._add(images.from_files(list(dlg.FileNames)))

    # --- pictures ---
    def _add(self, bitmaps):
        for bmp in bitmaps:
            if len(self.images) >= payload.MAX_IMAGES:
                forms.alert(texts.s('image_max'), title=TITLE)
                break
            try:
                b64 = images.encode_fitting(bmp)
            except Exception:
                b64 = None
            if not b64:
                forms.alert(texts.s('image_too_big'), title=TITLE)
                continue
            self.images.append((bmp, b64))
        self._show_images()

    def _show_images(self):
        from System.Windows import Thickness, CornerRadius, HorizontalAlignment, VerticalAlignment
        from System.Windows.Controls import Border, Button, Grid, Image
        from System.Windows.Media import Brushes, Stretch
        self.pnl_images.Children.Clear()
        for i, (bmp, b64) in enumerate(self.images):
            img = Image()
            img.Source = bmp
            img.Stretch = Stretch.UniformToFill
            img.Width, img.Height = 112, 76
            frame = Border()
            frame.CornerRadius = CornerRadius(4)
            frame.BorderBrush = Brushes.LightGray
            frame.BorderThickness = Thickness(1)
            frame.Child = img
            frame.ToolTip = u'{0} KB'.format(images.b64_size_kb(b64))
            rm = Button()
            rm.Style = self.FindResource('Remove')
            rm.Tag = i
            rm.HorizontalAlignment = HorizontalAlignment.Right
            rm.VerticalAlignment = VerticalAlignment.Top
            rm.Margin = Thickness(0, 4, 4, 0)
            rm.Click += self.on_remove_image
            cell = Grid()
            cell.Margin = Thickness(0, 0, 8, 8)
            cell.Children.Add(frame)
            cell.Children.Add(rm)
            self.pnl_images.Children.Add(cell)

    def on_remove_image(self, sender, args):
        i = sender.Tag
        if 0 <= i < len(self.images):
            del self.images[i]
        self._show_images()

    # --- state ---
    def _topic(self):
        return self._checked(self.topic_pills, texts.TOPIC_CODES[0])

    def _error(self):
        """The picked failure (only under Bug) or None."""
        i = self.cb_error.SelectedIndex
        if self._topic() != 'bug' or i < 1 or i > len(self.fails):
            return None
        return self.fails[i - 1]

    def _context(self):
        ctx = dict(self.ctx)
        f = self._error()
        ctx['error_script'] = f['script'] if f else u''
        ctx['error_text'] = runs.report_text(f['error']) if f else u''
        return ctx

    def _update_error(self, pick_button=False):
        f = self._error()
        if f and pick_button and f['button'] in self.buttons:
            self.cb_button.SelectedIndex = self.buttons.index(f['button'])
        text = context.describe(self._context())
        if f:
            text += u'\nError: {0}'.format(runs.summary(f['error']) or f['script'])
        self.tb_context.Text = text
        self.lbl_text.Text = texts.s('text_bug' if f else 'text')

    def _update_topic(self):
        code = self._topic()
        hint = dict((c, h) for c, _l, h in texts.TOPICS).get(code, u'')
        self.lbl_hint.Text = hint
        show = code in texts.TOPICS_WITH_BUTTON
        self.pnl_button.Visibility = Visibility.Visible if show else Visibility.Collapsed
        bug = code == 'bug' and bool(self.fails)
        self.pnl_error.Visibility = Visibility.Visible if bug else Visibility.Collapsed
        self._update_error()

    def _fields(self):
        code = self._topic()
        button = u''
        if code in texts.TOPICS_WITH_BUTTON:
            button = self.buttons[max(0, self.cb_button.SelectedIndex)]
        return {
            'topic': code,
            'text': self.tb_text.Text or u'',
            'error_text': self._context()['error_text'],
            'button': button,
            'frequency': self._checked(self.freq_pills),
            'duration': self._checked(self.dur_pills),
        }

    def on_ok(self, sender, args):
        if self.sending:
            return
        fields = self._fields()
        errors = payload.validate(fields)
        if errors:
            forms.alert(u'\n'.join(texts.s(e) for e in errors), title=TITLE)
            return
        try:
            req = payload.make_request(fields, self._context(),
                                       images=[b64 for _bmp, b64 in self.images])
        except ValueError as ex:
            forms.alert(u'Request not built: {0}'.format(ex), title=TITLE)
            return
        self.request = req
        self._send(req)

    # --- sending: in a background thread, the window (and Revit) stay alive --
    def _send(self, req):
        import threading
        from System import TimeSpan
        from System.Windows.Threading import DispatcherTimer
        self.sending = True
        self.btn_ok.IsEnabled = False
        self.btn_ok.Content = texts.s('sending')
        self.lbl_status.Text = texts.s('sending')
        box = {}

        def run():
            try:
                box['status'] = client.submit(ACTION, req, self.cfg)
            except Exception as ex:
                client._log(u'submit failed: {0}'.format(ex))
                box['status'] = client.QUEUED

        worker = threading.Thread(target=run, name='peer_contact_send')
        worker.daemon = True
        worker.start()
        timer = DispatcherTimer()
        timer.Interval = TimeSpan.FromMilliseconds(200)

        def tick(s, e):
            if worker.is_alive():
                return
            timer.Stop()
            self.sending = False
            if self.closed:          # closed while sending: main() already told the person
                return
            self.status = box.get('status', client.QUEUED)
            self.Close()

        timer.Tick += tick
        timer.Start()

    def on_requests(self, sender, args):
        """My requests: what happened to what was sent from this computer."""
        try:
            from peer_feedback import ui_requests
            ui_requests.show(script.get_bundle_file('MyRequestsForm.xaml'), owner=self)
        except Exception as ex:
            self.lbl_status.Text = u'{0}'.format(ex)

    def on_cancel(self, sender, args):
        self.Close()

    def _on_closed(self, sender, args):
        self.closed = True
        if self.sending:
            # Esc / X while sending: the request is in the outbox already,
            # the thread finishes on its own (or flush sends it next start)
            self.status = BACKGROUND


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
    win = ContactWindow(script.get_bundle_file('ContactForm.xaml'), cfg, ctx, buttons, fails,
                        topic=topic, error=error)
    if error:
        win._update_error(pick_button=True)
    win.ShowDialog()
    if not win.request or not win.status:
        return

    try:
        sent.add(win.request)
    except Exception:
        pass
    status = win.status
    if status == client.SENT:
        forms.alert(texts.s('sent'), title=TITLE, warn_icon=False)
    elif status == client.NOT_CONFIGURED:
        forms.alert(texts.s('not_configured'), title=TITLE)
    elif status == client.REJECTED:
        forms.alert(texts.s('rejected'), title=TITLE)
    elif status == BACKGROUND:
        forms.alert(texts.s('background'), title=TITLE, warn_icon=False)
    else:
        forms.alert(texts.s('queued'), title=TITLE)


main()
