# -*- coding: utf-8 -*-
__title__ = 'Mirror Building'
__author__ = 'Dima'
__doc__ = '''Version = 1.2
Date      = 2026-06-18
Description:
    One tool to mirror building A documentation onto building B (two instances
    of the same link). Pick what to mirror and on which views:
      - SECTIONS  — section marks mirrored whole (MirrorElements); dependent
                    views skipped; arrow side is auto-corrected when the link
                    is mirrored (T.HasReflection).
      - ANNOTATIONS — dimensions, tags, spots, detail lines, text (refs rebound
                    to link B).
      - OVERWRITE — delete what THIS tool created earlier on a view and recreate,
                    so each run refreshes B from A without duplicates.
    Created elements are remembered in a per-document registry file (keyed by
    source view), so overwrite never touches manual elements.
'''

from Autodesk.Revit.DB import (
    Transaction, Reference, ReferenceArray, Line, Arc, XYZ, ElementId, Plane,
    ElementTransformUtils, RevitLinkInstance, IndependentTag, TagOrientation, Dimension,
    SpotDimension, TextNote, TextNoteOptions, ViewSection, View, CurveElement, CurveElementType,
    LeaderEndCondition, StorageType, SpecTypeId, BuiltInCategory, BuiltInParameter,
    ViewDuplicateOption, FilteredElementCollector, IFailuresPreprocessor,
    FailureProcessingResult, FailureSeverity, TransactionStatus
)
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
from Autodesk.Revit.Exceptions import OperationCanceledException
from pyrevit import forms, script
from System.Collections.Generic import List
from System.Windows.Markup import XamlReader
from System.Windows.Controls import CheckBox
from System.Windows import Thickness
import math
import json
import os as _os
import sys as _sys

# peer_log
_ext = _os.path.dirname(_os.path.abspath(__file__))
while _ext and not _ext.endswith('.extension'):
    _parent = _os.path.dirname(_ext)
    if _parent == _ext:
        break
    _ext = _parent
_lib = _os.path.join(_ext, 'lib')
if _os.path.isdir(_lib) and _lib not in _sys.path:
    _sys.path.append(_lib)
try:
    from peer_log import RunLog
except Exception:
    class RunLog(object):
        def __init__(self, *a, **k): pass
        def processed(self, *a, **k): pass
        def skipped(self, *a, **k): pass
        def error(self, *a, **k): pass
        def finish(self, *a, **k): pass

doc = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
output = script.get_output()
run = RunLog('MirrorBuilding')

# Только планы (без разрезов/фасадов/детальных видов).
PLAN_LIKE = ('FloorPlan', 'CeilingPlan', 'EngineeringPlan', 'AreaPlan',
             'StructuralPlan')


# ============================================================
# Registry + settings (per-document file)
# ============================================================
try:
    REG_PATH = script.get_document_data_file('peer_mirror_registry', 'json')
except Exception:
    REG_PATH = _os.path.join(_os.environ.get('TEMP', _os.path.expanduser('~')),
                             'peer_mirror_registry.json')


def reg_read():
    try:
        if _os.path.isfile(REG_PATH):
            with open(REG_PATH, 'r') as f:
                d = json.load(f)
                if isinstance(d, dict):
                    return d
    except Exception:
        pass
    return {}


def reg_write(d):
    try:
        with open(REG_PATH, 'w') as f:
            json.dump(d, f)
    except Exception:
        pass


def get_settings():
    s = reg_read().get('_settings', {})
    return {
        'sec': bool(s.get('sec', True)),
        'ann': bool(s.get('ann', True)),
        'ovr': bool(s.get('ovr', True)),
    }


def save_settings(st):
    d = reg_read()
    d['_settings'] = st
    reg_write(d)


def reg_ids_for(vid_key):
    return reg_read().get(vid_key, [])


def delete_registered(vid_key):
    """Delete elements created earlier on this view. Inside a transaction."""
    reg = reg_read()
    ids = reg.get(vid_key, [])
    deleted = 0
    for i in ids:
        try:
            eid = ElementId(int(i))
            if doc.GetElement(eid) is not None:
                doc.Delete(eid)
                deleted += 1
        except Exception:
            pass
    reg[vid_key] = []
    reg_write(reg)
    return deleted, len(ids)


