# -*- coding: utf-8 -*-
"""Search in the library window: what a query matches and in what order.

- every word of the query must match (name, ID, tags, category, types,
  description);
- spaces and separators do not matter: "he 200 a", "HE200A", "he-200a";
- Russian and Hebrew words find the English names (колонна, עמוד -> column);
- results: name matches first, then ID / tags / types, then description.
Pure Python (no Revit) - tested in tests/test_core.py.
"""

import re

_SEP = re.compile(u'[\\s_\\-\\.,/\\\\()\\[\\]]+', re.UNICODE)
_INVISIBLE = dict((c, None) for c in (0x200E, 0x200F, 0x202A, 0x202B, 0x202C, 0xFEFF))

# query word (lower case) -> English words it also finds. Kept short on
# purpose: the structural vocabulary of the office.
SYNONYMS = {
    u'колонна': [u'column'], u'колонны': [u'column'], u'עמוד': [u'column'], u'עמודים': [u'column'],
    u'балка': [u'beam'], u'балки': [u'beam'], u'קורה': [u'beam'], u'קורות': [u'beam'],
    u'плита': [u'slab', u'floor'], u'перекрытие': [u'slab', u'floor'], u'תקרה': [u'slab'],
    u'רצפה': [u'floor', u'slab'], u'רפסודה': [u'raft', u'mat'],
    u'фундамент': [u'foundation', u'footing'], u'יסוד': [u'foundation', u'footing'],
    u'свая': [u'pile'], u'сваи': [u'pile'], u'כלונס': [u'pile'], u'כלונסאות': [u'pile'],
    u'ростверк': [u'pile cap', u'cap'], u'ראש': [u'cap', u'head'],
    u'стена': [u'wall'], u'стены': [u'wall'], u'קיר': [u'wall'], u'קירות': [u'wall'],
    u'арматура': [u'rebar', u'reinforcement'], u'стержень': [u'rebar', u'bar'],
    u'זיון': [u'rebar', u'reinforcement'], u'ברזל': [u'rebar', u'steel'],
    u'хомут': [u'stirrup'], u'חישוק': [u'stirrup'], u'форма': [u'shape'],
    u'марка': [u'tag'], u'тег': [u'tag'], u'תג': [u'tag'],
    u'лист': [u'sheet'], u'штамп': [u'title', u'sheet'], u'גיליון': [u'sheet'],
    u'разрез': [u'section'], u'сечение': [u'section'], u'חתך': [u'section'],
    u'отверстие': [u'opening'], u'проём': [u'opening'], u'проем': [u'opening'],
    u'פתח': [u'opening'], u'גומחה': [u'pocket', u'niche'], u'карман': [u'pocket'],
    u'лестница': [u'stair'], u'מדרגות': [u'stair'],
    u'деталь': [u'detail'], u'узел': [u'detail'], u'פרט': [u'detail'],
    u'анкер': [u'anchor', u'bolt'], u'болт': [u'bolt'], u'עוגן': [u'anchor'], u'בורג': [u'bolt'],
    u'закладная': [u'embed', u'plate'], u'пластина': [u'plate'], u'פלטה': [u'plate'],
    u'уголок': [u'angle'], u'швеллер': [u'channel', u'upn', u'upe'], u'двутавр': [u'ipe', u'he'],
    u'профиль': [u'profile'], u'פרופיל': [u'profile'],
    u'труба': [u'pipe'], u'צינור': [u'pipe'],
    u'уровень': [u'level'], u'отметка': [u'level', u'elevation'], u'מפלס': [u'level'],
    u'ось': [u'grid'], u'оси': [u'grid'], u'ציר': [u'grid'],
    u'обрыв': [u'break'], u'грунт': [u'ground', u'soil'], u'קרקע': [u'ground', u'soil'],
    u'бетон': [u'concrete'], u'בטון': [u'concrete'], u'сталь': [u'steel'], u'פלדה': [u'steel'],
}


def normalize(text):
    """Lower case, ё = е, without invisible direction marks."""
    t = (text or u'').lower().replace(u'ё', u'е')
    try:
        return t.translate(_INVISIBLE)
    except TypeError:                                     # py2 str
        return t


def compact(text):
    return _SEP.sub(u'', normalize(text))


def query_words(query):
    return [w for w in _SEP.split(normalize(query)) if w]


class Entry(object):
    """Search texts of one card, built once."""

    def __init__(self, card):
        name = card.get('name') or u''
        fields = {
            'name': name,
            'key': u' '.join([card.get('id') or u'', u' '.join(card.get('tags') or []),
                              card.get('revit_category') or u'',
                              u' '.join(card.get('types') or [])]),
            'desc': card.get('description') or u'',
        }
        self.text = dict((k, normalize(v)) for k, v in fields.items())
        self.flat = dict((k, compact(v)) for k, v in fields.items())
        self.name = self.text['name']
        self.category = normalize(card.get('revit_category') or u'')

    def _word_in(self, word, field):
        for w in [word] + SYNONYMS.get(word, []):
            if w in self.text[field] or compact(w) in self.flat[field]:
                return True
        return False

    def score(self, words, phrase=u''):
        """None = no match. Lower = better: 0 name starts with the query,
        1 all words in the name, 2 in name/ID/tags/types, 3 description too."""
        if not words:
            return 4
        where = []
        for w in words:
            if self._word_in(w, 'name'):
                where.append(1)
            elif self._word_in(w, 'key'):
                where.append(2)
            elif self._word_in(w, 'desc'):
                where.append(3)
            else:
                return None
        best = max(where)
        if best == 1 and phrase and self.flat['name'].startswith(compact(phrase)):
            return 0
        return best


    def in_category(self, words):
        """A query word names the Revit category ('column' -> Structural Columns):
        such families go first among equal matches."""
        for w in words:
            for alt in [w] + SYNONYMS.get(w, []):
                if len(alt) > 2 and alt in self.category:
                    return True
        return False

    def order_key(self, words, phrase=u''):
        """Sort key among matches (lower = first), None = no match."""
        s = self.score(words, phrase)
        if s is None:
            return None
        return (s, 0 if words and self.in_category(words) else 1)


def rank(entries, query):
    """[(index, score)] of the matching entries, best first, stable."""
    words = query_words(query)
    out = []
    for i, e in enumerate(entries):
        k = e.order_key(words, query)
        if k is not None:
            out.append((k, i))
    out.sort()
    return [(i, k[0]) for k, i in out]
