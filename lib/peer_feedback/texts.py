# -*- coding: utf-8 -*-
"""Window strings and choice lists. Codes go to the table; labels are shown.

Codes are stable: the weekly summary and the receiver group by them, so a
label can be reworded without touching the data.
"""

# (code, label, when to pick)
TOPICS = [
    ('automation', u'Automation', u'"I want a button that..."'),
    ('improve', u'Improve a button', u'An existing button is awkward to use - pick it below'),
    ('bug', u'Bug', u'A script crashed or gave a wrong result - pick it below'),
    ('idea', u'Idea', u'A process suggestion, not necessarily about scripts'),
    ('routine', u'Routine', u'"I keep doing this by hand", no solution in mind'),
    ('template', u'Template & families', u'A family, type or parameter is missing'),
    ('howto', u'How-to question', u'Not clear how to do a task in Revit or PEER'),
    ('standard', u'Office standard', u'An office rule is unclear or inconvenient'),
]
TOPIC_CODES = [t[0] for t in TOPICS]
# topics where the button list is shown
TOPICS_WITH_BUTTON = ('improve', 'bug')

FREQUENCY = [
    ('', u'(not set)'),
    ('daily', u'Every day'),
    ('weekly', u'Every week'),
    ('rare', u'Rarely'),
]
DURATION = [
    ('', u'(not set)'),
    ('lt5', u'Up to 5 min'),
    ('5to30', u'5-30 min'),
    ('gt30', u'More than 30 min'),
]
FREQUENCY_CODES = [c for c, _ in FREQUENCY]
DURATION_CODES = [c for c, _ in DURATION]

STRINGS = {
    'title': u'Contact the head of the group',
    'how_to': u'Pick a topic and describe what you need in a few sentences. '
              u'Project, view and Revit version are added automatically '
              u'(listed at the bottom). You can see the status of your '
              u'request later in PEER.',
    'topic': u'Topic:',
    'button': u'Which button:',
    'text': u'What do you need? (required)',
    'frequency': u'How often:',
    'duration': u'Time per occurrence:',
    'context': u'Added automatically:',
    'send': u'Send',
    'cancel': u'Cancel',
    'no_button': u'(not about a specific button)',
    'err_text': u'Please describe the request in the text field.',
    'err_button': u'Please pick the button this is about.',
    'sent': u'Sent. Thank you!',
    'queued': u'No connection to the receiver right now.\n'
              u'The request is saved on this computer and will be sent '
              u'automatically on the next Revit start.',
    'not_configured': u'The receiver is not set up yet.\n'
                      u'The request is saved on this computer and will be sent '
                      u'as soon as the receiver address is set.',
}


def s(key):
    return STRINGS[key]
