# -*- coding: utf-8 -*-
"""Window strings and choice lists. Codes go to the table; labels are shown.

Codes are stable: the weekly summary and the receiver group by them, so a
label can be reworded or translated without touching the data.
Language = config 'lang' (en / ru). Missing string -> English.
"""

# (code, {lang: (label, when to pick)})
TOPICS = [
    ('automation', {
        'en': (u'Automation', u'"I want a button that..."'),
        'ru': (u'Автоматизация', u'«Хочу кнопку, которая…»')}),
    ('improve', {
        'en': (u'Improve a button', u'An existing button is awkward to use - pick it below'),
        'ru': (u'Улучшить кнопку', u'Существующая кнопка работает неудобно - выберите её ниже')}),
    ('bug', {
        'en': (u'Bug', u'A script crashed or gave a wrong result - pick it below'),
        'ru': (u'Баг', u'Скрипт упал или дал неверный результат - выберите его ниже')}),
    ('idea', {
        'en': (u'Idea', u'A process suggestion, not necessarily about scripts'),
        'ru': (u'Идея', u'Предложение по процессу, не обязательно про скрипты')}),
    ('routine', {
        'en': (u'Routine', u'"I keep doing this by hand", no solution in mind'),
        'ru': (u'Рутина', u'«Делаю это руками постоянно», без идеи решения')}),
    ('template', {
        'en': (u'Template & families', u'A family, type or parameter is missing'),
        'ru': (u'Шаблон и семейства', u'Не хватает семейства, типа, параметра')}),
    ('howto', {
        'en': (u'How-to question', u'Not clear how to do a task in Revit or PEER'),
        'ru': (u'Вопрос «как сделать»', u'Непонятно, как выполнить задачу в Revit или PEER')}),
    ('standard', {
        'en': (u'Office standard', u'An office rule is unclear or inconvenient'),
        'ru': (u'Стандарт', u'Правило офиса непонятно или неудобно')}),
]
TOPIC_CODES = [t[0] for t in TOPICS]
# topics where the button list is shown
TOPICS_WITH_BUTTON = ('improve', 'bug')

FREQUENCY = [
    ('', {'en': u'(not set)', 'ru': u'(не указано)'}),
    ('daily', {'en': u'Every day', 'ru': u'Каждый день'}),
    ('weekly', {'en': u'Every week', 'ru': u'Каждую неделю'}),
    ('rare', {'en': u'Rarely', 'ru': u'Редко'}),
]
DURATION = [
    ('', {'en': u'(not set)', 'ru': u'(не указано)'}),
    ('lt5', {'en': u'Up to 5 min', 'ru': u'До 5 минут'}),
    ('5to30', {'en': u'5-30 min', 'ru': u'5–30 минут'}),
    ('gt30', {'en': u'More than 30 min', 'ru': u'Больше 30 минут'}),
]
FREQUENCY_CODES = [c for c, _ in FREQUENCY]
DURATION_CODES = [c for c, _ in DURATION]

STRINGS = {
    'title': {
        'en': u'Contact the head of the group',
        'ru': u'Связь с руководителем группы'},
    'how_to': {
        'en': u'Pick a topic and describe what you need in a few sentences. '
              u'Project, view and Revit version are added automatically '
              u'(listed at the bottom). You can see the status of your '
              u'request later in PEER.',
        'ru': u'Выберите тему и опишите в паре предложений, что нужно. '
              u'Проект, вид и версия Revit добавятся сами (список внизу). '
              u'Статус запроса потом видно в PEER.'},
    'topic': {'en': u'Topic:', 'ru': u'Тема:'},
    'button': {'en': u'Which button:', 'ru': u'Какая кнопка:'},
    'text': {'en': u'What do you need? (required)', 'ru': u'Что нужно? (обязательно)'},
    'frequency': {'en': u'How often:', 'ru': u'Как часто:'},
    'duration': {'en': u'Time per occurrence:', 'ru': u'Время за один раз:'},
    'context': {'en': u'Added automatically:', 'ru': u'Добавится автоматически:'},
    'send': {'en': u'Send', 'ru': u'Отправить'},
    'cancel': {'en': u'Cancel', 'ru': u'Отмена'},
    'no_button': {'en': u'(not about a specific button)', 'ru': u'(не про конкретную кнопку)'},
    'err_text': {
        'en': u'Please describe the request in the text field.',
        'ru': u'Опишите запрос в поле текста.'},
    'err_button': {
        'en': u'Please pick the button this is about.',
        'ru': u'Выберите кнопку, о которой речь.'},
    'sent': {
        'en': u'Sent. Thank you!',
        'ru': u'Отправлено. Спасибо!'},
    'queued': {
        'en': u'No connection to the receiver right now.\n'
              u'The request is saved on this computer and will be sent '
              u'automatically on the next Revit start.',
        'ru': u'Сейчас нет связи с приёмником.\n'
              u'Запрос сохранён на этом компьютере и уйдёт автоматически '
              u'при следующем запуске Revit.'},
    'not_configured': {
        'en': u'The receiver is not set up yet.\n'
              u'The request is saved on this computer and will be sent '
              u'as soon as the receiver address is set.',
        'ru': u'Приёмник ещё не настроен.\n'
              u'Запрос сохранён на этом компьютере и уйдёт, как только '
              u'будет задан адрес приёмника.'},
}


def norm_lang(lang):
    lang = (lang or 'en').lower()[:2]
    return lang if lang in ('en', 'ru') else 'en'


def s(key, lang):
    d = STRINGS[key]
    return d.get(norm_lang(lang)) or d['en']


def topic_labels(lang):
    """[(code, label, hint)] in display order."""
    lang = norm_lang(lang)
    return [(c, t.get(lang, t['en'])[0], t.get(lang, t['en'])[1]) for c, t in TOPICS]


def choice_labels(choices, lang):
    lang = norm_lang(lang)
    return [(c, d.get(lang) or d['en']) for c, d in choices]
