# -*- coding: utf-8 -*-
"""Revit side of publishing (IronPython, inside Revit only).

prepare_family(app, source, family_id, version, workdir):
    copy -> open in background -> checks -> PEER_Version into every type ->
    PNG preview 256x256 -> save compact -> close. The user's source file is
    never touched.
"""

import os
import shutil

import clr
from Autodesk.Revit import DB
from System.Collections.Generic import List

from peer_library import checks_file, log

VERSION_PARAM = 'PEER_Version'
PREVIEW_PX = 256


class Guard(DB.IFailuresPreprocessor):
    """Warnings are dropped, errors roll the transaction back silently."""

    def PreprocessFailures(self, fa):
        err = False
        for f in fa.GetFailureMessages():
            if f.GetSeverity() == DB.FailureSeverity.Warning:
                fa.DeleteWarning(f)
            else:
                err = True
        if err:
            return DB.FailureProcessingResult.ProceedWithRollBack
        return DB.FailureProcessingResult.Continue


def _transaction(doc, name):
    tx = DB.Transaction(doc, name)
    o = tx.GetFailureHandlingOptions()
    o.SetFailuresPreprocessor(Guard())
    o.SetClearAfterRollback(True)
    tx.SetFailureHandlingOptions(o)
    return tx


def revit_version(app):
    try:
        return int(app.VersionNumber)
    except (TypeError, ValueError):
        return 0


# ---- checks on the open family ---------------------------------------------
def family_checks(fd):
    res = []
    fam = fd.OwnerFamily
    cat = fam.FamilyCategory if fam else None
    if cat is None:
        res.append(('error', 'category', u'Family category is not set'))
    n_imports = DB.FilteredElementCollector(fd).OfClass(DB.ImportInstance).GetElementCount()
    if n_imports:
        res.append(('warning', 'cad', u'{0} imported / linked CAD file(s) inside the family'
                                      .format(n_imports)))
    if fd.FamilyManager.Types.Size == 0:
        res.append(('warning', 'types', u'Family has no named types - one will be created'))
    n_param = 0
    for p in fd.FamilyManager.GetParameters():
        if not p.IsShared and p.Definition.Name != VERSION_PARAM and p.Id.IntegerValue > 0:
            n_param += 1
    if n_param:
        res.append(('info', 'params', u'{0} family parameter(s) are not shared parameters'
                                      .format(n_param)))
    return res, (cat.Name if cat else u'')


def _version_param(fd):
    fm = fd.FamilyManager
    p = fm.get_Parameter(VERSION_PARAM)
    if p is None:
        p = fm.AddParameter(VERSION_PARAM, DB.GroupTypeId.IdentityData,
                            DB.SpecTypeId.Int.Integer, False)
    return p


def stamp_version(fd, version, family_id):
    """PEER_Version = version in every type. Returns problem text or None."""
    fm = fd.FamilyManager
    tx = _transaction(fd, 'PEER: library version')
    tx.Start()
    try:
        if fm.Types.Size == 0:
            fm.NewType(family_id)
        p = _version_param(fd)
        if p.IsInstance:
            fm.MakeType(p)
        if p.StorageType != DB.StorageType.Integer:
            raise Exception(u'{0} exists but is not an integer'.format(VERSION_PARAM))
        for t in list(fm.Types):
            fm.CurrentType = t
            fm.Set(p, int(version))
        tx.Commit()
    finally:
        if tx.HasStarted() and not tx.HasEnded():
            tx.RollBack()
    if tx.GetStatus() != DB.TransactionStatus.Committed:
        return u'Revit rejected the change'
    bad = []
    for t in list(fm.Types):
        v = t.AsInteger(fm.get_Parameter(VERSION_PARAM))
        if v != int(version):
            bad.append(t.Name or u'(no name)')
    if bad:
        return u'not written in types: ' + u', '.join(bad)
    return None


# ---- preview ---------------------------------------------------------------
def _is_model(fd):
    cat = fd.OwnerFamily.FamilyCategory if fd.OwnerFamily else None
    return cat is not None and cat.CategoryType == DB.CategoryType.Model


def _printable_views(fd):
    out = []
    for v in DB.FilteredElementCollector(fd).OfClass(DB.View):
        try:
            if not v.IsTemplate and v.CanBePrinted:
                out.append(v)
        except Exception:
            pass
    return out


def pick_view(fd):
    """3D view for model families (created if missing), else the first plan."""
    views = _printable_views(fd)
    if _is_model(fd):
        v3 = [v for v in views if isinstance(v, DB.View3D) and not v.IsPerspective]
        if v3:
            return v3[0], False
        vft = [t for t in DB.FilteredElementCollector(fd).OfClass(DB.ViewFamilyType)
               if t.ViewFamily == DB.ViewFamily.ThreeDimensional]
        if vft:
            return vft[0], True
    plans = [v for v in views if isinstance(v, DB.ViewPlan)]
    if plans:
        return plans[0], False
    return (views[0] if views else None), False


def _setup_view(fd, family_id):
    """Returns the view for the preview; may create a 3D view (in a transaction)."""
    view, create = pick_view(fd)
    if view is None:
        return None
    tx = _transaction(fd, 'PEER: preview view')
    tx.Start()
    try:
        if create:
            view = DB.View3D.CreateIsometric(fd, view.Id)
        if isinstance(view, DB.View3D):
            try:
                view.DisplayStyle = DB.DisplayStyle.ShadingWithEdges
                view.DetailLevel = DB.ViewDetailLevel.Fine
            except Exception:
                pass
        tx.Commit()
    finally:
        if tx.HasStarted() and not tx.HasEnded():
            tx.RollBack()
    return view


