// Английский интерфейс страницы управления.
//
// Страница и сервер пишут по-русски, а при английском языке этот скрипт подменяет
// русский текст на странице по словарю: текст элементов, подсказки (title),
// placeholder и aria-label, в том числе всё, что control.js и сервер покажут позже
// (MutationObserver). Текст без перевода в словаре остаётся русским.
//
// Язык хранится в settings.json (его же видят трей и уведомления, app/i18n.py),
// а в localStorage — копия, чтобы страница сразу открывалась на нужном языке.
// Переключение языка перезагружает страницу: русский — это исходный текст.
(() => {
  "use strict";

  const STORAGE_KEY = "language";
  const CYRILLIC = /[а-яё]/i;

  // Точные строки: русский → английский. Пробелы по краям и переносы внутри
  // текста не важны — сравнивается текст со сжатыми пробелами.
  const EXACT = {
    // Заголовок и вкладки
    "Счётчик матов — управление": "Swear Counter — control",
    "Счётчик матов": "Swear Counter",
    "Поддержать автора": "Support the author",
    "Нет связи с сервером": "No connection to the server",
    "Подключено": "Connected",
    "Разделы": "Sections",
    "Счётчик": "Counter",
    "Оформление": "Look",
    "Настройки": "Settings",
    "Светлая тема": "Light theme",
    "Тёмная тема": "Dark theme",

    // Вкладка «Счётчик»
    "Сколько удалось продержаться без нужных слов. Рекорд — с запуска программы или сброса счёта; на паузе таймер стоит.":
      "How long you've held out without the counted words. The record is since the program started or the count was reset; the timer stops while paused.",
    "Без мата:": "Clean for:",
    "· рекорд": "· record",
    "До цели:": "To the goal:",
    "+1 (тест)": "+1 (test)",
    "⏸ Пауза": "⏸ Pause",
    "▶ Продолжить": "▶ Resume",
    "Снова считать сказанное": "Count what's said again",
    "Не считать сказанное: на перерыв, катсцену или чужой голос": "Don't count what's said: for a break, a cutscene or someone else's voice",
    "Сбросить": "Reset",
    "Точно сбросить?": "Really reset?",
    "Точно?": "Sure?",
    "Пауза: сказанное не считается. Кнопки работают.": "Paused: what's said isn't counted. The buttons still work.",
    "Оверлей для OBS (источник «Браузер») или любого браузера:": "Overlay for OBS (a “Browser” source) or any browser:",
    "Нажмите, чтобы скопировать": "Click to copy",
    "Где распознавать": "Where to recognize",
    "Работают на вашем компьютере без интернета, звук никуда не отправляется. Модель нужно скачать один раз.":
      "Run on your computer without internet; audio never leaves it. The model is downloaded once.",
    "Звук фраз отправляется сервису по интернету, нужен ваш API-ключ. Скачивать модель не нужно, распознаёт быстро и точно.":
      "Phrase audio is sent to the service over the internet; your API key is required. No model download, fast and accurate.",
    "ключ сохранён": "key saved",
    "нужен ключ": "key needed",
    "Источники для OBS": "Sources for OBS",
    "Вставьте ссылку в источник «Браузер»": "Paste the link into a “Browser” source",
    "Таймер «без мата»": "“Clean for” timer",
    "Отсчёт до цели": "Countdown to the goal",
    "Копировать": "Copy",
    "Скопировать": "Copy",
    "Скопировано ✓": "Copied ✓",
    "Скопировано": "Copied",
    "Не удалось скопировать": "Couldn't copy",
    "Не скопировалось": "Couldn't copy",
    "Открыть оверлей в браузере по умолчанию": "Open the overlay in the default browser",
    "Открыть в браузере": "Open in browser",
    "Таймер «без мата» — отдельный источник:": "The “clean for” timer is a separate source:",
    "Отсчёт до цели — отдельный источник:": "The countdown to the goal is a separate source:",
    "Дополнительные счётчики": "Extra counters",
    "Свой список слов, счёт и оверлей — например, слова-паразиты отдельно от матов. Цели, таймер, статистика и OBS — только у основного счётчика.":
      "Their own word list, count and overlay — for example, filler words apart from swear words. Goals, the timer, statistics and OBS are only for the main counter.",
    "Название": "Name",
    "Название нового счётчика": "Name of the new counter",
    "Список слов нового счётчика": "Word list of the new counter",
    "Добавить": "Add",
    "без подписи": "no label",
    "Удалить счётчик": "Delete counter",
    "Точно удалить?": "Really delete?",
    "Список слов": "Word list",
    "Подпись": "Label",
    "Оверлей этого счётчика:": "This counter's overlay:",
    "Микрофон": "Microphone",
    "Обновить список микрофонов": "Refresh the microphone list",
    "Громкость микрофона": "Microphone volume",
    "🎧 Слушать себя": "🎧 Hear yourself",
    "⏹ Остановить прослушивание": "⏹ Stop listening",
    "Звук микрофона пойдёт в наушники. Без наушников будет эхо.": "The microphone sound goes to your headphones. Without headphones there will be an echo.",
    "Переключение микрофона…": "Switching the microphone…",
    "Микрофон откроется, когда модель загрузится": "The microphone will open once the model has loaded",
    "Микрофон откроется, когда модель скачается": "The microphone will open once the model has downloaded",
    "По умолчанию (системный)": "Default (system)",
    "Статистика": "Statistics",
    "Слов за последние сессии": "Words in recent sessions",
    "Сохранить в CSV": "Save as CSV",
    "Очистить": "Clear",
    "Точно очистить?": "Really clear?",
    "Пока пусто: сессия начинается с первого слова после запуска или сброса.": "Nothing yet: a session starts with the first word after launch or a reset.",

    // Вкладка «Оформление»
    "Подпись к счётчику": "Counter label",
    "Например: Маты за стрим: или Слова-паразиты:": "For example: Swears this stream: or Filler words:",
    "Подпись к таймеру «без мата»": "Label for the swear-free timer",
    "Например: Без мата:": "For example: Swear-free for:",
    "Подпись таймера стоит с той же стороны, что и подпись счётчика. Пустое поле — только время.":
      "The timer label sits on the same side as the counter label. An empty field shows just the time.",
    "Размер числа": "Number size",
    "Размер подписи": "Label size",
    "100% — размер по умолчанию. Больше окна источника в OBS счётчик не станет: чтобы он был крупнее, растяните сам источник.":
      "100% is the default size. The counter never grows beyond the OBS source window: to make it bigger, stretch the source itself.",
    "Где подпись": "Label position",
    "Слева": "Left",
    "Справа": "Right",
    "Сверху": "Top",
    "Снизу": "Bottom",
    "Подпись и число — один источник в OBS: двигаются и масштабируются вместе. Пустое поле — только число. Как это выглядит — в превью оформления ниже.":
      "The label and the number are one source in OBS: they move and scale together. An empty field shows just the number. See how it looks in the preview below.",
    "Звук оповещения": "Alert sound",
    "▶ Проверить": "▶ Test",
    "Загрузить звук…": "Upload a sound…",
    "Стандартный звон": "Standard ding",
    "Прослушать": "Play",
    "Удалить": "Delete",
    "Удалить?": "Delete?",
    "Загрузка…": "Uploading…",
    "Поддерживаются файлы MP3, WAV и OGG": "MP3, WAV and OGG files are supported",
    "Не получилось прочитать файл как звук": "Couldn't read the file as a sound",
    "Не удалось загрузить файл": "Couldn't upload the file",
    "Файл пустой": "The file is empty",
    "Оформление счётчика": "Counter look",
    "Превью оформления": "Look preview",
    "Установить оформление…": "Install a look…",
    "Установить по ссылке…": "Install from a link…",
    "📦 Сохранить архивом": "📦 Save as archive",
    "🗑 Удалить оформление": "🗑 Delete look",
    "Вставьте ссылку на архив": "Paste a link to the archive",
    "Установить": "Install",
    "Личное оформление: свой шрифт, картинки, анимация и звук. Его можно сделать самому":
      "A personal look: your own font, images, animation and sound. You can make one yourself",
    "по инструкции": "following the guide",
    "или": "or",
    "заказать у автора": "order one from the author",
    ". Готовое оформление ставится из zip-архива или по ссылке на Яндекс Диск, Google Диск или Dropbox. Устанавливайте только оформления из надёжных источников: анимация в них работает как небольшая программа внутри оверлея.":
      ". A finished look is installed from a zip archive or a link to Yandex Disk, Google Drive or Dropbox. Only install looks from trusted sources: their animation runs as a small program inside the overlay.",
    "Личные оформления": "Personal looks",
    "Оформление ставится из zip-архива": "A look is installed from a zip archive",
    "Установка…": "Installing…",
    "Не удалось установить оформление": "Couldn't install the look",
    "Скачивание и установка…": "Downloading and installing…",
    "Оформление удалено": "The look has been deleted",
    // Встроенные оформления (overlay/presets.js)
    "Классика": "Classic",
    "Жирные белые цифры с обводкой, подпрыгивание и вспышка.": "Bold white digits with an outline, a bounce and a flash.",
    "Мем": "Meme",
    "Шрифт Impact как в мемах, число трясётся при каждом мате.": "The Impact font from memes; the number shakes with every swear.",
    "Неон": "Neon",
    "Голубая неоновая вывеска с розовым свечением и мерцанием.": "A blue neon sign with a pink glow and flicker.",
    "Ретро": "Retro",
    "Моноширинный шрифт и пошаговая анимация, как в старых играх.": "A monospace font and step animation, like in old games.",
    "Минимализм": "Minimal",
    "Аккуратный тонкий шрифт без обводки, мягкое появление.": "A neat thin font without an outline, a soft fade-in.",
    "Цензура": "Censored",
    "Фирменный: красная плашка как значок программы, при каждом мате вылетает «#!@%».":
      "Signature style: a red plaque like the app icon; every swear pops out a comic “#!@%”.",
    "Взрыв": "Explosion",
    "Огненные цифры, резкое увеличение и разлетающиеся искры.": "Fiery digits, a sharp zoom and flying sparks.",

    // Вкладка «Настройки»: слова и модель
    "Что считать": "What to count",
    "Обновить списки": "Refresh lists",
    "✎ Изменить список": "✎ Edit list",
    "📁 Папка со списками": "📁 Lists folder",
    "Свой список — любой .txt-файл в этой папке: по одному корню на строку, слово засчитывается, если начинается с корня. Правки подхватываются сами, без перезапуска.":
      "Your own list is any .txt file in this folder: one root per line; a word counts if it starts with a root. Edits are picked up automatically, without a restart.",
    "В папке нет ни одного списка": "There are no lists in the folder",
    "Маты (18+)": "Russian swear words (18+)",
    "Слова-паразиты": "Russian filler words",
    "Мой список (из words.txt)": "My list (from words.txt)",
    "Модель распознавания": "Recognition model",
    "Язык речи": "Speech language",
    "Русский": "Russian",
    "Английский": "English",
    "Для английской речи выберите и английский список слов (раздел «Список слов» выше).":
      "For English speech, also pick an English word list (the “What to count” section above).",
    "Модель уже скачана, сейчас она читается с диска в оперативную память. Пока загрузка не закончится, слова не считаются. Можно выбрать другую модель — эта загрузка прервётся.":
      "The model is already downloaded and is now being read from disk into memory. Words aren't counted until loading finishes. You can pick another model — this loading will stop.",
    "Модель ещё не скачана. Скачайте любую модель ниже — она включится сама": "No model downloaded yet. Download any model below — it will switch on by itself",
    "Модель работает": "The model is running",
    "Модель загружена, но микрофон не открылся": "The model has loaded, but the microphone didn't open",
    "Ошибка распознавания, подробности в консоли приложения. Нажмите на модель, чтобы перезапустить":
      "Recognition error, see the app console for details. Click the model to restart it",
    "Распознавание остановлено": "Recognition stopped",
    "Распаковка…": "Unpacking…",
    "выбрана": "selected",
    "не скачана": "not downloaded",
    "скачивается": "downloading",
    "архив": "the archive",
    "Или скачайте": "Or download",
    "вручную и распакуйте в папку models/ рядом с программой.": "manually and unpack it into the models/ folder next to the program.",
    "Подробнее": "More",
    "Отменить": "Cancel",
    "⬇ Скачать": "⬇ Download",
    "⬇ Подготовить": "⬇ Prepare",
    "Сохраните API-ключ.": "Save the API key.",
    "Выбранную модель удалить нельзя: сначала выберите другую": "The selected model can't be deleted: pick another one first",
    "Удалить модель с диска": "Delete the model from disk",
    "Когда скачается, она включится сама. Страницу можно закрыть: скачивание идёт в приложении.":
      "It will switch on by itself once downloaded. You can close the page: the download runs in the app.",
    "Страницу можно закрыть: скачивание идёт в приложении.": "You can close the page: the download runs in the app.",
    // Облачные модели
    "облако": "cloud",
    "Для облачной модели нужен API-ключ сервиса: введите его в карточке модели ниже":
      "A cloud model needs the service's API key: enter it in the model card below",
    "Микрофон откроется, когда будет введён API-ключ": "The microphone will open once the API key is entered",
    "Сохранить ключ": "Save key",
    "Удалить ключ": "Delete key",
    "Где взять ключ": "Where to get a key",
    "быстрая и недорогая, от Deepgram": "fast and inexpensive, from Deepgram",
    "новая модель Deepgram, точнее Nova-2": "Deepgram's new model, more accurate than Nova-2",
    "экономная модель OpenAI": "OpenAI's economical model",
    "самая точная у OpenAI": "OpenAI's most accurate",
    "классический Whisper через API OpenAI": "classic Whisper through the OpenAI API",
    "Whisper на Groq, очень быстро и дёшево": "Whisper on Groq, very fast and cheap",
    "самый точный Whisper на Groq": "the most accurate Whisper on Groq",
    "модель ElevenLabs": "an ElevenLabs model",
    "Проверенная модель Deepgram: распознаёт быстро, цена за минуту невысокая. Подходит, если нужна скорость и недорого.":
      "A proven Deepgram model: recognizes fast, with a low price per minute. Fits when you need speed and a low price.",
    "Новая модель Deepgram: точнее Nova-2, лучше справляется с шумом и разговорной речью.":
      "Deepgram's new model: more accurate than Nova-2, copes better with noise and conversational speech.",
    "Облегчённая модель OpenAI: точнее исходного Whisper и дешевле GPT-4o Transcribe.":
      "OpenAI's lightweight model: more accurate than the original Whisper and cheaper than GPT-4o Transcribe.",
    "Самая точная модель распознавания OpenAI. Стоит дороже остальных у этого сервиса.":
      "OpenAI's most accurate recognition model. Costs more than the others from this service.",
    "Whisper large-v2, работающий на серверах OpenAI: нагрузки на компьютер нет совсем.":
      "Whisper large-v2 running on OpenAI's servers: no load on your computer at all.",
    "Whisper large-v3 turbo на серверах Groq: самый дешёвый способ получить Whisper, работает быстро. Сервис округляет каждый запрос до 10 секунд, поэтому короткие фразы обходятся как десятисекундные.":
      "Whisper large-v3 turbo on Groq's servers: the cheapest way to get Whisper, and fast. The service rounds each request up to 10 seconds, so short phrases cost like ten-second ones.",
    "Полная Whisper large-v3 на серверах Groq: точнее turbo-версии. Сервис округляет каждый запрос до 10 секунд.":
      "Full Whisper large-v3 on Groq's servers: more accurate than the turbo version. The service rounds each request up to 10 seconds.",
    "Модель распознавания речи ElevenLabs, точная на многих языках, в том числе на русском.":
      "ElevenLabs' speech recognition model, accurate in many languages, Russian included.",
    "Ключ должен быть одной строкой без пробелов и русских букв":
      "The key must be a single string without spaces or Russian letters",
    // Модели (app/stt/catalog.py)
    "Базовая": "Basic",
    "Экономная": "Lightweight",
    "Сбалансированная": "Balanced",
    "Разговорная": "Conversational",
    "Самая точная": "Most accurate",
    "Для мощных ПК": "For powerful PCs",
    "Современная": "Modern",
    "Точная": "Accurate",
    "Устойчивая к шуму": "Noise-resistant",
    "понимает речь сквозь шум и музыку": "understands speech through noise and music",
    "классическая Vosk, работает везде": "classic Vosk, runs anywhere",
    "самая лёгкая, для слабых ПК": "the lightest, for weak PCs",
    "хорошая точность при малой памяти": "good accuracy with little memory",
    "для живой быстрой речи": "for lively, fast speech",
    "лучшее распознавание, текст фразами": "the best recognition, text in phrases",
    "точная, но нужно 5,5 ГБ памяти": "accurate, but needs 5.5 GB of memory",
    "точнее базовой при малой памяти": "more accurate than basic with little memory",
    "крупнее базовой, с большим словарём": "bigger than basic, with a large vocabulary",
    "(T-one, Т-Банк)": "(T-one, T-Bank)",
    "(GigaAM v3, Сбер)": "(GigaAM v3, Sber)",
    "Загружается за секунду и почти не нагружает компьютер во время игры или стрима. Распознаёт хуже: путает похожие слова, хуже справляется с быстрой речью, шумом и редкими словами, поэтому часть слов может не засчитаться.":
      "Loads in a second and barely loads the computer during a game or stream. Recognizes worse: confuses similar words and copes worse with fast speech, noise and rare words, so some words may not count.",
    "Новая модель от авторов Vosk на современной архитектуре. Скачивается быстрее всех и занимает меньше памяти, чем базовая, а слова обычно распознаёт точнее. Почти не нагружает компьютер.":
      "A new model from the Vosk authors on a modern architecture. Downloads fastest of all and takes less memory than basic, while usually recognizing words more accurately. Barely loads the computer.",
    "Старшая версия экономной модели от авторов Vosk: крупнее и точнее, особенно на разговорной речи. Памяти занимает всё ещё немного, поэтому подойдёт, если модель для мощных ПК слишком тяжела для компьютера.":
      "The bigger sibling of the lightweight model from the Vosk authors: larger and more accurate, especially on conversational speech. It still takes little memory, so it fits when the model for powerful PCs is too heavy for your computer.",
    "Модель Т-Банка, обученная на живой разговорной речи, в том числе на звонках. Хорошо понимает быструю и не очень чёткую речь. Процессор нагружает немного сильнее экономной и сбалансированной, но для игр и стримов это незаметно.":
      "A T-Bank model trained on live conversational speech, including phone calls. Understands fast and not very clear speech well. Loads the CPU a bit more than the lightweight and balanced models, but it's unnoticeable in games and streams.",
    "Модель Сбера, одна из самых точных для русского языка, а памяти занимает в разы меньше модели для мощных ПК. Распознаёт речь целыми фразами, поэтому текст обновляется примерно раз в секунду, а не после каждого слова.":
      "A Sber model, one of the most accurate for Russian, taking several times less memory than the model for powerful PCs. Recognizes speech in whole phrases, so the text updates about once a second rather than after every word.",
    "Ошибается в 1,5–2,5 раза реже базовой и лучше понимает разговорную речь. Требует много оперативной памяти и заметнее нагружает процессор: на слабом компьютере может мешать игре и трансляции.":
      "Makes 1.5–2.5 times fewer mistakes than basic and understands conversational speech better. Needs a lot of memory and loads the CPU more noticeably: on a weak computer it may get in the way of the game and stream.",
    "Загружается за секунду и почти не нагружает компьютер во время игры или стрима. Распознаёт хуже остальных: с быстрой речью и шумом часть слов может не засчитаться.":
      "Loads in a second and barely loads the computer during a game or stream. Recognizes worse than the others: with fast speech and noise some words may not count.",
    "Новая потоковая модель на современной архитектуре: слова распознаёт точнее базовой, особенно в разговорной речи, а памяти занимает немного.":
      "A new streaming model on a modern architecture: recognizes words more accurately than basic, especially in conversational speech, and takes little memory.",
    "Модель Whisper от OpenAI, обученная на сотнях тысяч часов речи со всего интернета. Хорошо понимает речь сквозь шум, музыку и акценты. Распознаёт фразами, как самая точная, но процессор нагружает заметно сильнее: на слабом компьютере может мешать игре.":
      "OpenAI's Whisper model, trained on hundreds of thousands of hours of speech from across the internet. Understands speech well through noise, music and accents. Recognizes in phrases, like the most accurate one, but loads the CPU noticeably more: on a weak computer it may get in the way of the game.",
    "Английская модель Whisper от OpenAI, обученная на сотнях тысяч часов речи. Обычно точнее остальных английских моделей и лучше понимает речь сквозь шум, музыку и акценты. Распознаёт фразами и заметно сильнее нагружает процессор: на слабом компьютере может мешать игре.":
      "OpenAI's English Whisper model, trained on hundreds of thousands of hours of speech. Usually more accurate than the other English models and better at understanding speech through noise, music and accents. Recognizes in phrases and loads the CPU noticeably more: on a weak computer it may get in the way of the game.",
    "Старшая модель Vosk с большим словарём: реже путает похожие слова и лучше узнаёт редкие. Памяти и процессора нужно чуть больше, чем базовой.":
      "The bigger Vosk model with a large vocabulary: confuses similar words less often and recognizes rare ones better. Needs slightly more memory and CPU than basic.",

    // Цели, горячие клавиши, автозапуск, OBS
    "Цели": "Goals",
    "Особые числа": "Special numbers",
    "Например: 10, 50, 100": "For example: 10, 50, 100",
    "Цель": "Goal",
    "Без цели": "No goal",
    "На особых числах и на цели оверлей празднует: звёзды и фанфары. До цели идёт отсчёт «осталось N» — на вкладке «Счётчик» и отдельным источником для OBS.":
      "On special numbers and on the goal, the overlay celebrates with stars and fanfare. Before the goal there's a “N left” countdown — on the Counter tab and as a separate OBS source.",
    "Особые числа — целые числа через запятую": "Special numbers are whole numbers separated by commas",
    "Цель — целое число; пустое поле — без цели": "The goal is a whole number; an empty field means no goal",
    "Сохранено": "Saved",
    "Горячие клавиши": "Hotkeys",
    "Работают, даже когда окно свёрнуто и вы в игре. Нажмите на кнопку, затем нужное сочетание. Backspace — убрать, Esc — отмена.":
      "They work even when the window is minimized and you're in a game. Click a button, then press the shortcut. Backspace clears it, Esc cancels.",
    "Пауза": "Pause",
    "не задано": "not set",
    "Сочетание занято другой программой": "The shortcut is taken by another program",
    "Нажмите сочетание…": "Press a shortcut…",
    "Автозапуск": "Autostart",
    "Запускать вместе с Windows": "Start with Windows",
    "(свёрнутой в трей)": "(minimized to the tray)",
    "Когда запускается OBS": "When OBS starts",
    "Ничего не делать": "Do nothing",
    "Напомнить уведомлением": "Remind with a notification",
    "Запустить счётчик": "Start the counter",
    "Когда начинается трансляция": "When a stream starts",
    "Начало трансляции программа узнаёт от OBS — порт и пароль задаются в разделе «OBS». Реакция на OBS работает, когда счётчик закрыт: вместо него в фоне ждёт маленький процесс без окна и без микрофона. Он выходит, как только счётчик запущен, а после выхода из счётчика снова ждёт OBS.":
      "The program learns that a stream has started from OBS — the port and password are set in the “OBS” section. Reacting to OBS works while the counter is closed: a small background process without a window or microphone waits instead. It exits as soon as the counter starts and waits for OBS again after you quit the counter.",
    "Программа связывается с OBS по WebSocket. В OBS откройте «Инструменты → Настройки сервера WebSocket», включите сервер и перенесите сюда порт и пароль.":
      "The program talks to OBS over WebSocket. In OBS, open “Tools → WebSocket Server Settings”, enable the server and copy the port and password here.",
    "Порт сервера WebSocket": "WebSocket server port",
    "Пароль сервера WebSocket": "WebSocket server password",
    "Пароль (если задан в OBS)": "Password (if set in OBS)",
    "Пароль сохранён (пусто — не менять)": "Password saved (leave empty to keep it)",
    "Сохранить": "Save",
    "Проверить": "Test",
    "Подключаюсь к OBS…": "Connecting to OBS…",
    "OBS на связи, трансляция идёт": "OBS is connected, the stream is live",
    "OBS на связи. Не забудьте сохранить порт и пароль": "OBS is connected. Don't forget to save the port and password",
    "OBS на связи": "OBS is connected",
    "Сбрасывать счёт, когда начинается трансляция": "Reset the count when a stream starts",
    "Сбрасывать счёт, когда начинается запись": "Reset the count when a recording starts",
    "При": "At",
    "Сколько слов до смены сцены": "How many words before the scene switch",
    "словах включить сцену": "words, switch to the scene",
    "не переключать": "don't switch",
    "Загрузить сцены из OBS": "Load scenes from OBS",
    "Команда": "The",
    "!маты": "!swears",
    "в чате Twitch и другие связки — через Streamer.bot, см.": "Twitch chat command and other integrations — via Streamer.bot, see the",
    "инструкцию": "guide",

    // Обновления и «О программе»
    "Обновления": "Updates",
    "Нужно обязательное обновление.": "A required update is needed.",
    "Пока оно не установлено, программа не считает слова и не меняет настройки. Если скачать не получается, возьмите новую версию":
      "Until it's installed, the program doesn't count words or change settings. If the download fails, get the new version",
    "на странице релиза": "on the release page",
    "Что нового": "What's new",
    "Проверять обновления при запуске": "Check for updates on startup",
    "Устанавливать обновления автоматически": "Install updates automatically",
    "Устанавливать обновления автоматически?": "Install updates automatically?",
    "Сейчас это выключено. Если включить, новая версия будет скачиваться и ставиться при запуске программы, и она сама перезапустится. Передумать можно в разделе «Обновления».":
      "This is off right now. If you turn it on, a new version is downloaded and installed when the program starts, and it restarts by itself. You can change your mind in the \"Updates\" section.",
    "Работает только в собранной программе (exe).": "Only works in the built program (exe).",
    "Что нового и история изменений": "What's new and changelog",
    "История изменений": "Changelog",
    "Включить": "Turn on",
    "Не сейчас": "Not now",
    "Закрыть": "Close",
    "Позже": "Later",
    "Страница релиза": "Release page",
    "Для этой версии нет заметок.": "There are no notes for this version.",
    "Перезапустить и обновить": "Restart and update",
    "Скачать и установить": "Download and install",
    "Проверить обновления": "Check for updates",
    "Проверяю…": "Checking…",
    "Распаковываю…": "Unpacking…",
    "(собранная программа без неё не работает).": "(the built program doesn't work without it).",
    "О программе": "About",
    "Изначально задумывалась как счётчик матов для стримов в OBS, но используйте её как угодно: OBS не обязателен, а считать можно любые слова — слова-паразиты, имя друга, что угодно. Список выбирается в разделе «Что считать», там же можно создать свой.":
      "It was made as a swear counter for OBS streams, but use it however you like: OBS isn't required, and it can count any words — filler words, a friend's name, anything. Pick the list in the “What to count” section, where you can also make your own.",
    "Свободная программа под лицензией GNU GPL v3. Предоставляется «как есть», без каких-либо гарантий.":
      "Free software under the GNU GPL v3 license. Provided “as is”, without any warranty.",
    "❤ Поддержать": "❤ Support",
    "Программа бесплатная. Если она пригодилась — можно поддержать автора или заказать у него личное оформление счётчика.":
      "The program is free. If you find it useful, you can support the author or order a personal counter look from them.",
    "Нажмите на ссылку или наведите камеру телефона на QR-код.": "Click a link or point your phone camera at the QR code.",

    // Заказ оформления
    "Заказать оформление": "Order a look",
    "Опишите, каким вы видите счётчик: цвета, шрифт, картинки, анимацию, звук. Можно приложить ссылки на примеры. Автор ответит на почту для связи и обсудит сроки и цену.":
      "Describe how you see the counter: colors, font, images, animation, sound. You can add links to examples. The author will reply to your contact email to discuss the timing and price.",
    "Почта для связи": "Contact email",
    "Каким должно быть оформление": "What the look should be like",
    "Например: огненные цифры, взрыв при прибавлении, звук как в аркадах": "For example: fiery digits, an explosion on each increment, an arcade sound",
    "Скопировать текст письма": "Copy the email text",
    "Отмена": "Cancel",
    "Отправить": "Send",
    "Ещё раз": "Again",
    "✓ Текст скопирован": "✓ Text copied",
    "Готовлю письмо…": "Preparing the email…",
    "Укажите почту, на которую автор сможет ответить": "Enter an email the author can reply to",
    "Опишите, каким должно быть оформление": "Describe what the look should be like",
    "Напишите автору с любой почты: адрес и текст письма можно скопировать.": "Write to the author from any email: you can copy the address and the text.",
    "Письмо открылось в почтовой программе: проверьте его и отправьте.": "The email has opened in your mail program: check it and send it.",
    "Яндекс Почте": "Yandex Mail",
    "Почте Mail": "Mail.ru",
    "Рамблер Почте": "Rambler Mail",
    "iCloud Почте": "iCloud Mail",

    // Ошибки с сервера и при запросах
    "Нет связи с приложением. Проверьте, что оно запущено, и повторите": "No connection to the app. Check that it's running and try again",
    "Сервер не знает этой команды: перезапустите приложение, оно запущено со старой версией": "The server doesn't know this command: restart the app, it's running an older version",
    "Установите обязательное обновление, чтобы продолжить": "Install the required update to continue",
    "Откройте программу по адресу localhost": "Open the program at localhost",
    "Запрос с чужого сайта отклонён": "Request from another site rejected",
    "Неизвестное действие": "Unknown action",
    "Это сочетание уже назначено другому действию": "This shortcut is already assigned to another action",
    "Добавьте Ctrl, Alt, Shift или Win: без них клавиша мешала бы печатать": "Add Ctrl, Alt, Shift or Win: without them the key would get in the way of typing",
    "Проверьте почту для связи": "Check the contact email",
    "Заказ оформления недоступен": "Ordering a look is unavailable",
    "Неверный режим автозапуска": "Invalid autostart mode",
    "Порт — число от 1 до 65535": "The port is a number from 1 to 65535",
    "Слишком длинное имя сцены": "The scene name is too long",
    "Такого счётчика нет": "No such counter",
    "Введите название счётчика": "Enter a counter name",
    "Такого списка нет": "No such list",
    "Неверный id пресета": "Invalid look id",
    "Неверное положение подписи": "Invalid label position",
    "Эта модель не скачивается": "This model isn't downloading",
    "Модель скачивается: сначала отмените скачивание": "The model is downloading: cancel the download first",
    "Модель не скачана": "The model isn't downloaded",
    "Такого звука нет": "No such sound",
    "Такого оформления нет": "No such look",
    "Открыть файл можно только в Windows": "Files can only be opened on Windows",
    "Обновление не скачивается": "The update isn't downloading",
    "Обновление ставится только в собранной программе (exe)": "Updates can only be installed in the built program (exe)",
    "Нет доступного обновления": "No update available",
    "Обновление ещё не скачано": "The update hasn't been downloaded yet",
    "Это не zip-архив с оформлением": "This isn't a zip archive with a look",
    "В архиве нет preset.json": "There's no preset.json in the archive",
    "preset.json не читается: проверьте, что это JSON в UTF-8": "preset.json can't be read: check that it's JSON in UTF-8",
    "Архив пустой": "The archive is empty",
    "Архив повреждён": "The archive is damaged",
    "Вставьте ссылку, которая начинается с https://": "Paste a link that starts with https://",
    "Не удалось скачать: проверьте интернет и ссылку": "Couldn't download: check your internet connection and the link",
    "Скачивание заняло слишком долго: попробуйте ещё раз": "The download took too long: try again",
    "По ссылке не zip-архив, а страница: нужна прямая ссылка на файл": "The link leads to a page, not a zip archive: a direct link to the file is needed",
    "Нет связи с OBS": "No connection to OBS",
    "OBS не ответил на запрос": "OBS didn't respond to the request",
    "OBS не ответил на подключение": "OBS didn't respond to the connection",
    "Связь с OBS прервалась": "The connection to OBS was lost",
    "OBS закрыл соединение": "OBS closed the connection",
    "OBS прислал непонятный ответ": "OBS sent an unexpected response",
    "OBS не принял подключение": "OBS refused the connection",
    "По этому порту отвечает не OBS": "Something other than OBS answers on this port",
    "OBS не принял пароль: проверьте его в настройках сервера WebSocket": "OBS rejected the password: check it in the WebSocket server settings",
    "В OBS для сервера WebSocket задан пароль: укажите его здесь": "A password is set for the WebSocket server in OBS: enter it here",
    "OBS не отвечает. Проверьте, что OBS запущен и в «Инструменты → Настройки сервера WebSocket» включён сервер с этим портом":
      "OBS isn't responding. Check that OBS is running and the server with this port is enabled in “Tools → WebSocket Server Settings”",
    "GitHub временно ограничил запросы, попробуйте позже": "GitHub has temporarily limited requests, try again later",
  };

  // Строки с переменной частью: {} — любой текст (тоже переводится), {1}, {2} в
  // переводе — части по номеру, если порядок другой.
  const PATTERNS = [
    ["Локальные · {}", "Local · {}"],
    ["Облачные · {}", "Cloud · {}"],
    ["Ошибка сервера ({})", "Server error ({})"],
    ["{} (нет файла)", "{} (no file)"],
    ["{} (не найден)", "{} (not found)"],
    ["Сохранено: {}", "Saved: {}"],
    ["Архив сохранён: {}", "Archive saved: {}"],
    ["чаще всего: {}", "most frequent: {}"],
    ["всего {}", "{} in total"],
    ["Слушает: {}", "Listening to: {}"],
    ["По умолчанию — {}", "Default — {}"],
    ["Файл больше {}", "The file is larger than {}"],
    ["Архив больше {}", "The archive is larger than {}"],
    ["Файл по ссылке больше {}", "The linked file is larger than {}"],
    ["Распакованное оформление больше {}", "The unpacked look is larger than {}"],
    ["Личное оформление для: {}", "Personal look for: {}"],
    ["Звук оформления «{}»", "Sound of the “{}” look"],
    ["Оформление «{}» установлено и включено", "The “{}” look is installed and on"],
    ["Скачано {} из {}", "Downloaded {} of {}"],
    ["Облако: {}", "Cloud: {}"],
    ["Неизвестный сервис {}", "Unknown service {}"],
    [
      "{} Звук ваших фраз отправляется в {} и оплачивается по вашему API-ключу. Остальное распознавание остаётся на компьютере: в облако уходят только законченные фразы. Нужен интернет.",
      "{} The audio of your phrases is sent to {} and billed to your API key. Everything else stays on the computer: only finished phrases go to the cloud. Internet is required.",
    ],
    ["Ключ {} сохранён. Звук фраз уходит в {}.", "The {} key is saved. Phrase audio is sent to {}."],
    ["Звук фраз будет отправляться в {}: нужен ваш API-ключ.", "Phrase audio will be sent to {}: your API key is required."],
    ["API-ключ {}", "{} API key"],
    ["Скачано {}", "Downloaded {}"],
    ["Размер на диске: {}", "Size on disk: {}"],
    ["в памяти: {}", "in memory: {}"],
    ["Загрузка в память при запуске: {}", "Loading into memory at startup: {}"],
    ["Скачивается кнопкой «Скачать» ({}).", "Downloaded with the “Download” button ({})."],
    ["{}. Нажмите «Скачать», чтобы попробовать ещё раз", "{}. Click “Download” to try again"],
    ["{}. Нажмите «Подготовить», чтобы попробовать ещё раз", "{}. Click “Prepare” to try again"],
    ["Скачать модель ({})", "Download the model ({})"],
    ["Скачать детектор речи ({}), модель остаётся в облаке", "Download the speech detector ({}); the model stays in the cloud"],
    ["Нажмите «⬇ Подготовить»: скачается детектор речи ({}). Он находит в звуке фразы, текст не распознаёт.", "Press “⬇ Prepare”: the speech detector ({}) is downloaded. It finds phrases in the audio and does not recognize text."],
    ["Распознаёт фразы сам {} в облаке, по вашему ключу.", "{} recognizes the phrases itself, in the cloud, using your key."],
    ["Кнопка «Подготовить» скачивает детектор речи ({}): он находит в звуке фразы. Распознаёт их модель в облаке, её скачивать не нужно.", "The “Prepare” button downloads the speech detector ({}): it finds phrases in the audio. The model recognizes them in the cloud, no model download needed."],
    ["Модель «{}» ещё не была скачана — скачиваю её ({}). {}", "The “{}” model hasn't been downloaded yet — downloading it ({}). {}"],
    ["Загрузка модели «{}» в память… {}", "Loading the “{}” model into memory… {}"],
    ["Не удалось скачать модель: {}", "Couldn't download the model: {}"],
    ["Не удалось удалить модель: {}", "Couldn't delete the model: {}"],
    ["Неизвестная модель {}", "Unknown model {}"],
    ["Обязательно {}", "Required {}"],
    ["Доступна обязательная версия {} (у вас v{}).", "Required version {} is available (you have v{})."],
    ["Доступна новая версия {} (у вас v{}).", "New version {} is available (you have v{})."],
    ["Доступна обязательная версия {}. Из исходников обновитесь через git pull{}",
      "Required version {} is available. When running from source, update with git pull{}"],
    ["Доступна новая версия {}. Из исходников обновитесь через git pull{}",
      "New version {} is available. When running from source, update with git pull{}"],
    ["Вышла версия v{}", "Version v{} is out"],
    ["Скачиваю… {}%", "Downloading… {}%"],
    ["Не удалось установить обновление: {}", "Couldn't install the update: {}"],
    ["Доступна {}", "{} available"],
    ["Доступна", "Available"],
    ["У вас последняя версия: v{}", "You have the latest version: v{}"],
    ["Скачиваю {}: {}", "Downloading {}: {}"],
    ["{}% из {}", "{}% of {}"],
    ["{} скачана. Программа перезапустится в новой версии.", "{} has been downloaded. The program will restart in the new version."],
    ["Не удалось проверить обновления: {}", "Couldn't check for updates: {}"],
    ["Не удалось скачать обновление: {}", "Couldn't download the update: {}"],
    ["Версия v{}", "Version v{}"],
    ["Занято другой программой, выберите другое: {}", "Taken by another program, pick another: {}"],
    ["Неизвестная клавиша: {}", "Unknown key: {}"],
    ["Неверное сочетание: {}", "Invalid shortcut: {}"],
    ["QR-код {}", "QR code {}"],
    ["Открыть в {}", "Open in {}"],
    ["Письмо открылось в почтовой программе: проверьте его и отправьте. Если удобнее, напишите из {}.",
      "The email has opened in your mail program: check it and send it. If you prefer, write from {}."],
    ["Нажмите «Открыть в {}»: письмо автору уже заполнено, останется отправить.",
      "Click “Open in {}”: the email to the author is already filled in, you just need to send it."],
    ["Нажмите «Открыть в {}» и вставьте в новое письмо адрес автора и текст: их можно скопировать.",
      "Click “Open in {}” and paste the author's address and the text into a new email: you can copy them."],
    ["Тема: {}", "Subject: {}"],
    ["Микрофон «{}» не найден: возможно, он отключён", "Microphone “{}” not found: it may be disconnected"],
    ["Микрофон «{}» не найден", "Microphone “{}” not found"],
    ["Микрофон «{}» перестал отвечать", "Microphone “{}” stopped responding"],
    ["Не удалось включить прослушивание: {}", "Couldn't turn on listening: {}"],
    ["Размер должен быть от {} до {}%", "The size must be from {} to {}%"],
    ["Подпись длиннее {} символов", "The label is longer than {} characters"],
    ["Название длиннее {} символов", "The name is longer than {} characters"],
    ["Описание длиннее {} символов: сократите его", "The description is longer than {} characters: shorten it"],
    ["Счётчиков не больше {}", "No more than {} counters"],
    ["Порог — целое число от 0 до {}", "The threshold is a whole number from 0 to {}"],
    ["Особые числа — от 1 до {}", "Special numbers are from 1 to {}"],
    ["Не больше {} особых чисел", "No more than {} special numbers"],
    ["Цель — от 1 до {}, 0 — без цели", "The goal is from 1 to {}, 0 means no goal"],
    ["В библиотеке уже {} звуков: удалите ненужные", "The library already has {} sounds: delete the ones you don't need"],
    ["Уже установлено {} оформлений: удалите ненужные", "{} looks are already installed: delete the ones you don't need"],
    ["Не удалось сохранить таблицу: {}", "Couldn't save the table: {}"],
    ["Не удалось сохранить архив: {}", "Couldn't save the archive: {}"],
    ["Не удалось открыть: {}", "Couldn't open: {}"],
    ["Не удалось записать автозапуск в реестр: {}", "Couldn't write autostart to the registry: {}"],
    ["Сервер ответил ошибкой {}", "The server responded with error {}"],
    ["GitHub ответил ошибкой {}", "GitHub responded with error {}"],
  ];

  // Число со словом: «5 слов» → «5 words».
  const NOUNS = {
    слово: "word", слова: "word", слов: "word",
    сессия: "session", сессии: "session", сессий: "session",
    корень: "root", корня: "root", корней: "root",
  };
  const COUNTED = /^(\d+) ([а-яё]+)$/i;
  // Размеры и время из каталога моделей: «~0,3 ГБ», «1,5–2 мин».
  const UNITS = { ГБ: "GB", МБ: "MB", с: "s", мин: "min" };
  const AMOUNT = /^(~?[\d,]+(?:–[\d,]+)?) (ГБ|МБ|с|мин)$/;
  // Части составных строк: «дата · длительность · 5 слов», «список — 12 корней».
  const SEPARATORS = [" · ", " — "];

  const compiled = PATTERNS.map(([ru, en]) => {
    const source = ru.replace(/[.*+?^$()|[\]\\]/g, "\\$&").replace(/\{\}/g, "([\\s\\S]*?)");
    return [new RegExp(`^${source}$`), en];
  });

  function fill(template, parts) {
    let next = 0;
    return template.replace(/\{(\d*)\}/g, (_, n) => {
      const part = n ? parts[Number(n) - 1] : parts[next++];
      return translatePart(part === undefined ? "" : part);
    });
  }

  // Перевод части с сохранением пробелов по краям; без перевода — как была.
  function translatePart(text) {
    const m = /^(\s*)([\s\S]*?)(\s*)$/.exec(text);
    const en = translateCore(m[2].replace(/\s+/g, " "));
    return en === null ? text : m[1] + en + m[3];
  }

  function translateCore(text) {
    if (!text || !CYRILLIC.test(text)) return null;
    if (Object.prototype.hasOwnProperty.call(EXACT, text)) return EXACT[text];
    let m = COUNTED.exec(text);
    if (m && NOUNS[m[2].toLowerCase()]) return `${m[1]} ${NOUNS[m[2].toLowerCase()]}${m[1] === "1" ? "" : "s"}`;
    m = AMOUNT.exec(text);
    if (m) return `${m[1].replace(/,/g, ".")} ${UNITS[m[2]]}`;
    for (const [re, en] of compiled) {
      m = re.exec(text);
      if (m) return fill(en, m.slice(1));
    }
    for (const separator of SEPARATORS) {
      if (!text.includes(separator)) continue;
      const parts = text.split(separator);
      const done = parts.map((part) => translateCore(part));
      if (done.some((part) => part !== null)) return done.map((part, i) => (part === null ? parts[i] : part)).join(separator);
    }
    return null;
  }

  // --- Язык страницы ---

  function stored() {
    try {
      return localStorage.getItem(STORAGE_KEY);
    } catch (e) {
      return null;
    }
  }

  function store(language) {
    try {
      localStorage.setItem(STORAGE_KEY, language);
    } catch (e) {}
  }

  function guess() {
    const browser = (navigator.language || "").toLowerCase();
    return /^(ru|uk|be|kk)\b/.test(browser) ? "ru" : "en";
  }

  const saved = stored();
  const language = saved === "ru" || saved === "en" ? saved : guess();
  document.documentElement.lang = language;

  // Сервер помнит выбор для всех окон и для трея: если он другой, открываемся на нём.
  fetch("/api/ui-language")
    .then((resp) => (resp.ok ? resp.json() : null))
    .then((data) => {
      if (!data || (data.language !== "ru" && data.language !== "en")) return;
      store(data.language);
      if (data.language !== language) location.reload();
    })
    .catch(() => {});

  function setupButton() {
    const button = document.getElementById("language");
    if (!button) return;
    const other = language === "ru" ? "en" : "ru";
    button.textContent = other.toUpperCase();
    button.title = other === "en" ? "English interface" : "Русский интерфейс";
    button.setAttribute("translate", "no");
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        await fetch("/api/ui-language", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ language: other }),
        });
      } catch (e) {
        // Без связи с сервером язык поменяется только на этой странице.
      }
      store(other);
      location.reload();
    });
  }

  if (language === "ru") {
    document.addEventListener("DOMContentLoaded", setupButton);
    return;
  }

  // --- Перевод страницы ---

  const ATTRIBUTES = ["title", "placeholder", "aria-label"];
  // Текст внутри textarea — то, что ввёл человек; её placeholder переводится.
  const SKIP_TEXT = new Set(["SCRIPT", "STYLE", "TEXTAREA"]);

  function skipped(element) {
    return !element || Boolean(element.closest("[translate=no]"));
  }

  function translateText(node) {
    const parent = node.parentElement;
    if (skipped(parent) || SKIP_TEXT.has(parent.tagName)) return;
    const en = translatePart(node.nodeValue);
    if (en !== node.nodeValue) node.nodeValue = en;
  }

  function translateAttributes(element) {
    if (skipped(element)) return;
    for (const name of ATTRIBUTES) {
      const value = element.getAttribute(name);
      if (!value) continue;
      const en = translatePart(value);
      if (en !== value) element.setAttribute(name, en);
    }
  }

  function translateTree(root) {
    if (root.nodeType === Node.TEXT_NODE) return translateText(root);
    if (root.nodeType !== Node.ELEMENT_NODE) return;
    translateAttributes(root);
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      if (node.nodeType === Node.TEXT_NODE) translateText(node);
      else translateAttributes(node);
    }
  }

  new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      if (mutation.type === "characterData") translateText(mutation.target);
      else if (mutation.type === "attributes") translateAttributes(mutation.target);
      else mutation.addedNodes.forEach(translateTree);
    }
  }).observe(document.documentElement, {
    subtree: true,
    childList: true,
    characterData: true,
    attributes: true,
    attributeFilter: ATTRIBUTES,
  });

  document.addEventListener("DOMContentLoaded", () => {
    document.title = translatePart(document.title);
    translateTree(document.body);
    setupButton();
  });

  window.translateText = translatePart; // для проверки перевода из консоли и тестов
})();
