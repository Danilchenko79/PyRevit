# -*- coding: utf-8 -*-
"""Reinforcement rules of a column section. Pure Python, millimetres.

Every rule is one function and says where it comes from (SOURCE_*), so a
change to match the standard is a change in one place and in one test.
Until the clauses of SI 466 are checked, every rule here is the logic of
the old Create Column script, moved as it was.
"""

import math

RECT, ROUND2, ROUND1 = 'RECT', 'ROUND2', 'ROUND1'
SHAPES = (RECT, ROUND2, ROUND1)
SHAPE_ORDER = {RECT: 0, ROUND2: 1, ROUND1: 2, 'CIRCLE': 3}

SOURCE_OLD_SCRIPT = u'old script'       # moved as it was, not checked
SOURCE_OFFICE = u'office rule'          # said by the user
SOURCE_ESTIMATE = u'estimate'           # stands in for a family formula

STIRRUP, TIE = 'stirrup', 'tie'
VERTICAL, HORIZONTAL = 'vertical', 'horizontal'

# Detail families that draw the bar (PEER_Rebar_Shape NN).
STIRRUP_SHAPE = {RECT: 52, ROUND1: 60, ROUND2: None}   # ROUND2: not defined yet
TIE_SHAPE = 62

TIE_SPACING_LIMIT = 150.0      # mm between bars of a side; above it every bar is tied
DEFAULT_SPACING = 200.0        # mm along the column, stirrups and ties
DEFAULT_COVER = 25.0
DEFAULT_STIRRUP_DIA = 8.0
DEFAULT_TIE_DIA = 10.0


def total_bars(shape, qb, qh):
    """Longitudinal bars in the section.                    [old script]

    RECT:    qb / qh are the bars of ONE side without the 4 corner bars.
    rounded: the corner / tangent bars are counted in qh, no extra corners.
    Nothing entered (both 0) is 0, not 4."""
    qb, qh = int(qb), int(qh)
    if qb == 0 and qh == 0:
        return 0
    if shape == RECT:
        return 4 + 2 * qb + 2 * qh
    return 2 * (qb + qh)


def stirrup_size(b, h, cover):
    """(A, B) of the stirrup: section minus the cover on both sides.
    The cover is measured to the stirrup.                   [old script]"""
    return max(0.0, b - 2.0 * cover), max(0.0, h - 2.0 * cover)


def tie_length(side, cover):
    """Length of a tie across the section side.             [old script]"""
    return max(0.0, side - 2.0 * cover)


def tied_bars(q, shape):
    """How many bars of a side may get a tie at all.        [old script]

    Rounded shapes: 2 bars are taken off (corner / tangent bars get no tie).
    OPEN QUESTION: the old script takes 2 off qb as well, though by the
    legend qb of a rounded shape does not hold the tangent bars."""
    q = int(q)
    if shape in (ROUND1, ROUND2):
        q -= 2
    return max(0, q)


def tie_count(q, spacing, shape):
    """Ties of one direction in the section.                [office rule, 2026-08]

    Bars of the side further apart than 150 mm -> a tie on every bar;
    else a tie on every second bar: roundup(q / 2) - 1.
    spacing None (the family did not give it) counts as 'further apart'."""
    q = tied_bars(q, shape)
    if q <= 0:
        return 0
    if spacing is None or spacing > TIE_SPACING_LIMIT:
        return q
    return int(math.ceil(q / 2.0)) - 1


def estimate_spacing(side, q, cover, stirrup_dia, bar_dia):
    """Centre-to-centre spacing of the bars of a RECT side.  [estimate]

    Only for when the 2D family did not report Rebar_SpacingX / Y: the
    family formula is the truth and has to be compared with this."""
    q = int(q)
    span = side - 2.0 * (cover + stirrup_dia) - bar_dia
    if span <= 0:
        return None
    return span / (q + 1.0)


def transverse(shape, b, h, qb, qh,
               cover=DEFAULT_COVER,
               stirrup_dia=DEFAULT_STIRRUP_DIA, tie_dia=DEFAULT_TIE_DIA,
               stirrup_spacing=DEFAULT_SPACING, tie_spacing=DEFAULT_SPACING,
               spacing_b=None, spacing_h=None,
               vertical_ties=True, horizontal_ties=True):
    """Transverse reinforcement of the section, in drawing order.

    spacing_b / spacing_h   bar spacing along the B / H side (from the family)
    vertical_ties / horizontal_ties   the family's HasVerticalSpacer /
        HasHorizontalSpacer; True when the family does not decide.

    Each item: kind, direction, family_shape (PEER_Rebar_Shape NN), a, b,
    dia, spacing, qty (pieces in one section)."""
    out = []
    if STIRRUP_SHAPE.get(shape):
        a, bb = stirrup_size(b, h, cover)
        out.append({'kind': STIRRUP, 'direction': None,
                    'family_shape': STIRRUP_SHAPE[shape],
                    'a': a, 'b': bb, 'dia': stirrup_dia,
                    'spacing': stirrup_spacing, 'qty': 1})
    # A vertical tie runs along H and holds the bars of the B sides.
    for on, direction, q, sp, side in (
            (vertical_ties, VERTICAL, qb, spacing_b, h),
            (horizontal_ties, HORIZONTAL, qh, spacing_h, b)):
        qty = tie_count(q, sp, shape) if on else 0
        if qty > 0:
            out.append({'kind': TIE, 'direction': direction,
                        'family_shape': TIE_SHAPE,
                        'a': None, 'b': tie_length(side, cover),
                        'dia': tie_dia, 'spacing': tie_spacing, 'qty': qty})
    return out


def missing(qb, qh, dia):
    """What stops a group from being drawn: names for the report."""
    out = []
    if int(qb) == 0 and int(qh) == 0:
        out.append(u'Rebar_Quantity')
    if not dia:
        out.append(u'Rebar_Diameter')
    return out
