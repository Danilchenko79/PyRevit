# PEER Library — библиотека семейств (для разработчика)

План и ТЗ: документ «Библиотека семейств PEER — план разработки» (claude.ai artifact KMy4TRiUTRSWCxoKmN3dAu).
Инструкция для пользователей и админов: `docs/LIBRARY.md`. Сервис: `service/README.md`.

## Кнопки (PEER.tab → Library, все — smartbutton)
| Кнопка | Кто | Видна |
|---|---|---|
| Library | все | где настроена библиотека (`config.panel_visible`) |
| Propose family | все | там же |
| Publish, Inbox | админ | роль `admin` |
| Keys | админ | роль `admin` и сервис (`backend: http`) |

Без настройки `startup.py` прячет и саму панель — ветку можно вливать до раздачи адреса.

## Модули
| Без Revit (тесты на CPython) | В Revit (IronPython) |
|---|---|
| `config` настройки, `jsonio`, `log`, `strings` (все тексты UI) | `revit_family` открыть копию, проверки, `PEER_Version` формулой, превью, compact |
| `index` карточка, индекс, changelog | `publish` одно семейство / папка (имена+теги из `importmeta`) |
| `checks_file` маска, размер, версия Revit (2024) | `loader` статусы, LoadFamily / LoadFamilySymbol, размещение, список семейств проекта |
| `rfa_info` версия без Revit, sha1 | `session` вход: ключ / заявка на доступ |
| `cache` локальная копия `<group>/<ID>.rfa`, офлайн 14 дней | `ui_library` окно (группы, избранное, недавние, популярное, коллекции, фильтры, сортировка, каталоги, «Этот проект», админ-действия) |
| `backend_base` интерфейс; `backend_local` папка; `backend_http` сервис | `ui_publish` (+ Excel), `ui_inbox`, `ui_propose`, `ui_dialogs` |
| `catalog` каталог типов; `cards_csv` карточки ↔ Excel; `importmeta` имена/теги | `notify` уведомление при старте; `project_check` + `hooks/doc-opened.py` |
| `keystore` ключ и заявка (DPAPI); `userprefs` избранное/недавние | `ui_common` цвета/чипы (без синего, статус всегда с подписью) |

## Настройки
`%APPDATA%\PEER\library.json` поверх `lib/peer_library/settings.json` (для офиса положить сюда адрес сервиса):
```json
{"backend": "http", "url": "https://peer-library.<имя>.workers.dev"}
```
Ключ — `%APPDATA%\PEER\library_key.bin` (DPAPI), избранное — `library_user.json`, кэш — `%LOCALAPPDATA%\PEER\Library`,
лог — `%APPDATA%\PEER\library.log`. Вариант «папка» (`backend: local`, `root`) — для пробы без сервиса, роль из настроек.

## Формат
Revit **2024**, публиковать только из 2024. ID = имя файла = имя семейства в Revit, не меняется.
Карточка — `index.CARD_DEFAULTS` (+ `types` для поиска по типам, `files` — адреса версий в сервисе).
`PEER_Version` — параметр типа формулой `"N"` (одно значение на все типы).

## Проверки
```
py -3 -m unittest discover -s lib/peer_library/tests     # 29 тестов, в т.ч. клиент ↔ сервис (node)
node --test service/test                                  # 15 тестов сервиса
```
Синтаксис IronPython и XAML — `ipy`-компиляция и `XamlReader` (см. историю сессии 20.11.2026).

## Инструменты (`tools/`)
- `sort_source.py <сырые> <папка>` — раскладка по группам, журнал `_sort_log.csv`.
- `backfill_plan.py` + `apply_plan.ps1` — имена/теги/типы для уже опубликованных карточек (без новых версий).
- `backup.ps1 -Folder D:\Backup\PEER` — резервная копия библиотеки (.NET, проверка SHA-1).
