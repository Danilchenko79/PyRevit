# PEER Library — библиотека семейств (для разработчика)

План и ТЗ: документ «Библиотека семейств PEER — план разработки» (claude.ai artifact KMy4TRiUTRSWCxoKmN3dAu).
Инструкция для пользователей и админов: `docs/LIBRARY.md`. Сервис: `service/README.md`.

## Кнопки (PEER.tab → Library, все — smartbutton)
| Кнопка | Кто | Видна |
|---|---|---|
| Library | все | где настроена библиотека (`config.panel_visible`) |
| Propose family | все | там же |
| Check family | все | где настроена библиотека |
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
| `keystore` ключ и заявка (DPAPI); `userprefs` избранное/недавние; `search` поиск (слитно, RU/HE-синонимы, порядок) | `ui_common` цвета/чипы (без синего, статус всегда с подписью) |
| `require` (план: проект → библиотека → папка) |  `require.families` / `symbol` — семейства для других кнопок |
| `template_sync` шаблон проекта на компьютере; `passport` разница версий шаблона | кнопка New project |
| `access` статус ключа / замок; `version`; `releases`, `ext_update`, `pack` — пакет PEER | `ui_account` окно Account |
| `family_diff` что сломает замена семейства, проверки по ФОП, имена, типы (правила и тексты) | `family_sig` состав семейства данными; `load_check` проверка перед заменой (сравнение + пробная загрузка с откатом), `rename_aside`; `family_check` кнопка Check family / папка / Publish; `ui_check` окно отчёта; `family_fix` + `ui_fix` замена/переименование/удаление параметров, исправление папки в копию (план — `family_diff.fix_plan`) |

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
`/index` и `/changelog` отдаются с ETag: клиент хранит `index.json.etag` в кэше и при «304» берёт копию;
превью окно качает в фоновом потоке (сначала видимые), WPF трогает только поток окна.
`PEER_Version` — параметр типа формулой `"N"` (одно значение на все типы).

## Проверки
```
py -3 -m unittest discover -s lib/peer_library/tests     # 119 тестов, в т.ч. клиент ↔ сервис (node)
node --test service/test                                  # 25 тестов сервиса
```
Синтаксис IronPython и XAML — `ipy`-компиляция и `XamlReader` (см. историю сессии 20.11.2026).

