# -*- coding: utf-8 -*-
"""Small dialogs of the library window: request a family / report a problem,
edit family info (admin). XAML lives next to the Library button."""

import os

from pyrevit import forms

from peer_library import groups, log, strings

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from peer_library import version as _version

BTN_DIR = os.path.join(_version.tab_dir(), 'Library.panel', 'Library.smartbutton')


class TextWindow(forms.WPFWindow):
    """Two fields + send. on_send(text1, text2) -> error text or None."""

    def __init__(self, title, head, hint, label1, label2, ok_text, on_send, text1=u'', owner=None):
        forms.WPFWindow.__init__(self, os.path.join(BTN_DIR, 'TextWindow.xaml'))
        if owner is not None:
            self.Owner = owner
        self.Title = title
        self.head.Text = head
        self.hint.Text = hint
        self.label1.Text = label1
        self.label2.Text = label2
        self.ok_btn.Content = ok_text
        self.box1.Text = text1
        self.on_send = on_send
        self.done = False
        (self.box2 if text1 else self.box1).Focus()

    def on_key(self, sender, args):
        from System.Windows.Input import Key
        if args.Key == Key.Escape:
            self.Close()

    def on_cancel(self, sender, args):
        self.Close()

    def on_ok(self, sender, args):
        a, b = (self.box1.Text or u'').strip(), (self.box2.Text or u'').strip()
        if not a or not b:
            self.status_text.Text = strings.FILL_BOTH
            return
        try:
            err = self.on_send(a, b)
        except Exception as ex:
            log.write(u'text dialog send', exc=True)
            err = u'{0}'.format(ex)
        if err:
            self.status_text.Text = err
            return
        self.done = True
        self.Close()


class EditInfoWindow(forms.WPFWindow):
    """Admin: card info without a new version. self.fields after Save."""

    def __init__(self, card, owner=None, known_ids=None):
        forms.WPFWindow.__init__(self, os.path.join(BTN_DIR, 'EditInfoWindow.xaml'))
        if owner is not None:
            self.Owner = owner
        self.card = card
        self.known = dict((k.lower(), k) for k in (known_ids or []))
        self.fields = None
        self.comp_box.Text = u', '.join(card.get('companions') or [])
        self.head.Text = card['id']
        self.name_box.Text = card.get('name') or u''
        for g in groups.GROUPS:
            self.group_box.Items.Add(u'{0}  -  {1}'.format(g[0], g[1]))
        if card.get('group') in groups.GROUP_IDS:
            self.group_box.SelectedIndex = groups.GROUP_IDS.index(card['group'])
        self.tags_box.Text = u', '.join(card.get('tags') or [])
        self.desc_box.Text = card.get('description') or u''
        self.help_box.Text = card.get('help_url') or u''
        self.name_box.Focus()

    def on_key(self, sender, args):
        from System.Windows.Input import Key
        if args.Key == Key.Escape:
            self.Close()

    def on_cancel(self, sender, args):
        self.Close()

    def on_ok(self, sender, args):
        name = (self.name_box.Text or u'').strip()
        if not name:
            self.status_text.Text = u'The name is empty.'
            return
        url = (self.help_box.Text or u'').strip()
        if url and not (url.startswith('http://') or url.startswith('https://')):
            self.status_text.Text = u'The link must start with https://'
            return
        from peer_library import index
        comp = index.parse_companions(self.comp_box.Text, self.card['id'])
        if self.known:
            wrong = [c for c in comp if c.lower() not in self.known]
            if wrong:
                self.status_text.Text = strings.COMP_UNKNOWN.format(u', '.join(wrong))
                return
            comp = [self.known[c.lower()] for c in comp]
        i = self.group_box.SelectedIndex
        self.fields = {'companions': comp,
                       'name': name,
                       'group': groups.GROUP_IDS[i] if i >= 0 else self.card.get('group'),
                       'tags': [t.strip() for t in (self.tags_box.Text or u'').split(u',') if t.strip()],
                       'description': (self.desc_box.Text or u'').strip(),
                       'help_url': url}
        self.Close()
