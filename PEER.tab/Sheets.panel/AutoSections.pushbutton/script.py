# -*- coding: utf-8 -*-
__title__ = 'Auto Sections\n(Unique)'
__author__ = 'Dmitry D'
__doc__ = ('Version = 5.1\n'
           'Build transverse sections at the windows and/or beams of the ACTIVE '
           'level plan.\n\n'
           'Each window section is a thin (10 mm) slice at the window position, '
           'cropped between the lower window head and this window sill - so it '
           'shows only the floor slab and the concrete wall between the stacked '
           'windows (the windows are cropped out).\n\n'
           'Each beam section is a transverse cross-section, widened to 1000 mm '
           'toward the side(s) that carry a slab and kept tight (500 mm) above/'
           'below and on any slab-free side.\n\n'
           'Only UNIQUE nodes get a real section; repeated nodes get a REFERENCE '
           'marker pointing at the first one. Window uniqueness = wall thickness '
           '+ slab thickness + spandrel height; beam uniqueness = cross-section '
           '(b x h) + slab side context + vertical offset to the slab (the beam '
           'family/type is ignored).\n\n'
           'How-To: open the level plan, run, choose categories and sections per '
           'sheet.')

from pyrevit import revit, script
from pyrevit.forms import alert
from Autodesk.Revit.DB import ViewPlan

from AutoSections import collect as C
from AutoSections import signatures as SG
from AutoSections import sections as SC
from AutoSections import sheets as SH
from AutoSections import ui as UI

doc = revit.doc
output = script.get_output()


# --- run context: must be a plan view tied to a level ----------------------

active_view = revit.active_view
if not isinstance(active_view, ViewPlan) or active_view.IsTemplate:
    alert('Open a plan view of the level you want, then run the tool.')
    script.exit()

level = active_view.GenLevel
if level is None:
    alert('The active plan view is not associated with a level.')
    script.exit()
level_id = level.Id


# --- inputs ----------------------------------------------------------------

choice = UI.ask_categories()
if not choice:
    script.exit()
want_windows, want_beams = choice

per_sheet = UI.ask_per_sheet()
if per_sheet is None:
    script.exit()

vft = C.section_view_family_type(doc)
if vft is None:
    alert('No Section ViewFamilyType found in the project.')
    script.exit()


# --- collect (only this level) ---------------------------------------------

targets = C.collect_targets(doc, want_windows, want_beams, level_id)
if not targets:
    alert('No windows or beams found on level "{}".'.format(level.Name))
    script.exit()


# --- group by signature ----------------------------------------------------

groups, errors = SG.build_groups(doc, targets)
if not groups:
    alert('Could not build any signatures.')
    script.exit()


# --- real sections (one per group) -----------------------------------------

created, e_real = SC.create_real_sections(doc, vft.Id, groups)
errors += e_real
if not created:
    alert('No sections created.\n' + '\n'.join(errors[:5]))
    script.exit()


# --- reference markers on every duplicate ----------------------------------

ref_count, e_ref = SC.create_reference_sections(doc, active_view, created)
errors += e_ref


# --- lay the real views out on sheets --------------------------------------

tb_id = C.title_block_type_id(doc)
placed, e_sheet = SH.layout_on_sheets(
    doc, tb_id, [c['view'] for c in created], per_sheet)
errors += e_sheet


# --- report ----------------------------------------------------------------

rows = [[output.linkify(c['view'].Id), c['view'].Name, c['count']]
        for c in created]
output.print_table(table_data=rows,
                   columns=['View', 'Name', 'Members in group'])

scanned = len(targets)
output.print_md(
    '**Elements scanned:** {}  |  **Unique real sections:** {}  |  '
    '**Reference markers:** {}  |  **Duplicates collapsed:** {}  |  '
    '**Sheets created:** {}'.format(
        scanned, len(created), ref_count,
        scanned - len(created), len(placed)))

if errors:
    output.print_md('### Warnings ({})'.format(len(errors)))
    for w in errors[:15]:
        output.print_md(u'- {}'.format(w))