# ============================================================
# Links A/B
# ============================================================
def link_inst_from_ref(ref):
    if ref is None or ref.LinkedElementId == ElementId.InvalidElementId:
        return None
    el = doc.GetElement(ref.ElementId)
    return el if isinstance(el, RevitLinkInstance) else None


def first_link(items, ref_getter):
    for it in items:
        try:
            for r in ref_getter(it):
                li = link_inst_from_ref(r)
                if li is not None:
                    return li
        except Exception:
            pass
    return None


def remap_one(ref, link_b):
    if ref.LinkedElementId == ElementId.InvalidElementId:
        return ref, False
    s = ref.ConvertToStableRepresentation(doc)
    parts = s.split(':', 1)
    new_s = str(link_b.Id.IntegerValue) + ':' + parts[1]
    return Reference.ParseFromStableRepresentation(doc, new_s), True


class _LinkFilter(ISelectionFilter):
    def AllowElement(self, e):
        return isinstance(e, RevitLinkInstance)

    def AllowReference(self, r, p):
        return False


class _SwallowFailures(IFailuresPreprocessor):
    def PreprocessFailures(self, fa):
        has_error = False
        for msg in fa.GetFailureMessages():
            try:
                if msg.GetSeverity() == FailureSeverity.Error:
                    has_error = True
                else:
                    fa.DeleteWarning(msg)
            except Exception:
                pass
        if has_error:
            return FailureProcessingResult.ProceedWithRollBack
        return FailureProcessingResult.Continue


_swallow = _SwallowFailures()


def find_link_a():
    """Link A = the instance the existing documentation references. Try active
    view first (user is looking at building A there), then any view."""
    av = doc.ActiveView
    if av is not None:
        d = list(FilteredElementCollector(doc, av.Id).OfClass(Dimension))
        s = list(FilteredElementCollector(doc, av.Id).OfClass(SpotDimension))
        t = list(FilteredElementCollector(doc, av.Id).OfClass(IndependentTag))
        la = (first_link(d, lambda x: x.References)
              or first_link(s, lambda x: x.References)
              or first_link(t, lambda x: x.GetTaggedReferences()))
        if la is not None:
            return la
    d = list(FilteredElementCollector(doc).OfClass(Dimension))
    t = list(FilteredElementCollector(doc).OfClass(IndependentTag))
    return (first_link(d, lambda x: x.References)
            or first_link(t, lambda x: x.GetTaggedReferences()))


# ============================================================
# Annotations
# ============================================================
def mirrored_angle(src_angle, T, view):
    rd, up, vd = view.RightDirection, view.UpDirection, view.ViewDirection
    dvec = rd.Multiply(math.cos(src_angle)).Add(up.Multiply(math.sin(src_angle)))
    nd = T.OfVector(dvec).Normalize()
    na = math.atan2(rd.CrossProduct(nd).DotProduct(vd), rd.DotProduct(nd))
    half = math.pi / 2.0
    while na > half:
        na -= math.pi
    while na <= -half:
        na += math.pi
    return na


def find_tag_angle_param(tag):
    fallback = None
    for p in tag.Parameters:
        try:
            if p.StorageType != StorageType.Double or p.IsReadOnly:
                continue
            nm = p.Definition.Name
            if nm and nm.strip().lower() == 'angle':
                return p
            try:
                if p.Definition.GetDataType().TypeId == SpecTypeId.Angle.TypeId and fallback is None:
                    fallback = p
            except Exception:
                pass
        except Exception:
            pass
    return fallback


def mirror_curve(c, T):
    if isinstance(c, Line):
        return Line.CreateBound(T.OfPoint(c.GetEndPoint(0)), T.OfPoint(c.GetEndPoint(1)))
    if isinstance(c, Arc):
        return Arc.Create(T.OfPoint(c.GetEndPoint(0)),
                          T.OfPoint(c.GetEndPoint(1)),
                          T.OfPoint(c.Evaluate(0.5, True)))
    return c.CreateTransformed(T)


def mirror_dim(dim, T, link_b, view):
    refs = ReferenceArray()
    n_linked = 0
    for r in dim.References:
        nr, was = remap_one(r, link_b)
        if was:
            refs.Append(nr)
            n_linked += 1
        # host-ссылки (деталь-линии и т.п.) НЕ добавляем — иначе размер
        # цепляется к зданию A. Линковые витнесы переносятся как раньше.
    if n_linked < 2:
        raise Exception(u'<2 link references (skip)')
    crv = dim.Curve
    p = T.OfPoint(crv.Origin)
    d = T.OfVector(crv.Direction).Normalize()
    half = 1000.0
    line = Line.CreateBound(p - d.Multiply(half), p + d.Multiply(half))
    try:
        return doc.Create.NewDimension(view, line, refs, dim.DimensionType)
    except Exception:
        return doc.Create.NewDimension(view, line, refs)


