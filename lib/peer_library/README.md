# PEER Library — библиотека семейств

План и ТЗ: документ «Библиотека семейств PEER — план разработки» (claude.ai artifact KMy4TRiUTRSWCxoKmN3dAu).

## Кнопки (PEER.tab → Library)
| Кнопка | Кто | Что |
|---|---|---|
| Library | все | группы, поиск, превью, статус относительно проекта, загрузка / обновление / размещение, каталоги типов, «Что нового», «Мои предложения». Shift+Click — папка библиотеки, кэш, лог |
| Propose family | все | отправить семейство (файл / выделенный элемент / открытое в редакторе) во «Входящие» |
| Publish | админ | единственный путь в библиотеку: проверки, `PEER_Version`, превью, compact-сохранение, индекс; «Publish a sorted folder» — массовый импорт `<group>/<ID>.rfa` |
| Inbox | админ | предложения: открыть в редакторе, опубликовать, отклонить с комментарием |

Publish и Inbox — smartbutton: у роли `user` скрыты (`__selfinit__`).

## Хранилище
`config.py`: `%APPDATA%\PEER\library.json` поверх `lib/peer_library/settings.json` (офисный общий путь, если положить).
```json
{"backend": "local", "root": "\\\\server\\share\\PEER", "role": "admin"}
```
`root` — папка, в которой лежат `PEER-Library` и `PEER-Inbox`. Кэш — `%LOCALAPPDATA%\PEER\Library`, лог — `%APPDATA%\PEER\library.log`.
В локальном варианте роль берётся из настроек (для пробы в офисе); настоящую защиту даёт сервис (задача 4, `backend_http.py` — не сделан).

## Формат
Формат библиотеки — **Revit 2024** (`checks_file.LIBRARY_REVIT`). Публиковать только из Revit 2024.
ID = имя файла = имя семейства в Revit, не меняется. Карточка `<ID>.json` (поля — `index.CARD_DEFAULTS`), `index.json` пересобирается из карточек при каждой публикации, `changelog.json` — лента.

## Тесты (без Revit)
```
py -3 -m unittest discover -s lib/peer_library/tests
```
Модули без Revit API: groups, jsonio, config, rfa_info, checks_file, index, cache, catalog, backend_*.

## Сортировка исходной папки
`tools/sort_source.py <сырые семейства> <папка>` — копирует в `<group>/<ID>.rfa` (+ каталог .txt), пропуская бэкапы, OLD, дубли, файлы новее Revit 2024; журнал `_sort_log.csv`. Результат публикуется кнопкой Publish → «Publish a sorted folder».
