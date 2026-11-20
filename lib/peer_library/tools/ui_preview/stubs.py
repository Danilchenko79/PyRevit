# -*- coding: utf-8 -*-
"""Revit / pyRevit stand-ins for the off-screen window check (run.ps1).
Puts lib/ on sys.path, stubs pyrevit.forms, silences message boxes (kept in
MSGS), and gives pump() / snap() / show()."""
from __future__ import print_function
import os
import sys
import types

import clr
clr.AddReference('PresentationCore')
clr.AddReference('PresentationFramework')
clr.AddReference('WindowsBase')
clr.AddReference('System.Xaml')
clr.AddReference('System.Data')
_API = r'C:\Program Files\Autodesk\Revit 2024\RevitAPI.dll'
clr.AddReferenceToFileAndPath(_API)        # types only - nothing of Revit runs
import wpf  # noqa: E402
from System import TimeSpan  # noqa: E402
from System.IO import FileMode, FileStream  # noqa: E402
from System.Windows import Rect, Window, WindowStartupLocation  # noqa: E402
from System.Windows.Media import DrawingVisual, PixelFormats, VisualBrush  # noqa: E402
from System.Windows.Media.Imaging import BitmapFrame, PngBitmapEncoder, RenderTargetBitmap  # noqa: E402
from System.Windows.Threading import Dispatcher, DispatcherFrame, DispatcherTimer  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
EXT = os.path.dirname(LIB)
PANEL = os.path.join(EXT, 'PEER.tab', 'Library.panel')


def B(name):
    """Folder of a button by its name, wherever it sits in the tab."""
    from peer_library import version
    return version.bundle_dir(name, EXT)
if LIB not in sys.path:
    sys.path.insert(0, LIB)

pyrevit = types.ModuleType('pyrevit')
forms = types.ModuleType('pyrevit.forms')


class WPFWindow(Window):
    def __init__(self, xaml_path, *a, **k):
        wpf.LoadComponent(self, xaml_path)


forms.WPFWindow = WPFWindow
forms.ask_for_string = lambda **k: None
forms.SelectFromList = None
forms.alert = lambda *a, **k: None
forms.pick_file = lambda **k: None
forms.pick_folder = lambda **k: None
pyrevit.forms = forms
sys.modules['pyrevit'] = pyrevit
sys.modules['pyrevit.forms'] = forms

from peer_library import config  # noqa: E402
from peer_library import ui_common as U  # noqa: E402
MSGS = []
U.error = lambda t, title=None: MSGS.append(u'ERROR ' + t)
U.info = lambda t, title=None: MSGS.append(u'INFO ' + t)
U.ask = lambda t, title=None: False


class FakeApp(object):
    Documents = []
    VersionNumber = '2024'


class FakeDoc(object):
    IsFamilyDocument = False
    Title = u'Preview project'
    Application = FakeApp()


def backend(out):
    """The configured library (service + your saved key), cache in the output folder."""
    cfg = config.load()
    cfg['cache'] = os.path.join(out, 'cache')
    return config.make_backend(cfg), cfg


def pump(ms):
    """Let the window work (timers, loading) for ms milliseconds."""
    f = DispatcherFrame()
    t = DispatcherTimer()
    t.Interval = TimeSpan.FromMilliseconds(ms)

    def stop(s, a):
        t.Stop()
        f.Continue = False
    t.Tick += stop
    t.Start()
    Dispatcher.PushFrame(f)


def show(win, ms=1500):
    win.WindowStartupLocation = WindowStartupLocation.Manual
    win.Left, win.Top = -20000, 0          # off-screen, never takes the focus
    win.ShowActivated = False
    win.Show()
    pump(ms)
    return win


def snap(win, out, name):
    el = win.Content
    w, h = int(el.ActualWidth), int(el.ActualHeight)
    dv = DrawingVisual()
    ctx = dv.RenderOpen()
    ctx.DrawRectangle(VisualBrush(el), None, Rect(0, 0, w, h))
    ctx.Close()
    bmp = RenderTargetBitmap(w, h, 96, 96, PixelFormats.Pbgra32)
    bmp.Render(dv)
    enc = PngBitmapEncoder()
    enc.Frames.Add(BitmapFrame.Create(bmp))
    fs = FileStream(os.path.join(out, name), FileMode.Create)
    enc.Save(fs)
    fs.Close()
    print('picture', name)