Окна без Revit — настоящий код окон под IronPython pyRevit, Revit и `pyrevit.forms` заглушены, данные с живого
сервиса (ваш ключ, только чтение), окна вне экрана, картинки в папку:
```
powershell -STA -ExecutionPolicy Bypass -File lib\peer_library\tools\ui_preview\run.ps1 [-Script library|windows] [-Out папка]
```
`library.py` — библиотека (поиск, детали, каталог, «Need update», «This project», «What's new»), `windows.py` —
Keys, Inbox, Publish, Propose, вход, запрос, правка карточки. Загрузку в проект так не проверить — только в Revit.

Загрузка в проект — проверено в Revit 2024 через коннектор (временный проект, 20.11.2026), `loader.load_family`:
- выходной параметр `IFamilyLoadOptions` — `.Value` (`LAST_OPTIONS.used == 'value'`);
- файл, совпадающий с семейством в проекте, Revit пропускает (`OnFamilyFound` не зовётся, `SaveAs` без правки не
  помогает) → «Overwrite» при той же версии загружает копию с пустой правкой (параметр добавлен и удалён) из
  `%LOCALAPPDATA%\Temp\peer_lib_touch\<ID>.rfa`;
- типы каталога (`LoadFamilySymbol`) всегда получают значения каталога → без «Overwrite» значения типов читаются
  до загрузки и пишутся обратно в той же транзакции; целиком (`LoadFamily`) каталог грузит ВСЕ типы — окно так не делает;
- обновление v1 → v2: значения проекта сохраняются, `PEER_Version` (формула) становится 2; `project_check` /
  `on_doc_opened` находит устаревшее (уведомление в проверке заглушено).

Замена «чужого» семейства с тем же именем (проверено там же):
- постороннее семейство (своё, старая версия, исходник из «Families Dima») Revit заменяет молча: значения
  параметров, которых нет в библиотечном, пропадают, общий параметр с другим GUID — тоже;
- размер к опорной плоскости, которой нет в новом семействе = ошибка «dimension references … invalid» →
  `Guard` откатывает всю загрузку; `delete_broken=True` («Update anyway») разрешает Revit удалить такие размеры;
  размеры к центральным плоскостям шаблона переживают замену;
- особый случай: семейство-копия другого библиотечного (одна «родословная» файла) Revit не заменил вообще —
  `LoadFamily` вернул False без `OnFamilyFound`, `fd.LoadFamily` бросил «Family loading failed»;
- поэтому перед заменой `load_check.check`: сравнение составов (`EditFamily` проекта ↔ файл) + пробная загрузка в
  `TransactionGroup` с откатом (удалённое — через `DocumentChanged`, считаются размеры/марки/экземпляры и видимые
  зависимые элементы; сотни скрытых внутренних элементов семейства Revit пересоздаёт всегда — не в счёт);
  ~1,5–2 с на семейство. После отката старые Python-ссылки на элементы недействительны — брать по id;
- семейство с предупреждениями, открытое в фоне, показывает модальное окно «Warnings» и вешает скрипт —
  `revit_family.open_quiet` / `QuietOpen` (обработчик `FailuresProcessing` снимает предупреждения).

## Семейства для других кнопок (`require`)
Кнопка, которой нужны семейства компании, не ищет их по папкам сама:
```python
from peer_library import require
res = require.families(doc, [u'PR_Wall2D_Edge', u'PEER_Rebar_Shape 21'],
                       folder=BUTTON_FOLDER,              # старый запасной путь, можно не давать
                       types={u'HE_Profile': [u'HE200A']}) # семейства с каталогом — только эти типы
if not res.ok:
    forms.alert(res.message(), exitscript=True)
sym = require.symbol(doc, u'PR_Wall2D_Edge', u'Type 1')   # затем sym.Activate() в транзакции кнопки
```
- есть в проекте → берётся как есть (не перезагружается и не заменяется, даже если в библиотеке новее —
  `res.outdated`, обновляет человек в «This project»); нет → библиотека (скачать / локальная копия,
  офлайн 14 дней) → `folder/<имя>.rfa` → `res.missing` с причиной;
- семейство с каталогом без `types` не грузится (иначе придут все типы каталога);
- вместе с загружаемым семейством грузятся его «спутники» из карточки (`companions`: свая → марка), если их нет
  в проекте (`index.companions`, в окне — блок «Also load», правка — Edit info);
- каждая загрузка — своя транзакция: вызывать вне открытой `Transaction` (внутри `TransactionGroup` можно);
- `interactive=False` — без окна входа (хуки, пакетные прогоны): без ключа только папка;
- имя = ID библиотеки = имя семейства в Revit; `require.plan` — чистая логика, тесты `tests/test_require.py`.

## Один ключ на весь PEER (`access`, кнопка Account)
- `access.status()` — что есть на компьютере: ключ (DPAPI), последняя проверка (`last_ok`), сколько дней офлайн осталось.
- Замок выключен, пока в `settings.json` нет `"access_lock": true` и адреса сервиса. С замком без действующего
  ключа `startup.py` прячет все панели, кроме Account и Feedback (`access.apply_ribbon`), а первая строка каждой
  кнопки `import peer_access; peer_access.require_key()` предлагает войти и останавливает скрипт.
- Ключ сверяется с сервисом в фоне при старте Revit и в Account («Check now»); отозванный забывается, без сети
  действует последняя проверка 14 дней. С проверкой уходит версия PEER (`X-PEER-Version`) — в Keys видно, кто на какой.
- Окно во всех состояниях без Revit: `tools/ui_preview/run.ps1 -Script account` (ключ и сервис не трогаются).

## PEER раздаётся сервисом (пакет вместо GitHub)
| Что | Где |
|---|---|
| Сервис `/release/<ext\|template>/…`: манифест (каналы `stable`/`beta` — указатели на версии), файл, загрузка, publish, promote | `service/src/worker.js` |
| Что входит в пакет, сборка zip + `files.json` + `version.json` | `pack.py`, `tools/release/build_ext.py` |
| Какая версия нужна компьютеру (beta не отстаёт от stable) | `releases.py` |
| Довести установку до пакета (скачать раз, SHA-1, заменить изменённое, убрать удалённое, чужое не трогать; `version.json` пишется последним) | `ext_update.py` |
| Старт Revit: сначала пакет, иначе старый git-способ; git-клон сам становится пакетом | `lib/peer_update.py` |
| Установщик по ключу / по заявке на доступ | `installer/install.bat` + `install.ps1` |

Выпуск (ключ админа этого пользователя Windows, не печатается; в пакет идут только закоммиченные файлы):
```
powershell -ExecutionPolicy Bypass -File lib\peer_library\tools\release\release.ps1                      # что опубликовано
... release.ps1 -Do ext -Note "что изменилось"                    # пакет HEAD -> beta
... release.ps1 -Do promote -Version 2026.11.20.1 -Channel stable  # beta -> всем; так же откат на старую версию
```
Свой компьютер на beta: `"channel": "beta"` в `%APPDATA%\PEER\library.json`. Журнал обновления —
`%TEMP%\peer_revit_logs\peer_update.log`, пакеты — `%LOCALAPPDATA%\PEER\Update`.
Рабочая копия автора (не в `%APPDATA%\pyRevit\Extensions`) не обновляется никогда.

Переход с GitHub: (1) выпуск в `main` с этим кодом и адресом сервиса в `settings.json`; (2) у кого есть ключ —
установка сама переходит на пакет при старте Revit, в Keys видна версия пакета; у кого нет — работает старый
git-способ; (3) когда перешли все — `"access_lock": true` и закрыть репозиторий.

## Шаблон проекта `PR_Template Concrete`
- Файл всегда один: `%LOCALAPPDATA%\PEER\Templates\PR_Template Concrete.rte`; рядом `template.json` (версия, SHA-1,
  заметка). `template_sync.sync` при старте Revit (в фоне) доводит файл до версии канала: скачать один раз, сверить
  SHA-1, заменить; файл занят — новая версия ждёт рядом как `*.new` до следующего старта. После обновления —
  уведомление с заметкой «что изменено». Испорченный или удалённый файл восстанавливается.
- Выпуск: шаблон сохранить из Revit в `.rte`, затем
  `release.ps1 -Do template -File "…\PR_Template Concrete.rte" -Note "что изменено"` (версии 1, 2, 3…; сначала `beta`,
  потом `-Do promote -Product template -Version N -Channel stable`).
- Кнопка **New project** (панель Account): новый проект из этого файла, сразу «Сохранить как» и открыть.
- `passport.py` — «паспорт» шаблона (`{раздел: {имя: {поле: значение}}}`) и читаемая разница двух версий
  (`diff`, `text`, `summary`), сверка семейств шаблона с библиотекой (`outdated_families`). Сбор паспорта из
  `.rte` и кнопка «Update from template» — в Revit, ещё не сделаны.
- Новый шаблон меняет только новые проекты; начатые проекты он не трогает.

## Инструменты (`tools/`)
- `sort_source.py <сырые> <папка>` — раскладка по группам, журнал `_sort_log.csv`.
- `backfill_plan.py` + `apply_plan.ps1` — имена/теги/типы для уже опубликованных карточек (без новых версий).
- `backup.ps1 -Folder D:\Backup\PEER` — резервная копия библиотеки (.NET, проверка SHA-1).
