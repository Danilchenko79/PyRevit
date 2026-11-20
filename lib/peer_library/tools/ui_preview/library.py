# -*- coding: utf-8 -*-
"""Library window, off-screen: load, previews, search (separators, RU/HE),
details, catalog, 'Need update', This project, What's new. A fake project has
one family up to date, one outdated, one without a version."""
from __future__ import print_function
import os
import time

execfile(os.path.join(os.path.dirname(__file__), 'stubs.py'))   # noqa: F821
from System.Windows import Visibility  # noqa: E402
from peer_library import loader  # noqa: E402

PROJECT = {'peer-concrete-column-rectangular': 1, 'pr_detail_breakline': 0, 'pr_sheet a0': None}
loader.project_families = lambda doc: dict(PROJECT)
loader.project_family_list = lambda doc: [
    (u'PEER-Concrete-Column-Rectangular', u'Structural Columns', 1),
    (u'PR_Detail_BreakLine', u'Detail Items', 0),
    (u'PR_Sheet A0', u'Title Blocks', None),
    (u'M_Single-Flush', u'Doors', None)]

from peer_library.ui_library import LibraryWindow  # noqa: E402
be, cfg = backend(OUT)   # noqa: F821
t0 = time.time()
win = LibraryWindow(os.path.join(PANEL, 'Library.smartbutton', 'LibraryWindow.xaml'), FakeDoc(), None, be, cfg)
show(win, 300)
print('open: %.1f s, %d families, status: %s' % (time.time() - t0, len(win.items), win.status_text.Text))
for i in range(60):
    if all(x.preview_done for x in win.items):
        break
    pump(500)
print('previews: %d / %d after %.1f s' % (sum(1 for x in win.items if x.image.Source is not None),
                                          len(win.items), time.time() - t0))
snap(win, OUT, 'library_1_start.png')   # noqa: F821


def search(text, picture=None):
    win.search_box.Text = text
    pump(400)
    shown = [lbi.Tag.card['id'] for lbi in win.tile_list.Items if lbi.Visibility == Visibility.Visible]
    print(u'search %r -> %d: %s' % (text, len(shown), u', '.join(shown[:5])))
    if picture:
        snap(win, OUT, picture)   # noqa: F821


search(u'he 200 a', 'library_2_search.png')
search(u'колонна')
search(u'כלונס')
search(u'column')
first = [lbi for lbi in win.tile_list.Items if lbi.Visibility == Visibility.Visible][0]
win.tile_list.SelectedItem = first
pump(600)
print('details:', win.d_name.Text, '|', win.d_version.Text, '|', win.d_project.Text)
snap(win, OUT, 'library_3_details.png')   # noqa: F821
search(u'')
cat = [x for x in win.items if x.card.get('type_catalog')]
if cat:
    win.tile_list.SelectedItem = cat[0].lbi
    pump(800)
    print('catalog:', cat[0].card['id'], '-', win.types_header.Text)
win.group_list.SelectedIndex = win.group_keys.index('outdated')
pump(400)
print('need update:', [lbi.Tag.card['id'] for lbi in win.tile_list.Items if lbi.Visibility == Visibility.Visible])
snap(win, OUT, 'library_4_outdated.png')   # noqa: F821
win.group_list.SelectedIndex = 0
win.tabs.SelectedItem = win.tab_project
pump(600)
print('this project:', win.proj_summary.Text)
snap(win, OUT, 'library_5_project.png')   # noqa: F821
win.tabs.SelectedItem = win.tab_news
pump(800)
print("what's new: %d lines" % win.news_list.Items.Count)
snap(win, OUT, 'library_6_news.png')   # noqa: F821
win.Close()
pump(200)
print('message boxes:', MSGS or 'none')
