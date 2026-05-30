# -*- coding: utf-8 -*-
"""User prompts for the Auto Sections tool. English UI."""

from pyrevit import forms


def ask_categories():
    """Ask which categories to process.

    Returns (want_windows, want_beams), or None if the user cancelled.
    """
    choice = forms.SelectFromList.show(
        ['Windows', 'Beams'],
        title='Categories for sections',
        multiselect=True, button_name='OK')
    if not choice:
        return None
    return ('Windows' in choice), ('Beams' in choice)


def ask_per_sheet(default=4):
    """Ask how many sections per sheet.

    Returns a positive int, or None if the user cancelled the prompt.
    """
    answer = forms.ask_for_string(
        default=str(default),
        prompt='How many sections per sheet?',
        title='Layout')
    if answer is None:
        return None
    try:
        return max(1, int(answer))
    except Exception:
        return default
