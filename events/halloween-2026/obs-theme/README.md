# Хеллоуин-тема для OBS (временно, Хеллоуин 2026)

> **EVENT: halloween-2026 — временная тема.** Всё лежит в этой папке и больше нигде.
> После 1 ноября 2026 папку `events/halloween-2026/obs-theme` можно просто удалить:
> программа SwearCounter её не использует. Если забыть убрать источники из OBS,
> страницы сами станут пустыми и прозрачными с 2 ноября (`EVENT_ENDS` в `lib/event.js`).

Набор браузерных источников OBS на HTML/CSS/JS. Картинок и чужих файлов нет: паутина, тыквы,
мыши и пауки рисуются кодом. Шрифты Rubik и Rubik Wet Paint (кириллица и латиница) лежат
в `fonts/`, лицензия SIL Open Font License, см. `fonts/OFL.txt`.

Откройте `index.html` в браузере: там превью всех страниц и кнопки для проверки.

| Страница | Размер источника | Что это |
|---|---|---|
| `spider.html` | 1920×1080, поверх всей сцены | Пауки: пробежка, стая, спуск на паутине, огромный паук-скример |
| `alerts.html` | 1920×1080 | Алерты: открытка спускается на паутине вместе с пауком |
| `screen.html` | 1920×1080 | Заставки «Скоро начнём», «Сейчас вернусь», «Спасибо за стрим» с отсчётом |
| `frame.html` | камера + 68 px (708×428 для 640×360) | Рамка камеры: паутина, капли, паучок на нити, подпись |

## Как добавить в OBS

1. **Источники → + → Браузер.**
2. Включите **Локальный файл** и выберите нужный `.html`. Параметры (`?mode=...`) с локальным
   файлом не передать, поэтому для них снимите галочку и вставьте в **URL** адрес вида
   `file:///C:/путь/к/obs-theme/screen.html?mode=brb`.
3. Ширина и высота — из таблицы. Пользовательский CSS очистите.
4. Для `spider.html` и `alerts.html` включите **Управлять звуком через OBS**, если задаёте `?sound=`.

## Параметры

**Все страницы:** `?lang=en` — английский текст; `?force=1` — показать тему после окончания евента;
`?sb=off`, `?obs=off` — не подключаться к Streamer.bot или OBS WebSocket;
`?sb=ws://host:port/` и `?obs=ws://host:port` — другие адреса; `?obspass=...` — пароль OBS WebSocket.

**spider.html:** `?mode=run|swarm|drop|big` — что делать, когда источник показали в сцене;
`?ambient=90` — сам выпускать паучка примерно раз в 90 секунд; `?autoplay=1` — паук сразу после загрузки.
В режиме «Взаимодействовать» клавиши 1–4 запускают режимы.

**alerts.html:** `?duration=7` — секунд на алерт; `?sound=boo.mp3&volume=0.6` — звук.

**screen.html:** `?mode=starting|brb|ending`; `?title=...&sub=...` — свой текст;
`?minutes=10` или `?until=19:00` — обратный отсчёт.

**frame.html:** `?label=Ник`; `?color=pumpkin|slime|violet|blood`.

## Как запускать пауков и алерты

Страницы слушают сразу три источника, настраивать их в странице не нужно.

### 1. Показать источник в OBS

Самый простой способ. Streamer.bot (или горячая клавиша OBS) включает видимость источника
`spider.html` — паук пробегает в режиме из `?mode=`. Через несколько секунд источник можно скрыть.

### 2. Streamer.bot WebSocket Server

В Streamer.bot: **Servers/Clients → WebSocket Server**, включите сервер (по умолчанию
`127.0.0.1:8080`) и автозапуск. Без пароля.

- **Алерты** Twitch (фоллоу, подписки, подарки, битсы, рейды) и YouTube (подписчики, спонсоры,
  суперчаты) страница `alerts.html` получает сама.
- **Свои команды:** sub-action **Core → C# → Execute C# Code** с кодом из `streamerbot/spider.cs`,
  или одной строкой:
  ```csharp
  CPH.WebsocketBroadcastJson("{\"overlay\":\"halloween\",\"action\":\"spider\",\"mode\":\"big\"}");
  ```

### 3. OBS WebSocket

Streamer.bot: sub-action **OBS → Raw**, запрос `BroadcastCustomEvent`, данные:

```json
{ "eventData": { "overlay": "halloween", "action": "spider", "mode": "swarm", "count": 15 } }
```

Так же работает из Touch Portal, Stream Deck и всего, что умеет OBS WebSocket 5.
Если в OBS задан пароль WebSocket, добавьте его в адрес: `spider.html?obspass=...`.

### Паук на каждый мат (SwearCounter)

Подключите Streamer.bot к счётчику, как в [docs/STREAMERBOT.md](../../../docs/STREAMERBOT.md)
(WebSocket-клиент `ws://127.0.0.1:8765/ws/events`). На триггер **Custom Client Message**
повесьте действие с `streamerbot/spider.cs` и условием «`%message%` содержит `increment`».

## Команды

| Команда | Что делает |
|---|---|
| `{"action":"spider","mode":"run"}` | один паук перебегает экран перебежками |
| `{"action":"spider","mode":"swarm","count":12}` | стая пауков с одного края |
| `{"action":"spider","mode":"drop","x":0.5}` | паук спускается на паутине (x — доля ширины) |
| `{"action":"spider","mode":"big"}` | огромный паук через весь экран |
| `{"action":"alert","kind":"donation","user":"Вася","amount":"500 ₽","message":"Бу!"}` | алерт; kind: follow, sub, gift, cheer, raid, donation |
| `{"action":"screen","mode":"brb"}` | сменить текст заставки |
| `{"action":"countdown","minutes":5}` | новый отсчёт на заставке |
| `{"action":"frame","label":"Ник"}` | сменить подпись рамки |

Поле `"overlay":"halloween"` необязательно; команды с другим `overlay` страницы пропускают.

## Удаление после евента

1. Уберите источники темы из сцен OBS.
2. Удалите папку `events/halloween-2026/obs-theme` (и `events/halloween-2026`, если она пустая).
3. В Streamer.bot удалите действия с `spider.cs` и `BroadcastCustomEvent`.
