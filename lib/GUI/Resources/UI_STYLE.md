# PEER — правила оформления интерфейса (UI style)

Единый стиль окон для всех инструментов PEER. **Перед любой работой над UI
(новое окно, правка формы) сверяйся с этим файлом.** Эталон — окно
`PEER.tab/Sheets.panel/Worksets.pushbutton` (`WorksetsForm.xaml` + `script.py`).

---

## 1. Канонический паттерн окна

Новые окна делаем на **`forms.WPFWindow` + внешний `.xaml`**, загружаемый через
`script.get_bundle_file(...)`. Разметку НЕ строим в коде (кроме динамических
элементов — пунктов списка, чекбоксов по данным).

```python
from pyrevit import forms, script

class MyToolWindow(forms.WPFWindow):
    def __init__(self, xaml_path, ...):
        forms.WPFWindow.__init__(self, xaml_path)
        # заполнить динамику: списки, чекбоксы, значения по умолчанию

    def on_ok(self, sender, args):
        # ВАЛИДАЦИЯ прямо здесь; при ошибке forms.alert(...) и return,
        # окно НЕ закрываем
        self.DialogResult = True
        self.Close()

    def on_cancel(self, sender, args):
        self.DialogResult = False
        self.Close()

win = MyToolWindow(script.get_bundle_file("MyToolForm.xaml"), ...)
win.ShowDialog()
if not win.DialogResult:
    return  # или forms.alert("Cancelled", exitscript=True)
```

- Файл XAML лежит **рядом со `script.py`** в папке кнопки, имя `<Tool>Form.xaml`.
- Обработчики кнопок в XAML — `Click="on_ok"` / `Click="on_cancel"`, имена
  методов совпадают.
- Одно окно на инструмент: **весь ввод собираем за один показ**, а не серией
  `ask_for_string`.

## 2. Обязательная разметка (light-стиль Worksets)

- `Window`: `FontFamily="Segoe UI" FontSize="13"`,
  `WindowStartupLocation="CenterScreen"`, `ShowInTaskbar="False"`,
  `ResizeMode="CanResizeWithGrip"`, заданы `MinWidth`/`MinHeight`.
- Внешний `Grid Margin="14"` с двумя строками: `Height="*"` (контент, в
  `ScrollViewer`) и `Height="Auto"` (закреплённая панель кнопок — **никогда не
  обрезается**).
- **Заголовок** сверху: `TextBlock FontWeight="Bold" FontSize="15"`.
- **Блок «How to use»** — краткая инструкция в рамке:
  `Border Background="#F2F6FA" BorderBrush="#C6D4E1" BorderThickness="1"
  CornerRadius="3" Padding="8"`, текст `Foreground="#33475B"`, `TextWrapping="Wrap"`.
- Поля ввода — подпись `TextBlock` над контролом, `Margin="0,12,0,4"` между
  группами.
- **Нижняя панель**: `StackPanel Orientation="Horizontal"
  HorizontalAlignment="Right"`, две кнопки `Width="90" Height="28"`:
  `OK` (`IsDefault="True"`) и `Cancel` (`IsCancel="True"`).
- Каждому контролу, который читается из кода, задаём `x:Name`.

## 3. Поведение

- `OK` (`IsDefault`) — Enter; `Cancel`/`IsCancel` — Esc и крестик закрывают окно
  без действия.
- Вся валидация — в `on_ok`; при непройденной проверке показываем
  `forms.alert(..., title=__title__)` и **не** закрываем окно.
- Итоги/отчёты выводим в окно pyRevit output (`script.get_output()`),
  ссылки на элементы — через `output.linkify(element_id)`.

## 4. Легаси-стиль (не для нового кода)

`my_WPF` (`lib/GUI/WPF_Base.py`) + тёмная тема `WPF_styles.xaml` (EF-Tools,
magenta/blue) — **старый** стиль, оставлен для существующих окон `lib/GUI/*`
(FindReplace, SelectFromDict и т.п.). Для **новых** инструментов его не
используем — только если правим уже существующее тёмное окно и нужно сохранить
его вид.

## 5. Чек-лист перед сдачей UI

- [ ] Окно — `forms.WPFWindow` + внешний `.xaml` через `get_bundle_file`?
- [ ] Есть заголовок и блок «How to use»?
- [ ] Кнопки закреплены снизу (`OK` IsDefault / `Cancel` IsCancel), 90×28?
- [ ] Segoe UI 13, CenterScreen, есть Min-размеры?
- [ ] Валидация в `on_ok`, при ошибке окно не закрывается?
- [ ] Весь ввод собран одним окном, без цепочки диалогов?