def _square_png(src, dst, size):
    clr.AddReference('System.Drawing')
    from System.Drawing import Bitmap, Color, Graphics, Rectangle
    from System.Drawing.Drawing2D import InterpolationMode
    from System.Drawing.Imaging import ImageFormat
    img = Bitmap(src)
    try:
        canvas = Bitmap(size, size)
        g = Graphics.FromImage(canvas)
        try:
            g.Clear(Color.White)
            g.InterpolationMode = InterpolationMode.HighQualityBicubic
            pad = 8
            k = min(float(size - 2 * pad) / img.Width, float(size - 2 * pad) / img.Height)
            w, h = int(img.Width * k), int(img.Height * k)
            g.DrawImage(img, Rectangle((size - w) // 2, (size - h) // 2, w, h))
        finally:
            g.Dispose()
        canvas.Save(dst, ImageFormat.Png)
        canvas.Dispose()
    finally:
        img.Dispose()


def export_preview(fd, view, png_path):
    tmp = os.path.join(os.path.dirname(png_path), '_img')
    if os.path.isdir(tmp):
        shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    opts = DB.ImageExportOptions()
    opts.ExportRange = DB.ExportRange.SetOfViews
    opts.SetViewsAndSheets(List[DB.ElementId]([view.Id]))
    opts.ZoomType = DB.ZoomFitType.FitToPage
    opts.PixelSize = PREVIEW_PX * 3
    opts.ImageResolution = DB.ImageResolution.DPI_150
    opts.HLRandWFViewsFileType = DB.ImageFileType.PNG
    opts.ShadowViewsFileType = DB.ImageFileType.PNG
    opts.FilePath = os.path.join(tmp, 'preview')
    fd.ExportImage(opts)
    pngs = [os.path.join(tmp, f) for f in os.listdir(tmp) if f.lower().endswith('.png')]
    if not pngs:
        raise Exception(u'Revit exported no image')
    _square_png(pngs[0], png_path, PREVIEW_PX)
    shutil.rmtree(tmp, ignore_errors=True)
    return png_path


# ---- whole preparation -----------------------------------------------------
def prepare_family(app, source, family_id, version, workdir):
    """-> dict(results, rfa, png, catalog, category, revit).

    results: list of (level, code, text); any 'error' = do not publish.
    """
    out = {'results': [], 'rfa': None, 'png': None, 'catalog': None,
           'category': u'', 'revit': None}
    res = out['results']
    file_res, year = checks_file.check_file(source, family_id)
    res.extend(file_res)
    out['revit'] = year
    ver = revit_version(app)
    if ver != checks_file.LIBRARY_REVIT:
        res.append(('error', 'revit_app', u'Publish from Revit {0} only (this is Revit {1}) - '
                                          u'otherwise the file is saved in a newer format'
                                          .format(checks_file.LIBRARY_REVIT, ver)))
    if checks_file.errors(res):
        return out

    src_dir = os.path.join(workdir, 'src')
    out_dir = os.path.join(workdir, 'out')
    for d in (src_dir, out_dir):
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)
    copy = os.path.join(src_dir, family_id + '.rfa')
    shutil.copyfile(source, copy)
    target = os.path.join(out_dir, family_id + '.rfa')

    fd = None
    try:
        try:
            fd = app.OpenDocumentFile(copy)
        except Exception as ex:
            log.write(u'open {0}: {1}'.format(source, ex), exc=True)
            res.append(('error', 'open', u'Revit could not open the family: {0}'.format(ex)))
            return out
        if not fd.IsFamilyDocument:
            res.append(('error', 'not_family', u'Not a family document'))
            return out
        doc_res, out['category'] = family_checks(fd)
        res.extend(doc_res)
        if checks_file.errors(res):
            return out
        try:
            problem = stamp_version(fd, version, family_id)
        except Exception as ex:
            log.write(u'stamp {0}'.format(family_id), exc=True)
            problem = u'{0}'.format(ex)
        if problem:
            res.append(('warning', 'version', u'{0} not written: {1} - the version in projects '
                                              u'will show as unknown'.format(VERSION_PARAM, problem)))
        view = None
        try:
            view = _setup_view(fd, family_id)
            if view is not None:
                out['png'] = export_preview(fd, view, os.path.join(out_dir, family_id + '.png'))
            else:
                res.append(('warning', 'preview', u'No view for a preview'))
        except Exception as ex:
            log.write(u'preview {0}'.format(family_id), exc=True)
            res.append(('warning', 'preview', u'Preview not made: {0}'.format(ex)))
        so = DB.SaveAsOptions()
        so.OverwriteExistingFile = True
        so.Compact = True
        so.MaximumBackups = 1
        if view is not None:
            try:
                so.PreviewViewId = view.Id
            except Exception:
                pass
        fd.SaveAs(target, so)
        out['rfa'] = target
    finally:
        if fd is not None:
            try:
                fd.Close(False)
            except Exception:
                log.write(u'close {0}'.format(family_id), exc=True)
    for f in os.listdir(out_dir):
        if f.lower().endswith('.rfa') and f != family_id + '.rfa':
            try:
                os.remove(os.path.join(out_dir, f))   # Revit backups *.0001.rfa
            except OSError:
                pass
    cat = os.path.splitext(source)[0] + '.txt'
    if os.path.isfile(cat):
        dst = os.path.join(out_dir, family_id + '.txt')
        shutil.copyfile(cat, dst)
        out['catalog'] = dst
    return out
