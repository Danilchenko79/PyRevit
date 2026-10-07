# Для автора: как выпускать обновления

## Как это работает
У каждого пользователя расширение — копия ветки `main` с GitHub.
При запуске Revit pyRevit сам скачивает новое из `main`.
**Что попало в `main` — у всех при следующем запуске Revit.**

| Ветка | Кто видит |
|---|---|
| `dev` | только вы — работа, недоделанное |
| `main` | все пользователи — только проверенное |

## Выпуск версии
```
git checkout dev
git add -A
git commit -m "Что сделано"
git push

git checkout main
git pull
git merge dev
git push
git checkout dev
```

## Откат сломанного выпуска
```
git checkout main
git revert HEAD
git push
```
`push --force` не использовать.

## Перед выпуском проверить
- Новая кнопка вписана в `layout` в `bundle.yaml`.
- `__doc__` кнопки — только латиница.
- Нет путей к своему компьютеру (`C:\Users\...`, `Desktop`).

`install.bat` у себя не запускать — будет две вкладки PEER.
