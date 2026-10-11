# Разработка

Документ для тех, кто правит код, собирает exe и выпускает релизы.
Пользовательская инструкция — в [README](../README.md).

Все команды — для PowerShell из корня репозитория.

## Содержание

- [Как устроено](#как-устроено)
- [Подготовка окружения](#подготовка-окружения)
- [Запуск из исходников](#запуск-из-исходников)
- [Тесты и CI](#тесты-и-ci)
- [Сборка exe локально](#сборка-exe-локально)
- [Выпуск релиза](#выпуск-релиза)
- [Как работает обновление](#как-работает-обновление)
- [Частые задачи](#частые-задачи)
- [Структура проекта](#структура-проекта)

## Как устроено

```
микрофон → Vosk (отдельный процесс) → поиск корней из words.txt → счётчик (counter.json)
        → FastAPI + WebSocket → оверлей OBS (/overlay/) и страница управления (/control/)
```

- **Сервер** — FastAPI + uvicorn на `127.0.0.1:8765` (если занят — 8766…8774).
  Состояние рассылается клиентам по WebSocket `/ws`, команды идут через `/api/*`.
- **Окно приложения** — та же страница `/control/` в окне WebView2 (pywebview),
  плюс значок в трее (pystray). Сервер работает в фоновом потоке (`app/desktop.py`).
- **Распознавание** — Vosk в отдельном процессе (`app/stt/vosk_worker.py`), чтобы загрузку
  модели можно было прервать мгновенно, просто завершив процесс.
- **Данные пользователя** (`counter.json`, `settings.json`, `words.txt`, `models/`, `sounds/`,
  `webview/`, `swearcounter.log`) лежат рядом с exe, а из исходников — в корне репозитория
  (`app/paths.py`). Встроенные ресурсы (`overlay/`, `control/`, `assets/`) — внутри сборки.

## Подготовка окружения

Нужны Windows 10/11, [Python 3.15](https://www.python.org/downloads/) и git.

1. Клонировать репозиторий:

   ```powershell
   git clone https://github.com/vvallikk/SwearCounter.git
   cd SwearCounter
   ```

2. Создать виртуальное окружение `.venv` (на него рассчитаны все команды ниже):

   ```powershell
   py -3.15 -m venv .venv
   ```

3. Поставить зависимости: для запуска, тестов и сборки exe:

   ```powershell
   .venv\Scripts\python.exe -m pip install -r requirements-dev.txt -r requirements-build.txt
   ```

   | Файл                     | Что внутри                                    |
   |--------------------------|-----------------------------------------------|
   | `requirements.txt`       | зависимости приложения                        |
   | `requirements-dev.txt`   | + pytest и httpx2 (для `TestClient`)          |
   | `requirements-build.txt` | + PyInstaller                                 |

4. Модель распознавания скачивается из окна приложения кликом по ней (в папку `models/`,
   она в `.gitignore`). Вручную: распаковать архив так, чтобы получилось
   `models/vosk-model-small-ru-0.22/am, conf, graph, ...`. Ссылки — в `app/stt/catalog.py`.

## Запуск из исходников

```powershell
.venv\Scripts\python.exe -m app.main
```

Откроется окно и значок в трее, лог — в `swearcounter.log`. Выход — «Выход» в меню трея.

| Ключ             | Что делает                                                 |
|------------------|------------------------------------------------------------|
| `--console`      | без окна и трея: адреса и лог в консоли, выход по `Ctrl+C` |
| `--list-devices` | показать звуковые устройства и выйти                       |
| `--device N`     | слушать устройство с номером `N` или по части названия     |

Для разработки фронтенда удобнее `--console` и обычный браузер:

```powershell
.venv\Scripts\python.exe -m app.main --console
```

- Страница управления: http://localhost:8765/control/
- Оверлей: http://localhost:8765/overlay/

Статика (`overlay/`, `control/`) отдаётся с диска — после правки достаточно обновить страницу.
Python-код требует перезапуска. Второй экземпляр в оконном режиме не запустится
(именованный mutex) — сначала закройте первый через «Выход».

## Тесты и CI

```powershell
.venv\Scripts\python.exe -m pytest -q
```

- Тесты в `tests/`, идут пару секунд, не требуют микрофона, моделей и интернета:
  `sounddevice`, `vosk` и `urlopen` подменены, файлы создаются во временной папке.
  Работающее приложение и его порты тесты не трогают.
- Новый код ядра (`app/`) покрывается тестами в том же PR.
- GitHub Actions (`.github/workflows/tests.yml`, windows-latest) гоняет тесты на каждый
  PR и push в `main`.

## Сборка exe локально

1. Закройте запущенный `dist\SwearCounter\SwearCounter.exe` («Выход» в трее) — иначе
   PyInstaller не сможет перезаписать файлы.
2. Соберите:

   ```powershell
   .venv\Scripts\python.exe scripts/build.py
   ```

3. Результат:
   - `dist\SwearCounter\` — готовая папка (`SwearCounter.exe`, `_internal\`, `words.txt`,
     `README.md`, `models\README.txt`);
   - `dist\SwearCounter-v<версия>-windows.zip` — тот же архив, что публикуется в релизе.

Настройки сборки — в `SwearCounter.spec` (без консоли, иконка, ресурс версии из
`app/__init__.py`). Иконка перерисовывается скриптом:

```powershell
.venv\Scripts\python.exe scripts/make_icon.py
```

## Выпуск релиза

Релиз собирает и публикует GitHub Actions (`.github/workflows/release.yml`) по тегу `v*`.

1. Обновите `main`:

   ```powershell
   git checkout main
   git pull
   ```

2. Создайте ветку и поднимите версию в `app/__init__.py` (семантическое версионирование:
   исправления — `0.3.1`, новые возможности — `0.4.0`):

   ```powershell
   git checkout -b release/v0.3.0
   ```

   ```python
   __version__ = "0.3.0"
   ```

   и напишите заметки к релизу в `docs/releases/v0.3.0.md` (без них сборка упадёт).
   Формат — как в [v0.2.0](releases/v0.2.0.md): раздел «Что нового» на русском, затем
   «What's new» с тем же списком на английском. Только перечень изменений, понятный
   пользователю, без имён разработчиков и номеров PR. Этот текст увидят пользователи
   на странице релиза и в блоке «Что нового» в программе.

3. Проверьте тесты и закоммитьте:

   ```powershell
   .venv\Scripts\python.exe -m pytest -q
   git add app/__init__.py docs/releases/v0.3.0.md
   git commit -m "Release v0.3.0"
   git push -u origin release/v0.3.0
   ```

4. Откройте PR и влейте его в `main` после зелёных тестов:

   ```powershell
   gh pr create --fill
   gh pr merge --merge
   ```

5. Поставьте тег на коммит в `main` и отправьте его:

   ```powershell
   git checkout main
   git pull
   git tag v0.3.0
   git push origin v0.3.0
   ```

6. Следите за сборкой (~5–10 минут):

   ```powershell
   gh run watch
   ```

   Workflow проверит, что тег равен `v` + `__version__` и что есть заметки
   `docs/releases/v0.3.0.md` (иначе упадёт), прогонит тесты, соберёт exe и создаст релиз
   `v0.3.0` с архивом `SwearCounter-v0.3.0-windows.zip` и текстом из заметок.

7. Поправить описание уже опубликованного релиза:

   ```powershell
   gh release edit v0.3.0 --notes-file docs/releases/v0.3.0.md
   ```

**Если сборка упала:** исправьте причину в `main`, затем удалите тег и поставьте заново:

```powershell
git push --delete origin v0.3.0
git tag -d v0.3.0
git tag v0.3.0
git push origin v0.3.0
```

Если релиз уже успел создаться — сначала `gh release delete v0.3.0 --yes`.

## Как работает обновление

Код — `app/updater.py`, API — `/api/update*` в `app/server.py`, UI — раздел «Обновления»
на странице управления, пункт «Проверить обновления» в трее.

1. **Проверка.** `GET https://api.github.com/repos/vvallikk/SwearCounter/releases/latest`
   без токена (лимит GitHub — 60 запросов в час с IP). Черновики, пре-релизы и теги не вида
   `vX.Y.Z` игнорируются. В релизе ищется ассет `SwearCounter-v*-windows.zip`.
   При запуске проверка идёт не чаще раза в 6 часов; время и результат хранятся
   в `settings.json` (`update_checked_at`, `update_last`), выключается `update_auto`.
2. **Скачивание** (только собранный exe): архив качается в `update\update.zip.part`
   и распаковывается в `update\new\`. Прогресс рассылается по WebSocket (`type: "update"`).
3. **Установка.** Пишется `update\apply.cmd` и запускается отдельным процессом, а приложение
   выходит. Скрипт ждёт завершения процесса, копирует `_internal\` (robocopy `/MIR`)
   и `SwearCounter.exe`, запускает новую версию и удаляет папку `update\`.
   Данные пользователя не трогаются.

Версии, вышедшие до появления автообновления, нужно один раз обновить вручную (скачать zip и заменить `SwearCounter.exe` и `_internal`).

### Проверить обновление вручную

1. Временно поставьте `__version__ = "0.0.1"` в `app/__init__.py` и соберите exe
   (`scripts/build.py`). Не коммитьте это изменение.
2. Скопируйте `dist\SwearCounter` в отдельную папку, положите туда тестовые
   `settings.json` / `counter.json`, запустите exe.
3. В разделе «Обновления» должна появиться последняя версия → «Скачать и установить» →
   «Перезапустить и обновить». Программа должна перезапуститься с новой версией в заголовке,
   а счёт и настройки — сохраниться.
4. Верните версию: `git checkout app/__init__.py`.

## Частые задачи

**Добавить модель распознавания** — дописать её в `CATALOG` в `app/stt/catalog.py`
(название, описание, характеристики, ссылка на zip).

**Добавить оформление оверлея** — новый пресет в `overlay/presets.js`:
он сам появится в списке на странице управления.

**Поменять список слов по умолчанию** — `words.txt` в корне (попадает в сборку и
кладётся рядом с exe; у пользователей их правленая копия не перезаписывается обновлением).

**Переснять скриншоты для README** — `docs/screenshots/`. Запустите приложение с `--console`
и снимите страницу и оверлей headless-браузером (каждый снимок — со своим `--user-data-dir`,
файл появляется через несколько секунд после выхода команды), например:

```powershell
& "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe" --headless=new --user-data-dir="$env:TEMP\edge-shot" --hide-scrollbars --virtual-time-budget=5000 --window-size=960,1500 --screenshot="$PWD\docs\screenshots\control.png" http://localhost:8765/control/
```

## Структура проекта

```
app/main.py           точка входа, ключи запуска, логирование
app/desktop.py        окно (pywebview), трей (pystray), сервер в потоке, один экземпляр
app/server.py         FastAPI: /ws, /api/state, /api/increment, /api/reset, /api/speech,
                      /api/devices, /api/sound, /api/overlay, /api/update, статика
app/updater.py        проверка, скачивание и установка обновлений из GitHub Releases
app/settings.py       настройки (settings.json)
app/sound.py          громкость и библиотека звуков оповещения (sounds/)
app/counter.py        счётчик и сохранение в counter.json
app/profanity.py      поиск корней из words.txt, счёт по ходу фразы (SwearTracker)
app/paths.py          пути к файлам (из исходников и из exe)
app/stt/              распознавание: VoskRecognizer, процесс vosk_worker, каталог моделей,
                      скачивание моделей (downloader), список микрофонов (audio_devices)
overlay/              оверлей для OBS; presets.js — оформления, sound.js — проигрыватель звука
control/              страница управления (index.html, style.css, control.js)
assets/               иконка (scripts/make_icon.py)
scripts/build.py      сборка exe и zip
SwearCounter.spec     настройки PyInstaller
tests/                тесты pytest
docs/                 документация, скриншоты, заметки к релизам (releases/)
.github/workflows/    tests.yml — тесты, release.yml — релиз по тегу
```