def mirror_tag(tag, T, link_b, view):
    refs = list(tag.GetTaggedReferences())
    if not refs:
        raise Exception(u'tag without references')
    nref, was = remap_one(refs[0], link_b)
    new_head = T.OfPoint(tag.TagHeadPosition)
    nt = IndependentTag.Create(doc, tag.GetTypeId(), view.Id, nref,
                               tag.HasLeader, tag.TagOrientation, new_head)
    need_refresh = False
    src_p = find_tag_angle_param(tag)
    if src_p is not None:
        na = mirrored_angle(src_p.AsDouble(), T, view)
        dst_p = find_tag_angle_param(nt)
        if dst_p is not None:
            try:
                dst_p.Set(na)
                if abs(na) > 1e-4:
                    need_refresh = True
            except Exception:
                pass
    else:
        try:
            ang = getattr(tag.Location, 'Rotation', None)
            if ang:
                na = mirrored_angle(ang, T, view)
                axis = Line.CreateBound(new_head, new_head.Add(view.ViewDirection))
                ElementTransformUtils.RotateElement(doc, nt.Id, axis, na)
        except Exception:
            pass
    nt.TagHeadPosition = new_head
    # Тег с Orientation=Model НЕ перерисовывается после записи Angle, пока
    # ориентацию не «дёрнуть» (как руками Vertical->Model). Иначе угол стоит
    # в параметре, но визуально тег горизонтальный.
    if need_refresh:
        try:
            ori = nt.TagOrientation
            nt.TagOrientation = TagOrientation.Vertical
            doc.Regenerate()
            nt.TagOrientation = ori
            doc.Regenerate()
        except Exception:
            pass
    if tag.HasLeader:
        try:
            nt.LeaderEndCondition = tag.LeaderEndCondition
        except Exception:
            pass
        try:
            nt.SetLeaderElbow(nref, T.OfPoint(tag.GetLeaderElbow(refs[0])))
        except Exception:
            pass
        try:
            if tag.LeaderEndCondition == LeaderEndCondition.Free:
                nt.SetLeaderEnd(nref, T.OfPoint(tag.GetLeaderEnd(refs[0])))
        except Exception:
            pass
    return nt


def mirror_spot(spot, T, link_b, view):
    rr = None
    for r in spot.References:
        rr = r
        break
    if rr is None:
        raise Exception(u'no reference')
    nref, was = remap_one(rr, link_b)
    if not was:
        raise Exception(u'reference not to link')
    origin = T.OfPoint(spot.Origin)
    try:
        end = T.OfPoint(spot.LeaderEndPosition)
    except Exception:
        end = origin
    bend = (origin + end).Multiply(0.5)
    has_leader = bool(getattr(spot, 'LeaderHasShoulder', True))
    return doc.Create.NewSpotElevation(view, nref, origin, bend, end, origin, has_leader)


def mirror_detail_curve(de, T, view):
    nc = mirror_curve(de.GeometryCurve, T)
    ndc = doc.Create.NewDetailCurve(view, nc)
    try:
        ndc.LineStyle = de.LineStyle
    except Exception:
        pass
    return ndc


def mirror_text(tn, T, view):
    pos = T.OfPoint(tn.Coord)
    # зеркалим поворот текста (BaseDirection), нормализуем в (-90,90] чтобы
    # текст читался — иначе он стоит как в оригинале и «не перевёрнут».
    rd, vd = view.RightDirection, view.ViewDirection
    bd = tn.BaseDirection
    src = math.atan2(rd.CrossProduct(bd).DotProduct(vd), rd.DotProduct(bd))
    na = mirrored_angle(src, T, view)
    opts = TextNoteOptions(tn.GetTypeId())
    opts.Rotation = na
    try:
        opts.HorizontalAlignment = tn.HorizontalAlignment
    except Exception:
        pass
    nt = TextNote.Create(doc, view.Id, pos, tn.Text, opts)
    try:
        nt.Width = tn.Width
    except Exception:
        pass
    return nt


