# -*- coding: utf-8 -*-
"""The other library windows, off-screen: open and render only, nothing is sent."""
from __future__ import print_function
import os
import traceback

execfile(os.path.join(os.path.dirname(__file__), 'stubs.py'))   # noqa: F821
be, cfg = backend(OUT)   # noqa: F821


def run(name, make):
    try:
        win = make()
        show(win)
        snap(win, OUT, name)   # noqa: F821
        st = getattr(win, 'status_text', None)
        print(name, '-', st.Text if st is not None else u'')
        win.Close()
        pump(100)
    except Exception:
        print('FAILED', name)
        traceback.print_exc()


def keys():
    ns = {'__name__': 'keys_preview', '__file__': os.path.join(B('Keys.smartbutton'), 'script.py')}
    execfile(ns['__file__'], ns)   # noqa: F821
    return ns['KeysWindow'](be)


run('keys.png', keys)
from peer_library.ui_inbox import InboxWindow  # noqa: E402
run('inbox.png', lambda: InboxWindow(os.path.join(B('Inbox.smartbutton'), 'InboxWindow.xaml'), be,
                                     os.path.join(B('Publish.smartbutton'), 'PublishWindow.xaml'),
                                     FakeApp()))
from peer_library.ui_publish import PublishWindow  # noqa: E402
first_id = be.get_index()['families'][0]['id']
run('publish.png', lambda: PublishWindow(os.path.join(B('Publish.smartbutton'), 'PublishWindow.xaml'),
                                         FakeApp(), be, {'family_id': first_id}))
from peer_library.ui_propose import ProposeWindow  # noqa: E402
run('propose.png', lambda: ProposeWindow(os.path.join(B('Propose.smartbutton'), 'ProposeWindow.xaml'),
                                         FakeDoc(), None, be, preset_file=r'C:\Temp\My_Family.rfa'))
from peer_library import session, strings  # noqa: E402
run('login.png', lambda: session.LoginWindow(be))
from peer_library.ui_dialogs import EditInfoWindow, TextWindow  # noqa: E402
run('request.png', lambda: TextWindow(strings.TITLE_REQUEST, strings.REQUEST_HEAD, strings.REQUEST_HINT,
                                      strings.REQUEST_L1, strings.REQUEST_L2, strings.BTN_SEND,
                                      lambda a, b: None))
run('edit_info.png', lambda: EditInfoWindow(be.get_index()['families'][0]))


def load_check_windows():
    """The check before an update: a family that breaks things, and a clean one.
    Data like the Revit test of 20.11.2026 (an old corner family with the
    library name); pictures from the cache when they are there."""
    from peer_library import family_diff as D, load_check
    from peer_library.ui_check import LoadCheckWindow
    LEN, INT, TXT = u'autodesk.spec.aec:length-2.0.0', u'autodesk.spec:int-2.0.0', u'autodesk.spec:string-2.0.0'

    def p(name, shared=False, guid=u'', spec=LEN):
        return {'name': name, 'shared': shared, 'guid': guid, 'instance': True, 'spec': spec,
                'formula': u'', 'reporting': False}
    old = {'category': u'Detail Items', 'types': [u'Corner'], 'nested': [],
           'params': [p(u'A'), p(u'Note', spec=TXT), p(u'Rebar_Number', True, u'ea1e3542-018b-4ec2-ad9a-ff2d969c3897', INT)]}
    new = {'category': u'Detail Items', 'types': [u'Corner v2'], 'nested': [],
           'params': [p(u'Rebar_Number', True, u'3daaa3a8-42d9-4e71-86e3-9541a415b23b', INT),
                      p(u'Active_WallBot'), p(u'Active_WallTop'), p(u'Corner_Quantity b', spec=INT)]}
    trial = {'failed': [], 'warnings': [], 'resolved': [u'One or more dimension references are or have become invalid.'],
             'deleted': {'dimensions': 1}, 'lost': {u'A': [4, 0], u'Note': [4, 0], u'Rebar_Number': [4, 0]},
             'changed': {}, 'instances': 4, 'types': 1}
    fid = u'PR_Reinforcement in corner v2'
    findings = D.soften(D.compare(old, new), trial) + D.trial_findings(trial)
    findings.append((D.WARNING, 'not_library', strings.CHECK_NOT_LIBRARY))
    rep = load_check.Report(fid, findings, trial, not_library=True)
    scratch = os.environ.get('PEER_PREVIEW_PICTURES', u'')
    rep.project_png = os.path.join(scratch, u'project_real_corner.png') if scratch else None
    lib_png = os.path.join(os.environ['LOCALAPPDATA'], u'PEER', u'Library', u'03_Rebar_2D', fid + u'.png')
    run('check_breaks.png', lambda: LoadCheckWindow(rep, lib_png))
    clean = load_check.Report(u'PEER-Concrete-Column-Rectangular',
                              [(D.INFO, 'param_new', u"New in the library: 'Chamfer'.")],
                              {'instances': 12, 'types': 3})
    run('check_clean.png', lambda: LoadCheckWindow(clean, None))
    fam = load_check.Report(u'PR_Detail_Arrow', [
        (D.WARNING, 'file_name', u"'ADSK_Revit Version' is called 'PR_Revit Version' in PR_FOPv4.txt (same GUID)."),
        (D.WARNING, 'should_share', u"'Cap Thickness' is a family parameter, but PR_FOPv4.txt has a shared 'Cap Thickness' - tags and schedules cannot show this one."),
        (D.WARNING, 'type_broken', u"Type '30/80' does not regenerate: Constraints are not satisfied"),
        (D.INFO, 'unused', u"Not used by any dimension, element or formula: 'Diameter'.")],
        kind='family', summary=u'Detail Items · 8 parameters (2 shared) · 1 types',
        note=u'Shared parameters checked against: F:\...\PR_FOPv4.txt')
    fam.fixes = [{'text': u"'ADSK_Revit Version' -> 'PR_Revit Version'"}, {'text': u"'Cap Thickness' -> shared"}]
    fam.can_change = True
    run('check_family.png', lambda: LoadCheckWindow(fam))


load_check_windows()
print('message boxes:', MSGS or 'none')
