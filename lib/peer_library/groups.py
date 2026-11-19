# -*- coding: utf-8 -*-
"""Library groups = top folders of PEER-Library. Order = order in the window."""

GROUPS = [
    ('01_Framing', u'Framing', u'Beams, columns, profiles, precast'),
    ('02_Foundations', u'Foundations', u'Footings, piles, pile caps, anchors'),
    ('03_Rebar_2D', u'Rebar 2D', u'2D rebar shapes, rebar annotations, area/path symbols'),
    ('04_Rebar_3D_Embeds', u'Rebar 3D & embeds', u'Rebar shapes, cast-in parts, anchors, channels'),
    ('05_Details', u'Details', u'Detail components, typical details'),
    ('06_Tags', u'Tags & symbols', u'Tags, symbols, grid heads, elevations, titles'),
    ('07_Sheets', u'Sheets', u'Title blocks'),
    ('08_Steel', u'Steel', u'Steel profiles, trusses, decks, steel connections'),
    ('09_Openings', u'Openings', u'Openings, sleeves, voids'),
]

ARCHIVE = '_Archive'

GROUP_IDS = [g[0] for g in GROUPS]


def title(group_id):
    for g in GROUPS:
        if g[0] == group_id:
            return g[1]
    return group_id