def collect_annotations(view):
    dims, spots, tags, texts, curves = [], [], [], [], []
    for el in FilteredElementCollector(doc, view.Id).WhereElementIsNotElementType():
        if isinstance(el, IndependentTag):
            tags.append(el)
        elif isinstance(el, SpotDimension):
            spots.append(el)
        elif isinstance(el, Dimension):
            dims.append(el)
        elif isinstance(el, TextNote):
            texts.append(el)
        elif isinstance(el, CurveElement) and el.CurveElementType == CurveElementType.DetailCurve:
            curves.append(el)
    return dims, spots, tags, texts, curves


def do_annotations(view, T, link_b, collected):
    dims, spots, tags, texts, curves = collected
    new_ids = []
    results = []
    errors = []

    def process(items, fn, label):
        made = 0
        for it in items:
            try:
                ne = fn(it)
                if ne is not None:
                    new_ids.append(ne.Id.IntegerValue)
                    made += 1
            except Exception as ex:
                errors.append(u'{} id{}: {}'.format(label, it.Id.IntegerValue, str(ex)))
        results.append((label, len(items), made, len(items) - made))

    if not any([dims, spots, tags, texts, curves]):
        return results, new_ids, errors
    t = Transaction(doc, 'Mirror annotations to B')
    t.Start()
    process(dims,   lambda d: mirror_dim(d, T, link_b, view),   u'Dimensions')
    process(spots,  lambda s: mirror_spot(s, T, link_b, view),  u'Spots')
    process(tags,   lambda g: mirror_tag(g, T, link_b, view),   u'Tags')
    process(curves, lambda c: mirror_detail_curve(c, T, view),  u'Lines')
    process(texts,  lambda x: mirror_text(x, T, view),          u'Text')
    t.Commit()
    return results, new_ids, errors


# ============================================================
# Sections
# ============================================================
def collect_section_jobs(view, T, link_a, link_b):
    oa = link_a.GetTotalTransform().Origin
    ob = link_b.GetTotalTransform().Origin

    def building_of(p):
        da = (p.X - oa.X) ** 2 + (p.Y - oa.Y) ** 2
        db = (p.X - ob.X) ** 2 + (p.Y - ob.Y) ** 2
        return u'A' if da <= db else u'B'

    name_map = {}
    for s in FilteredElementCollector(doc).OfClass(ViewSection):
        try:
            if not s.IsTemplate and s.Name:
                name_map[s.Name] = s
        except Exception:
            pass

    viewers = list(FilteredElementCollector(doc, view.Id)
                   .OfCategory(BuiltInCategory.OST_Viewers).WhereElementIsNotElementType())
    jobs = []
    skipped = 0
    for m in viewers:
        try:
            nm = m.Name
        except Exception:
            nm = None
        target = name_map.get(nm) if nm else None
        if target is None:
            continue
        try:
            if target.GetPrimaryViewId() != ElementId.InvalidElementId:
                skipped += 1
                continue
        except Exception:
            pass
        bb = m.get_BoundingBox(view)
        if bb is None:
            continue
        c = (bb.Min + bb.Max).Multiply(0.5)
        if building_of(c) != u'A':
            continue
        idl = List[ElementId]()
        idl.Add(m.Id)
        try:
            if not ElementTransformUtils.CanMirrorElements(doc, idl):
                skipped += 1
                continue
        except Exception:
            skipped += 1
            continue
        orient = u'X' if (bb.Max.X - bb.Min.X) >= (bb.Max.Y - bb.Min.Y) else u'Y'
        is_ref = False
        try:
            p = m.get_Parameter(BuiltInParameter.VIEWER_IS_REFERENCE)
            is_ref = (p is not None and p.AsInteger() == 1)
        except Exception:
            pass
        jobs.append((nm, m, orient, c, target, is_ref))
    return jobs, skipped


def _bbox_line(bb):
    """Концы линии марки по длинной оси bbox (по центру короткой)."""
    cz = (bb.Min.Z + bb.Max.Z) / 2.0
    if (bb.Max.X - bb.Min.X) >= (bb.Max.Y - bb.Min.Y):
        cy = (bb.Min.Y + bb.Max.Y) / 2.0
        return XYZ(bb.Min.X, cy, cz), XYZ(bb.Max.X, cy, cz)
    cx = (bb.Min.X + bb.Max.X) / 2.0
    return XYZ(cx, bb.Min.Y, cz), XYZ(cx, bb.Max.Y, cz)


