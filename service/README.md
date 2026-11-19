# Сервис доступа PEER Library (Cloudflare)

Небольшой Worker перед хранилищем R2: проверяет личный ключ и роль, отдаёт файлы,
принимает публикации и предложения. Ключи, предложения и журнал действий лежат в D1.
Код — `src/worker.js`, схема — `schema.sql`. На компьютерах пользователей эта папка не
используется (pyRevit её игнорирует).

Стоимость для офиса на 10–20 человек — бесплатный тариф: R2 10 ГБ, исходящий трафик бесплатно,
Workers 100 000 запросов в день. Workers Paid — 5 $ в месяц на аккаунт, если упрёмся в лимиты.

## Развернуть с нуля (один раз, около 20 минут)
Нужны: аккаунт Cloudflare, Node.js (`node --version`). Команды выполнять в папке `service`.

1. Зарегистрироваться на dash.cloudflare.com. В разделе **R2** нажать «Enable / Purchase R2»
   (бесплатный тариф; Cloudflare может попросить привязать карту).
2. Войти из командной строки (откроется браузер):
   ```
   npx wrangler login
   ```
3. Создать хранилище и базу:
   ```
   npx wrangler r2 bucket create peer-library
   npx wrangler d1 create peer-library
   ```
   Команда `d1 create` печатает `database_id` — вставить его в `wrangler.toml` вместо
   `PASTE-DATABASE-ID-HERE`.
4. Создать таблицы и опубликовать сервис:
   ```
   npx wrangler d1 execute peer-library --remote --file=schema.sql
   npx wrangler deploy
   ```
   `deploy` печатает адрес вида `https://peer-library.<имя>.workers.dev`.
5. Первый ключ админа:
   ```
   node scripts/first_key.mjs "Дима"
   ```
   Скрипт печатает ключ (один раз — сохранить в менеджер паролей) и команду
   `npx wrangler d1 execute ... --command "INSERT ..."` — выполнить её.
6. В Revit: Shift+Click по **Library** → «Library service address» → вставить адрес;
   затем **Library** → вставить ключ. После pyRevit → Reload появятся кнопки админа
   (Publish, Inbox, Keys).
7. Загрузить семейства: Revit **2024** → Publish → «Publish a sorted folder» →
   `Desktop\PEER-Library-Source`.

## Раздать коллегам
1. Адрес сервиса положить в `lib/peer_library/settings.json`:
   ```json
   {"backend": "http", "url": "https://peer-library.<имя>.workers.dev"}
   ```
   и выпустить в `main` (автообновление PEER). Адрес не секрет — без ключа сервис ничего не отдаёт.
2. Каждому — ключ кнопкой **Keys** («Create key», роль `user`), отправить лично.
   Ушёл человек — «Revoke selected key», ключ перестаёт работать сразу.

## Резервная копия
- Файлы библиотеки: `py -3 lib/peer_library/tools/backup.py <адрес> D:\Backup\PEER`
  (ключ админа берётся из PEER этого пользователя Windows).
- Ключи, предложения, журнал: `npx wrangler d1 export peer-library --remote --output=D:\Backup\PEER\d1.sql`

## Проверка без Cloudflare
```
node --test test                     # 10 тестов сервиса (R2 и D1 подменены, node:sqlite)
node test/dev_server.mjs 8787        # локальная копия сервиса, печатает тестовые ключи
py -3 -m unittest discover -s ..\lib\peer_library\tests   # в т.ч. клиент против dev_server
```

## Безопасность
- Сервер хранит только SHA-256 ключа; сам ключ показывается один раз.
- У пользователя ключ хранится зашифрованным DPAPI (`%APPDATA%\PEER\library_key.bin`),
  в логи не пишется.
- Роль проверяет сервер на каждом запросе: `user` — читать и предлагать, `admin` — ещё публиковать,
  отклонять, выдавать и отзывать ключи.
- Журнал действий (кто что скачал, опубликовал, предложил) — `GET /audit` (админ).
- Секретов в репозитории нет: `wrangler.toml` содержит только имена и id базы.
