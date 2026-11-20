# -*- coding: utf-8 -*-
"""The section sketch on a WPF Canvas (IronPython 2.7, no Revit).

Draws exactly what sketch.svg draws (the gallery picture): the SVG text is
parsed and every element becomes a WPF shape, so the window and the gallery
never disagree.
"""

import re
import xml.etree.ElementTree as ET

from System.Windows import Point, Size
from System.Windows.Controls import Canvas, TextBlock
from System.Windows.Media import (BrushConverter, DoubleCollection, Geometry, PointCollection,
                                  RotateTransform)
from System.Windows.Shapes import Ellipse, Line, Path, Polygon, Polyline, Rectangle

from column_rebar import sketch

_bc = BrushConverter()
NS = '{http://www.w3.org/2000/svg}'


def _brush(v):
    if not v or v == 'none':
        return None
    return _bc.ConvertFromString(v)


def _f(e, k, d=0.0):
    try:
        return float(e.get(k, d))
    except (TypeError, ValueError):
        return d


def _stroke(shape, e):
    s = _brush(e.get('stroke'))
    if s is not None:
        shape.Stroke = s
    shape.StrokeThickness = _f(e, 'stroke-width', 1.0)
    f = _brush(e.get('fill'))
    if f is not None and hasattr(shape, 'Fill'):
        shape.Fill = f
    dash = e.get('stroke-dasharray')
    if dash:
        w = max(shape.StrokeThickness, 0.5)
        dc = DoubleCollection()
        for v in dash.split():
            dc.Add(float(v) / w)
        shape.StrokeDashArray = dc


def _points(txt):
    pc = PointCollection()
    for pair in txt.split():
        x, y = pair.split(',')
        pc.Add(Point(float(x), float(y)))
    return pc


def render(canvas, result, b, h, cover, bar_dia, size=300.0):
    """Clears canvas and draws the section; returns (width, height) used."""
    canvas.Children.Clear()
    if not result or not result.get('stirrup'):
        return 0.0, 0.0
    svg = sketch.svg(result, b, h, cover, bar_dia, size=size, margin=40.0)
    root = ET.fromstring(svg.encode('utf-8'))
    W, H = _f(root, 'width'), _f(root, 'height')
    canvas.Width, canvas.Height = W, H
    for e in root:
        tag = e.tag.replace(NS, '')
        sh = None
        if tag == 'rect':
            sh = Rectangle()
            sh.Width, sh.Height = _f(e, 'width'), _f(e, 'height')
            sh.RadiusX = sh.RadiusY = _f(e, 'rx')
            Canvas.SetLeft(sh, _f(e, 'x'))
            Canvas.SetTop(sh, _f(e, 'y'))
            _stroke(sh, e)
        elif tag == 'circle':
            r = _f(e, 'r')
            sh = Ellipse()
            sh.Width = sh.Height = 2 * r
            Canvas.SetLeft(sh, _f(e, 'cx') - r)
            Canvas.SetTop(sh, _f(e, 'cy') - r)
            _stroke(sh, e)
        elif tag == 'line':
            sh = Line()
            sh.X1, sh.Y1, sh.X2, sh.Y2 = _f(e, 'x1'), _f(e, 'y1'), _f(e, 'x2'), _f(e, 'y2')
            _stroke(sh, e)
        elif tag in ('polyline', 'polygon'):
            sh = Polyline() if tag == 'polyline' else Polygon()
            sh.Points = _points(e.get('points'))
            _stroke(sh, e)
        elif tag == 'path':
            sh = Path()
            sh.Data = Geometry.Parse(e.get('d'))      # SVG path syntax = WPF mini-language here
            _stroke(sh, e)
        elif tag == 'text':
            sh = TextBlock()
            sh.Text = e.text or u''
            sh.FontSize = 10.0
            fill = _brush(e.get('fill'))
            if fill is not None:
                sh.Foreground = fill
            x, y = _f(e, 'x'), _f(e, 'y')
            anchor = e.get('text-anchor')
            sh.Measure(Size(1e4, 1e4))
            w, hh = sh.DesiredSize.Width, sh.DesiredSize.Height
            dx = -w / 2.0 if anchor == 'middle' else 0.0
            Canvas.SetLeft(sh, x + dx)
            Canvas.SetTop(sh, y - hh * 0.8)
            m = re.match(r'rotate\(([-\d.]+) ([-\d.]+) ([-\d.]+)\)', e.get('transform') or '')
            if m:
                sh.RenderTransformOrigin = Point(0.5, 0.8)
                sh.RenderTransform = RotateTransform(float(m.group(1)))
        if sh is not None:
            canvas.Children.Add(sh)
    return W, H