def _viewer_ids(view):
    return set(e.Id.IntegerValue for e in FilteredElementCollector(doc, view.Id)
               .OfCategory(BuiltInCategory.OST_Viewers).WhereElementIsNotElementType())


def do_sections(view, T, jobs, flip_look):
    """Марки разрезов на B. НЕ создаём новых разрезов:
       - существующий референс-callout -> зеркалим целиком (MirrorElements);
       - первичная марка настоящего разреза -> РЕФЕРЕНС на тот же разрез
         (CreateReferenceSection), без копии."""
    made = 0
    new_ids = []
    errors = []
    diag = []          # (nm, orient, kind, oid, nid)
    if not jobs:
        return made, new_ids, errors, diag

    plane = None
    for j in jobs:
        c = j[3]
        q = T.OfPoint(c)
        if (c - q).GetLength() > 1e-6:
            plane = Plane.CreateByNormalAndOrigin((c - q).Normalize(), (c + q).Multiply(0.5))
            break
    if plane is None:
        return made, new_ids, errors, diag

    reflected = T.HasReflection
    for nm, m, orient, c, target, is_ref in jobs:
        t1 = Transaction(doc, 'Mirror section mark')
        fo = t1.GetFailureHandlingOptions()
        fo.SetFailuresPreprocessor(_swallow)
        fo.SetClearAfterRollback(True)
        t1.SetFailureHandlingOptions(fo)
        t1.Start()
        nid = None
        kind = u'ref' if is_ref else u'newref'
        try:
            if is_ref:
                idl = List[ElementId]()
                idl.Add(m.Id)
                res = ElementTransformUtils.MirrorElements(doc, idl, plane, True)
                for r in ([x for x in res] if res else []):
                    el = doc.GetElement(r)
                    if el is None:
                        continue
                    nid = r
                    if flip_look:
                        bb = el.get_BoundingBox(view)
                        if bb is not None:
                            cx = (bb.Min.X + bb.Max.X) * 0.5
                            cy = (bb.Min.Y + bb.Max.Y) * 0.5
                            axis = Line.CreateBound(XYZ(cx, cy, 0.0), XYZ(cx, cy, 1.0))
                            ElementTransformUtils.RotateElement(doc, r, axis, math.pi)
            else:
                bb = m.get_BoundingBox(view)
                p0, p1 = _bbox_line(bb)
                h0 = T.OfPoint(p0)
                t0 = T.OfPoint(p1)
                vdA = target.ViewDirection
                vdA = XYZ(vdA.X, vdA.Y, 0.0)
                vdA = vdA.Normalize() if vdA.GetLength() > 1e-9 else XYZ.BasisX
                lk = T.OfVector(vdA)
                lk = XYZ(lk.X, lk.Y, 0.0)
                if reflected:
                    lk = XYZ(-lk.X, -lk.Y, 0.0)
                lk = lk.Normalize() if lk.GetLength() > 1e-9 else XYZ.BasisX
                d = t0 - h0
                if XYZ(d.Y, -d.X, 0.0).DotProduct(lk) < 0:
                    head, tail = t0, h0
                else:
                    head, tail = h0, t0
                before = _viewer_ids(view)
                ViewSection.CreateReferenceSection(doc, view.Id, target.Id, head, tail)
                doc.Regenerate()
                for eid in (_viewer_ids(view) - before):
                    nid = ElementId(eid)
                    break
            st = t1.Commit()
            if st != TransactionStatus.Committed:
                errors.append(u'{}: rolled back'.format(nm))
                continue
            if nid is not None:
                new_ids.append(nid.IntegerValue)
            diag.append((nm, orient, kind, m.Id, nid))
            made += 1
        except Exception as ex:
            try:
                if t1.HasStarted() and not t1.HasEnded():
                    t1.RollBack()
            except Exception:
                pass
            errors.append(u'{}: {}'.format(nm, str(ex)))
    return made, new_ids, errors, diag


def describe_mirror(T):
    inv_x = T.OfVector(XYZ.BasisX).X < 0
    inv_y = T.OfVector(XYZ.BasisY).Y < 0
    if T.HasReflection:
        if inv_x and not inv_y:
            return u'mirror across Y axis (flips X)'
        if inv_y and not inv_x:
            return u'mirror across X axis (flips Y)'
        return u'angled mirror'
    return u'NO mirror (links are not reflected) — check placement'


# ============================================================
# Candidate views
# ============================================================
def candidate_views(active_id):
    """Только планы. БЕЗ подсчёта объектов (чтобы окно открывалось мгновенно)."""
    out = []
    for v in FilteredElementCollector(doc).OfClass(View):
        try:
            if v.IsTemplate:
                continue
            if v.ViewType.ToString() not in PLAN_LIKE:
                continue
            # Зависимые виды делят аннотации с основным — запуск на них
            # продублировал бы теги/размеры. Пропускаем, оставляем основные.
            if v.GetPrimaryViewId() != ElementId.InvalidElementId:
                continue
            out.append(v)
        except Exception:
            pass
    out.sort(key=lambda v: (v.Id.IntegerValue != active_id, v.Name))
    return out


# ============================================================
# Dialog
# ============================================================
XAML_STR = u'''<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Mirror Building B" Width="520" Height="660"
    MinWidth="440" MinHeight="480"
    WindowStartupLocation="CenterScreen" ResizeMode="CanResize"
    Background="#F4F5F7" FontFamily="Segoe UI">
  <Grid Margin="18">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>

    <StackPanel Grid.Row="0" Margin="0,0,0,12">
      <TextBlock Text="Mirror building B from A" FontSize="18" FontWeight="Bold"
                 Foreground="#1A1A1A"/>
      <TextBlock x:Name="lblLinks" Text="" Foreground="#5A6472" Margin="0,2,0,0"/>
      <TextBlock x:Name="lblMirror" Text="" Foreground="#5A6472" Margin="0,1,0,0"
                 FontStyle="Italic"/>
    </StackPanel>

    <Border Grid.Row="1" Background="White" BorderBrush="#E0E3E8" BorderThickness="1"
            CornerRadius="6" Padding="14,12" Margin="0,0,0,10">
      <StackPanel>
        <TextBlock Text="WHAT TO MIRROR" FontSize="11" FontWeight="SemiBold"
                   Foreground="#8A93A0" Margin="0,0,0,8"/>
        <CheckBox x:Name="cbSec" Margin="0,2,0,2">
          <StackPanel>
            <TextBlock Text="Sections" FontWeight="SemiBold" FontSize="14"/>
            <TextBlock Text="section marks mirrored whole; dependent views skipped"
                       Foreground="#8A93A0" FontSize="12"/>
          </StackPanel>
        </CheckBox>
        <Separator Margin="0,8,0,8" Background="#EEF0F3"/>
        <CheckBox x:Name="cbAnn" Margin="0,2,0,2">
          <StackPanel>
            <TextBlock Text="Annotations" FontWeight="SemiBold" FontSize="14"/>
            <TextBlock Text="dimensions, tags, spot elevations, detail lines, text"
                       Foreground="#8A93A0" FontSize="12"/>
          </StackPanel>
        </CheckBox>
      </StackPanel>
    </Border>

    <Border Grid.Row="2" Background="White" BorderBrush="#E0E3E8" BorderThickness="1"
            CornerRadius="6" Padding="14,12" Margin="0,0,0,10">
      <StackPanel>
        <TextBlock Text="UPDATE MODE" FontSize="11" FontWeight="SemiBold"
                   Foreground="#8A93A0" Margin="0,0,0,8"/>
        <CheckBox x:Name="cbOvr">
          <StackPanel>
            <TextBlock Text="Overwrite" FontWeight="SemiBold" FontSize="14"/>
            <TextBlock Text="delete what this tool created on each view before, then recreate"
                       Foreground="#C0392B" FontSize="12"/>
          </StackPanel>
        </CheckBox>
      </StackPanel>
    </Border>

    <Border Grid.Row="3" Background="White" BorderBrush="#E0E3E8" BorderThickness="1"
            CornerRadius="6" Padding="14,12" Margin="0,0,0,14">
      <DockPanel>
        <DockPanel DockPanel.Dock="Top" Margin="0,0,0,6">
          <TextBlock Text="VIEWS TO RUN ON" FontSize="11" FontWeight="SemiBold"
                     Foreground="#8A93A0" VerticalAlignment="Center"/>
          <StackPanel Orientation="Horizontal" HorizontalAlignment="Right"
                      DockPanel.Dock="Right">
            <Button x:Name="btnAll" Content="All" Padding="8,1" Margin="0,0,6,0"
                    FontSize="11"/>
            <Button x:Name="btnNone" Content="None" Padding="8,1" FontSize="11"/>
          </StackPanel>
        </DockPanel>
        <Border BorderBrush="#EEF0F3" BorderThickness="1" CornerRadius="4">
          <ScrollViewer VerticalScrollBarVisibility="Auto">
            <StackPanel x:Name="viewsPanel" Margin="6"/>
          </ScrollViewer>
        </Border>
      </DockPanel>
    </Border>

    <StackPanel Grid.Row="4" Orientation="Horizontal" HorizontalAlignment="Right">
      <Button x:Name="btnCancel" Content="Cancel" Width="100" Height="34"
              Margin="0,0,8,0" FontSize="13"/>
      <Button x:Name="btnRun" Content="Run" Width="150" Height="34"
              FontSize="13" FontWeight="SemiBold" Foreground="White" Background="#2E7D32"
              BorderThickness="0"/>
    </StackPanel>

    <TextBlock Grid.Row="5" x:Name="lblHint" Text="" Foreground="#C0392B"
               FontSize="12" Margin="0,8,0,0" HorizontalAlignment="Right"/>
  </Grid>
</Window>'''


class MirrorDialog(object):
    def __init__(self, info, cand, active_id, settings):
        self.result = None
        self.view_cbs = []
        self.window = XamlReader.Parse(XAML_STR)
        w = self.window

        w.FindName('lblLinks').Text = u'Link A: {}   to   Link B: {}'.format(
            info['a_name'], info['b_name'])
        w.FindName('lblMirror').Text = info['mirror']

        self.cb_sec = w.FindName('cbSec')
        self.cb_ann = w.FindName('cbAnn')
        self.cb_ovr = w.FindName('cbOvr')
        self.lbl_hint = w.FindName('lblHint')
        panel = w.FindName('viewsPanel')

        self.cb_sec.IsChecked = settings['sec']
        self.cb_ann.IsChecked = settings['ann']
        self.cb_ovr.IsChecked = settings['ovr']

        reg = reg_read()
        for v in cand:
            cb = CheckBox()
            prev = len(reg.get(str(v.Id.IntegerValue), []))
            label = v.Name + (u'    (mirrored {})'.format(prev) if prev else u'')
            cb.Content = label
            cb.Tag = v.Id.IntegerValue
            cb.IsChecked = (v.Id.IntegerValue == active_id)
            cb.Margin = Thickness(0, 2, 0, 2)
            cb.FontSize = 13
            panel.Children.Add(cb)
            self.view_cbs.append(cb)

        w.FindName('btnRun').Click += self._on_run
        w.FindName('btnCancel').Click += self._on_cancel
        w.FindName('btnAll').Click += self._on_all
        w.FindName('btnNone').Click += self._on_none

    def _on_all(self, s, a):
        for cb in self.view_cbs:
            cb.IsChecked = True

    def _on_none(self, s, a):
        for cb in self.view_cbs:
            cb.IsChecked = False

    def _on_run(self, s, a):
        sec = bool(self.cb_sec.IsChecked)
        ann = bool(self.cb_ann.IsChecked)
        ovr = bool(self.cb_ovr.IsChecked)
        views = [int(cb.Tag) for cb in self.view_cbs if bool(cb.IsChecked)]
        if not (sec or ann or ovr):
            self.lbl_hint.Text = u'Pick at least one action.'
            return
        if not views:
            self.lbl_hint.Text = u'Pick at least one view.'
            return
        self.result = {'sec': sec, 'ann': ann, 'ovr': ovr, 'views': views}
        self.window.DialogResult = True

    def _on_cancel(self, s, a):
        self.window.DialogResult = False

    def show(self):
        self.window.ShowDialog()
        return self.result


# ============================================================
# Main
# ============================================================
link_a = find_link_a()
if link_a is None:
    forms.alert(u'No link-bound annotations found — pick link A (building A) manually.',
                title='Mirror Building')
    try:
        picked = uidoc.Selection.PickObject(ObjectType.Element, _LinkFilter(),
                                            u'Pick link of building A')
        link_a = doc.GetElement(picked.ElementId)
    except OperationCanceledException:
        script.exit()

cands = [li for li in FilteredElementCollector(doc).OfClass(RevitLinkInstance)
         if li.Id != link_a.Id and li.GetTypeId() == link_a.GetTypeId()]
if not cands:
    forms.alert(u'Second instance of the link (building B) not found.',
                title='Mirror Building')
    script.exit()
link_b = cands[0] if len(cands) == 1 else forms.SelectFromList.show(
    cands, name_attr='Name', title=u'Pick link B', button_name=u'This is building B')
if link_b is None:
    script.exit()

T = link_b.GetTotalTransform().Multiply(link_a.GetTotalTransform().Inverse)
flip_look = T.HasReflection

active_id = doc.ActiveView.Id.IntegerValue if doc.ActiveView is not None else -1
cand = candidate_views(active_id)
if not cand:
    forms.alert(u'No plan/section views with content found.', title='Mirror Building')
    script.exit()

info = {'a_name': link_a.Name, 'b_name': link_b.Name, 'mirror': describe_mirror(T)}
dlg = MirrorDialog(info, cand, active_id, get_settings())
choice = dlg.show()
if not choice:
    script.exit()
save_settings({'sec': choice['sec'], 'ann': choice['ann'], 'ovr': choice['ovr']})

want_sec = choice['sec']
want_ann = choice['ann']
overwrite = choice['ovr']
view_ids = choice['views']

# per-view processing
per_view = []   # (view_name, sec_made, sec_skip, sec_diag, ann_results, deleted, errs)
grand_new = 0
for vid in view_ids:
    v = doc.GetElement(ElementId(int(vid)))
    if v is None:
        continue
    vkey = str(vid)
    deleted = prev = 0
    if overwrite:
        t = Transaction(doc, 'Delete previously mirrored')
        t.Start()
        deleted, prev = delete_registered(vkey)
        t.Commit()

    all_new = []
    sec_made = sec_skip = 0
    sec_errors = []
    sec_diag = []
    ann_results = []
    ann_errors = []

    if want_sec:
        jobs, sec_skip = collect_section_jobs(v, T, link_a, link_b)
        sec_made, sec_new, sec_errors, sec_diag = do_sections(v, T, jobs, flip_look)
        all_new.extend(sec_new)
    if want_ann:
        coll = collect_annotations(v)
        ann_results, ann_new, ann_errors = do_annotations(v, T, link_b, coll)
        all_new.extend(ann_new)

    reg = reg_read()
    existing = [] if overwrite else reg.get(vkey, [])
    reg[vkey] = list(existing) + [int(x) for x in all_new]
    reg_write(reg)

    grand_new += len(all_new)
    per_view.append((v.Name, sec_made, sec_skip, sec_diag, ann_results,
                     deleted, sec_errors + ann_errors))

# ============================================================
# Report
# ============================================================
output.print_md(u'# Mirror Building B')
output.print_md(u'- Link A: {}  ->  Link B: {}'.format(link_a.Name, link_b.Name))
output.print_md(u'- {}  |  arrow flip: **{}**'.format(
    describe_mirror(T), u'on' if flip_look else u'off'))
output.print_md(u'- Views processed: **{}**, created total: **{}**'.format(
    len(per_view), grand_new))

for vname, sec_made, sec_skip, sec_diag, ann_results, deleted, errs in per_view:
    output.print_md(u'## {}'.format(vname))
    if overwrite:
        output.print_md(u'- overwrite: deleted **{}**'.format(deleted))
    if want_sec:
        output.print_md(u'- sections: created **{}**, skipped {}'.format(sec_made, sec_skip))
        if sec_diag:
            rows = []
            for nm, orient, kind, oid, nid in sec_diag:
                a = output.linkify(oid) if oid is not None else u'—'
                b = output.linkify(nid) if nid is not None else u'—'
                tp = u'reference' if kind == u'ref' else u'reference (new)'
                rows.append([nm, orient, tp, a, b])
            output.print_table(table_data=rows,
                               columns=[u'Section', u'Axis', u'Type', u'A', u'B'])
    if want_ann and ann_results:
        output.print_table(table_data=[[r[0], r[1], r[2], r[3]] for r in ann_results],
                           columns=[u'Category', u'Found', u'Created', u'Failed'])
    for e in errs[:10]:
        output.print_md(u'- {}'.format(e))

run.finish(summary=u'views={} sec={} ann={} ovr={} flip={} created={}'.format(
    len(view_ids), want_sec, want_ann, overwrite, flip_look, grand_new))
