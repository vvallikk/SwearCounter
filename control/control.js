(() => {
  "use strict";

  // --- Общее ---

  const $ = (id) => document.getElementById(id);

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  async function api(method, url, body) {
    const init = { method };
    if (body !== undefined) {
      init.headers = { "Content-Type": "application/json" };
      init.body = JSON.stringify(body);
    }
    let resp;
    try {
      resp = await fetch(url, init);
    } catch (e) {
      // Браузер пишет только «Failed to fetch»: приложение закрыто или перезапускается.
      throw new Error("Нет связи с приложением. Проверьте, что оно запущено, и повторите");
    }
    const data = await resp.json().catch(() => null);
    if (resp.ok) return data;
    const detail = data && data.detail;
    // Стандартные ответы FastAPI на незнакомый адрес: сервер старее страницы.
    if (detail === "Not Found" || detail === "Method Not Allowed") {
      throw new Error("Сервер не знает этой команды: перезапустите приложение, оно запущено со старой версией");
    }
    throw new Error((typeof detail === "string" && detail) || `Ошибка сервера (${resp.status})`);
  }

  function setStatus(node, text, error, ok) {
    node.textContent = text;
    node.classList.toggle("error", Boolean(error));
    node.classList.toggle("ok", Boolean(ok));
  }

  // Подтверждение вторым нажатием, а не confirm(): во встроенных браузерах
  // (док OBS, Simple Browser в VS Code) confirm() молча возвращает false.
  function confirmByTwoClicks(button, confirmLabel, action) {
    const label = button.textContent;
    let timer = null;
    const disarm = () => {
      clearTimeout(timer);
      timer = null;
      button.textContent = label;
      button.classList.remove("confirm");
    };
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      if (timer === null) {
        button.textContent = confirmLabel;
        button.classList.add("confirm");
        timer = setTimeout(disarm, 3000);
        return;
      }
      disarm();
      action();
    });
  }

  // --- Тема: при первом входе тёмная, потом — последний выбор ---

  const themeBtn = $("theme");

  function showTheme() {
    const dark = document.documentElement.dataset.theme !== "light";
    themeBtn.textContent = dark ? "☀" : "🌙";
    themeBtn.title = dark ? "Светлая тема" : "Тёмная тема";
  }

  themeBtn.addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem("theme", next);
    } catch (e) {}
    showTheme();
  });
  showTheme();

  // --- Счётчик ---

  const countEl = $("count");
  const dotEl = $("dot");
  const statusEl = $("status");
  const incBtn = $("inc");
  const resetBtn = $("reset");

  function setOnline(online) {
    dotEl.classList.toggle("online", online);
    statusEl.textContent = online ? "Подключено" : "Нет связи с сервером";
  }

  async function post(url, button) {
    button.disabled = true;
    try {
      countEl.textContent = (await api("POST", url)).count;
    } catch (e) {
      setOnline(false);
    } finally {
      button.disabled = false;
    }
  }

  incBtn.addEventListener("click", () => post("/api/increment", incBtn));
  confirmByTwoClicks(resetBtn, "Точно сбросить?", () => post("/api/reset", resetBtn));

  // --- Адрес оверлея копируется по клику ---

  const overlayBtn = $("overlay-url");
  const overlayLabel = overlayBtn.querySelector(".copy-label");
  const overlayUrl = `${location.origin}/overlay/`;
  $("overlay-url-text").textContent = overlayUrl;
  let copiedTimer = null;

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (e) {
      // Встроенные браузеры (док OBS) могут не давать доступ к Clipboard API.
      const area = document.createElement("textarea");
      area.value = text;
      document.body.append(area);
      area.select();
      const ok = document.execCommand("copy");
      area.remove();
      return ok;
    }
  }

  overlayBtn.addEventListener("click", async () => {
    const ok = await copyText(overlayUrl);
    overlayBtn.classList.toggle("copied", ok);
    overlayLabel.textContent = ok ? "Скопировано ✓" : "Не удалось скопировать";
    clearTimeout(copiedTimer);
    copiedTimer = setTimeout(() => {
      overlayBtn.classList.remove("copied");
      overlayLabel.textContent = "Копировать";
    }, 2000);
  });

  // --- Состояние распознавания (микрофон и модель) ---

  let speechTimer = null;

  async function refreshSpeech() {
    try {
      showSpeech(await api("GET", "/api/speech"));
    } catch (e) {}
  }

  function showSpeech(state) {
    const loading = state.status === "loading";
    showMic(state, loading);
    showModels(state, loading);
    // Пока модель грузится или переключается микрофон, опрашиваем сервер,
    // чтобы увидеть, чем это закончилось.
    clearTimeout(speechTimer);
    const downloading = state.models.some((m) => m.download && m.download.status !== "error");
    if (loading || downloading || state.mic_pending) speechTimer = setTimeout(refreshSpeech, 1000);
  }

  // --- Микрофон ---

  const micEl = $("mic");
  const micStatusEl = $("mic-status");
  const micRefreshBtn = $("mic-refresh");
  const micMonitorBtn = $("mic-monitor");
  const meterMaskEl = $("meter-mask");

  function showMic(state, loading) {
    $("mic-section").hidden = false;
    let text = "";
    let error = false;
    if (state.mic_pending) text = "Переключение микрофона…";
    else if (state.mic_error) [text, error] = [state.mic_error, true];
    else if (state.monitor_error) [text, error] = [state.monitor_error, true];
    else if (state.mic) text = `Слушает: ${state.mic}`;
    else if (loading) text = "Микрофон откроется, когда модель загрузится";
    else if (state.status === "no_model") text = "Микрофон откроется, когда модель скачается";
    setStatus(micStatusEl, text, error);
    showMonitor(Boolean(state.monitor));
    micMonitorBtn.disabled = !state.mic;
    if (!state.mic) targetLevel = 0;
  }

  function showMonitor(on) {
    micMonitorBtn.setAttribute("aria-pressed", String(on));
    micMonitorBtn.textContent = on ? "⏹ Остановить прослушивание" : "🎧 Слушать себя";
  }

  async function loadDevices() {
    micRefreshBtn.disabled = true;
    try {
      const { devices, default: def, selected } = await api("GET", "/api/devices");
      const options = [new Option(def ? `По умолчанию — ${def}` : "По умолчанию (системный)", "")];
      options.push(...devices.map((name) => new Option(name, name)));
      if (selected && !devices.includes(selected)) {
        // Выбранный микрофон сейчас отключён: показываем его, чтобы было понятно, что случилось.
        const missing = new Option(`${selected} (не найден)`, selected);
        missing.disabled = true;
        options.push(missing);
      }
      micEl.replaceChildren(...options);
      micEl.value = selected ?? "";
    } catch (e) {
      // нет связи с сервером: список обновится при переподключении
    } finally {
      micRefreshBtn.disabled = false;
    }
  }

  micRefreshBtn.addEventListener("click", loadDevices);
  micEl.addEventListener("change", async () => {
    showMonitor(false); // новый микрофон начинаем без прослушивания
    setStatus(micStatusEl, "Переключение микрофона…");
    try {
      showSpeech(await api("POST", "/api/speech/device", { device: micEl.value || null }));
    } catch (e) {
      setStatus(micStatusEl, e.message, true);
      loadDevices();
    }
  });
  micMonitorBtn.addEventListener("click", async () => {
    const enable = micMonitorBtn.getAttribute("aria-pressed") !== "true";
    try {
      await api("POST", "/api/speech/monitor", { enabled: enable });
      // Процесс распознавания включает прослушивание асинхронно — смотрим результат чуть позже.
      setTimeout(refreshSpeech, 400);
    } catch (e) {
      setStatus(micStatusEl, e.message, true);
    }
  });

  // Индикатор громкости: уровень приходит ~10 раз в секунду, между ними плавно спадает.
  let targetLevel = 0;
  let shownLevel = 0;

  function levelToPosition(level) {
    // Шкала в децибелах: от −60 дБ (тишина) до 0 дБ (максимум).
    if (level <= 0) return 0;
    return Math.min(Math.max((20 * Math.log10(level) + 60) / 60, 0), 1);
  }

  function drawMeter() {
    shownLevel = targetLevel > shownLevel ? targetLevel : shownLevel * 0.88;
    targetLevel *= 0.8;
    meterMaskEl.style.width = `${(1 - shownLevel) * 100}%`;
    requestAnimationFrame(drawMeter);
  }
  requestAnimationFrame(drawMeter);

  // --- Звук оповещения (тот же проигрыватель, что в оверлее: /overlay/sound.js) ---

  const MAX_SOUND_MB = 5;
  const SOUND_TYPES = { mp3: "audio/mpeg", wav: "audio/wav", ogg: "audio/ogg" };
  const player = window.createDingPlayer();
  const volumeEl = $("volume");
  const volumeValueEl = $("volume-value");
  const soundListEl = $("sound-list");
  const soundStatusEl = $("sound-status");
  const soundInput = $("sound-input");
  const soundUploadBtn = $("sound-upload");
  let volumeTimer = null;
  let renderedSoundsKey = "";
  let soundState = null; // последний ответ /api/sound: список перерисовывается и при смене пресета
  let standardSound = "ding"; // стандартный звук выбранного пресета (поле sound в presets.js)
  const STANDARD_NAMES = { ding: "Стандартный звон", ferret: "Стандартный: гуканье хорька" };

  function showVolume(volume) {
    volumeEl.value = volume;
    volumeValueEl.textContent = `${volume}%`;
  }

  function soundItem(id, name, active) {
    const item = el("div", active ? "sound-item active" : "sound-item");
    const pick = el("button", "sound-pick");
    pick.type = "button";
    pick.setAttribute("role", "radio");
    pick.setAttribute("aria-checked", String(active));
    pick.append(el("span", "radio"), el("span", "name", name));
    pick.title = name;
    pick.addEventListener("click", () => selectSound(id));
    const play = el("button", "icon-btn", "▶");
    play.type = "button";
    play.title = "Прослушать";
    play.addEventListener("click", () => {
      setStatus(soundStatusEl, "");
      player.preview(id);
    });
    item.append(pick, play);
    if (id !== null) {
      const del = el("button", "icon-btn", "🗑");
      del.type = "button";
      del.title = "Удалить";
      confirmByTwoClicks(del, "Удалить?", () => deleteSound(id));
      item.append(del);
    }
    return item;
  }

  // state — ответ /api/sound или сообщение "sound" из WebSocket.
  function showSound(state) {
    $("sound-section").hidden = false;
    // Ползунок не трогаем, пока его двигают: иначе он прыгал бы назад.
    if (volumeTimer === null && document.activeElement !== volumeEl) showVolume(state.volume);
    soundState = state;
    const key = JSON.stringify([state.sounds, state.active, standardSound]);
    if (key !== renderedSoundsKey) {
      renderedSoundsKey = key;
      soundListEl.replaceChildren(
        soundItem(null, STANDARD_NAMES[standardSound], state.active === null),
        ...state.sounds.map((s) => soundItem(s.id, s.name, s.id === state.active))
      );
    }
    return player.apply(state);
  }

  async function selectSound(id) {
    try {
      await showSound(await api("POST", "/api/sound/active", { id }));
      setStatus(soundStatusEl, "");
      player.play();
    } catch (e) {
      setStatus(soundStatusEl, e.message, true);
    }
  }

  async function deleteSound(id) {
    try {
      await showSound(await api("DELETE", `/api/sound/file/${encodeURIComponent(id)}`));
      setStatus(soundStatusEl, "");
    } catch (e) {
      setStatus(soundStatusEl, e.message, true);
    }
  }

  function sendVolume() {
    clearTimeout(volumeTimer);
    volumeTimer = null;
    api("POST", "/api/sound/volume", { volume: Number(volumeEl.value) }).catch(() => setOnline(false));
  }

  volumeEl.addEventListener("input", () => {
    showVolume(volumeEl.value);
    player.setVolume(Number(volumeEl.value));
    // Оверлею громкость отправляем не на каждый сдвиг, а когда ползунок замер.
    clearTimeout(volumeTimer);
    volumeTimer = setTimeout(sendVolume, 250);
  });
  volumeEl.addEventListener("change", () => {
    sendVolume();
    player.play(); // сразу слышно, что получилось
  });
  $("sound-test").addEventListener("click", () => player.play());

  soundUploadBtn.addEventListener("click", () => soundInput.click());
  soundInput.addEventListener("change", async () => {
    const file = soundInput.files[0];
    soundInput.value = ""; // чтобы тот же файл можно было выбрать ещё раз
    if (!file) return;
    const type = SOUND_TYPES[file.name.split(".").pop().toLowerCase()];
    if (!type) return setStatus(soundStatusEl, "Поддерживаются файлы MP3, WAV и OGG", true);
    if (file.size > MAX_SOUND_MB * 1024 * 1024) {
      return setStatus(soundStatusEl, `Файл больше ${MAX_SOUND_MB} МБ`, true);
    }
    soundUploadBtn.disabled = true;
    setStatus(soundStatusEl, "Загрузка…");
    try {
      if (!(await player.canDecode(await file.arrayBuffer()))) {
        return setStatus(soundStatusEl, "Не получилось прочитать файл как звук", true);
      }
      const resp = await fetch("/api/sound/file", {
        method: "PUT",
        headers: { "Content-Type": type, "X-Filename": encodeURIComponent(file.name) },
        body: file,
      });
      const body = await resp.json();
      if (!resp.ok) return setStatus(soundStatusEl, body.detail, true);
      await showSound(body);
      setStatus(soundStatusEl, "");
      player.play();
    } catch (e) {
      setStatus(soundStatusEl, "Не удалось загрузить файл", true);
    } finally {
      soundUploadBtn.disabled = false;
    }
  });

  // --- Оформление счётчика (пресеты описаны в /overlay/presets.js) ---

  const presets = window.OVERLAY_PRESETS || [];
  const presetEl = $("preset");
  const presetPreviewEl = $("preset-preview");
  const presetDescEl = $("preset-desc");
  let shownPreset = null;
  let presetRequests = 0; // сколько выборов ещё не подтвердил сервер

  presetEl.replaceChildren(...presets.map((p) => new Option(p.title, p.id)));

  // Превью загружается один раз, а стиль в нём меняется сообщением. Если бы iframe
  // перезагружался на каждую смену, при быстром переключении превью могло пропасть.
  function sendPreviewStyle() {
    const win = presetPreviewEl.contentWindow;
    if (!win || !shownPreset) return;
    const message = { type: "style", preset: shownPreset, label: labelTextEl.value.trim(), label_position: labelPositionEl.value };
    win.postMessage(message, location.origin);
  }
  presetPreviewEl.addEventListener("load", sendPreviewStyle);

  function showPreset(id) {
    const preset = presets.find((p) => p.id === id) || presets[0];
    if (!preset) return;
    $("preset-section").hidden = false;
    presetEl.value = preset.id;
    presetDescEl.textContent = preset.description;
    standardSound = STANDARD_NAMES[preset.sound] ? preset.sound : "ding";
    player.setStandard(standardSound);
    if (soundState) showSound(soundState);
    if (shownPreset === preset.id) return;
    const first = shownPreset === null;
    shownPreset = preset.id;
    // Без ?size число в превью подгоняется под рамку, как в OBS.
    if (first) presetPreviewEl.src = `/overlay/?preview=1&preset=${encodeURIComponent(preset.id)}`;
    else sendPreviewStyle();
  }

  presetEl.addEventListener("change", async () => {
    const id = presetEl.value;
    showPreset(id); // сразу, не дожидаясь сервера
    presetRequests += 1;
    try {
      await api("POST", "/api/overlay/preset", { preset: id });
    } catch (e) {
      setOnline(false);
    } finally {
      presetRequests -= 1;
    }
  });

  // Стиль от сервера (WebSocket). Пока свои выборы не подтверждены, приходят ответы
  // на прежние — они вернули бы список назад, поэтому их пропускаем.
  function showServerPreset(id) {
    if (presetRequests === 0) showPreset(id);
  }

  // --- Подпись к счётчику: текст и число — один источник в OBS ---

  const labelTextEl = $("label-text");
  const labelPositionEl = $("label-position");
  const labelStatusEl = $("label-status");
  let labelTimer = null; // отправка текста ждёт, пока перестанут печатать
  let labelRequests = 0;

  function showLabel(text, position) {
    $("label-section").hidden = false;
    labelTextEl.value = text;
    labelPositionEl.value = position;
    sendPreviewStyle();
  }

  async function sendLabel() {
    clearTimeout(labelTimer);
    labelTimer = null;
    labelRequests += 1;
    try {
      await api("POST", "/api/overlay/label", { text: labelTextEl.value, position: labelPositionEl.value });
      setStatus(labelStatusEl, "");
    } catch (e) {
      setStatus(labelStatusEl, e.message, true);
    } finally {
      labelRequests -= 1;
    }
  }

  labelTextEl.addEventListener("input", () => {
    sendPreviewStyle(); // превью меняется сразу, оверлей — когда замрёт ввод
    clearTimeout(labelTimer);
    labelTimer = setTimeout(sendLabel, 400);
  });
  labelPositionEl.addEventListener("change", () => {
    sendPreviewStyle();
    sendLabel();
  });

  // Подпись от сервера. Пока её редактируют здесь, не перезаписываем поле.
  function showServerLabel(text, position) {
    if (typeof text !== "string") return; // сервер старее страницы
    if (labelRequests > 0 || labelTimer !== null || document.activeElement === labelTextEl) return;
    showLabel(text, position);
  }

  // --- Модель распознавания: карточки, выбор кликом, описание раскрывается ---

  const progressEl = $("progress");
  const progressBarEl = $("progress-bar");
  const speechStatusEl = $("speech-status");
  const speechNoteEl = $("speech-note");
  const modelListEl = $("model-list");
  const downloadNoteEl = $("download-note");
  const expandedModels = new Set();
  const downloadBars = new Map(); // id модели → {bar, text} в её карточке
  const STATUS_TEXT = {
    no_model: "Модель ещё не скачана. Нажмите на модель ниже — она скачается и включится",
    listening: "Модель работает",
    mic_error: "Модель загружена, но микрофон не открылся",
    error: "Ошибка распознавания, подробности в консоли приложения. Нажмите на модель, чтобы перезапустить",
    stopped: "Распознавание остановлено",
  };
  let renderedModelsKey = "";

  function formatMB(bytes) {
    const mb = bytes / 1024 / 1024;
    return mb >= 1024 ? `${(mb / 1024).toFixed(1).replace(".", ",")} ГБ` : `${Math.round(mb)} МБ`;
  }

  function downloadText(download) {
    if (download.status === "extracting") return "Распаковка…";
    const done = formatMB(download.done_bytes);
    if (!download.total_bytes) return `Скачано ${done}`;
    return `Скачано ${done} из ${formatMB(download.total_bytes)} · ${Math.round(download.progress * 100)}%`;
  }

  function modelCard(m, current, failed) {
    const card = el("div", "model-card");
    const download = m.download;
    const active = download && download.status !== "error"; // качается или распаковывается
    // Модель «выбрана», только когда скачана: до этого работает прежняя (или никакая).
    const selected = m.id === current && m.installed;
    if (selected) card.classList.add("current");
    if (active) card.classList.add("downloading");

    const pick = el("button", "model-pick");
    pick.type = "button";
    const title = el("span", "title", m.title);
    title.append(el("span", "model-name", ` (${m.name})`));
    if (selected) title.append(el("span", "badge", "выбрана"));
    else if (active) title.append(el("span", "badge", "скачивается"));
    else if (!m.installed) title.append(el("span", "badge", `не скачана · ${m.download_size}`));
    pick.append(title, el("span", "summary", m.summary));
    // Нескачанная модель по клику скачивается; упавшую можно перезапустить кликом по ней же.
    if (!active && (!m.installed || !selected || failed)) pick.addEventListener("click", () => chooseModel(m));
    else pick.setAttribute("aria-disabled", "true");

    const details = el("div", "model-details");
    details.id = `model-details-${m.id}`;
    details.hidden = !expandedModels.has(m.id);
    details.append(
      el("p", "", m.description),
      el("p", "specs", `Размер на диске: ${m.disk} · в памяти: ${m.memory}`),
      el("p", "specs", `Загрузка в память при запуске: ${m.load_time}`)
    );
    if (!m.installed) {
      const hint = el("p", "specs", `Нажмите на модель, чтобы скачать её (${m.download_size}). Или скачайте `);
      const link = el("a", "", "архив");
      link.href = m.url;
      hint.append(link, " вручную и распакуйте в папку models/ рядом с программой.");
      details.append(hint);
    }

    const expand = el("button", "model-expand");
    expand.type = "button";
    expand.title = "Подробнее";
    expand.setAttribute("aria-controls", details.id);
    expand.setAttribute("aria-expanded", String(!details.hidden));
    expand.addEventListener("click", () => {
      details.hidden = !details.hidden;
      expand.setAttribute("aria-expanded", String(!details.hidden));
      if (details.hidden) expandedModels.delete(m.id);
      else expandedModels.add(m.id);
    });

    const head = el("div", "model-head");
    head.append(pick, expand);
    card.append(head);

    if (active) {
      const box = el("div", "model-download");
      const progress = el("div", "progress");
      const bar = el("div", "progress-bar");
      progress.append(bar);
      const row = el("div", "row download-row");
      const text = el("span", "download-text");
      const cancel = el("button", "secondary-btn small-btn", "Отменить");
      cancel.type = "button";
      cancel.addEventListener("click", () => cancelDownload(m.id, cancel));
      row.append(text, cancel);
      box.append(progress, row);
      card.append(box);
      downloadBars.set(m.id, { bar, text });
    } else if (download && download.status === "error") {
      card.append(el("div", "model-download status-line error", `${download.error}. Нажмите на модель, чтобы попробовать ещё раз`));
    }
    card.append(details);
    return card;
  }

  function showModels(state, loading) {
    $("model-section").hidden = false;
    // Перерисовываем только при изменениях: опрос идёт раз в секунду.
    const failed = state.status === "error";
    // Байты скачивания в ключ не входят: полосы обновляются на месте, без перерисовки карточек.
    const key = JSON.stringify([
      state.models.map((m) => [m.id, m.installed, m.download && m.download.status, m.download && m.download.error]),
      state.model,
      failed,
    ]);
    if (key !== renderedModelsKey) {
      renderedModelsKey = key;
      downloadBars.clear();
      modelListEl.replaceChildren(...state.models.map((m) => modelCard(m, state.model, failed)));
    }
    for (const m of state.models) {
      const shown = downloadBars.get(m.id);
      if (!shown || !m.download) continue;
      shown.bar.style.width = `${Math.round(m.download.progress * 100)}%`;
      shown.text.textContent = downloadText(m.download);
    }
    const downloading = state.models.find((m) => m.download && m.download.status !== "error");
    downloadNoteEl.hidden = !downloading;
    if (downloading) {
      downloadNoteEl.textContent =
        `Модель «${downloading.title}» ещё не была скачана — скачиваю её (${downloading.download_size}). ` +
        (downloading.id === state.wanted ? "Когда скачается, она включится сама. " : "") +
        "Страницу можно закрыть: скачивание идёт в приложении.";
    }
    progressEl.hidden = !loading;
    speechNoteEl.hidden = !loading;
    const percent = Math.round(state.progress * 100);
    progressBarEl.style.width = `${percent}%`;
    const model = state.models.find((m) => m.id === state.model);
    const title = model ? `${model.title} (${model.name})` : state.model;
    setStatus(
      speechStatusEl,
      loading ? `Загрузка модели «${title}» в память… ${percent}%` : STATUS_TEXT[state.status] || state.status,
      state.status === "error",
      state.status === "listening"
    );
  }

  async function chooseModel(m) {
    if (!m.installed) {
      setStatus(speechStatusEl, `Модель «${m.title}» не скачана — начинаю скачивание (${m.download_size})…`);
    } else {
      // Новая загрузка: полоса сразу с нуля, без анимации назад.
      progressBarEl.style.transition = "none";
      progressBarEl.style.width = "0";
      void progressBarEl.offsetWidth;
      progressBarEl.style.transition = "";
    }
    try {
      showSpeech(await api("POST", "/api/speech/model", { model: m.id }));
    } catch (e) {
      setStatus(speechStatusEl, e.message, true);
    }
  }

  async function cancelDownload(id, button) {
    button.disabled = true;
    try {
      showSpeech(await api("DELETE", `/api/speech/download/${encodeURIComponent(id)}`));
    } catch (e) {
      setStatus(speechStatusEl, e.message, true);
      button.disabled = false;
    }
  }

  // --- Обновления программы ---

  let updateState = null;

  function showUpdate(state) {
    updateState = state;
    $("update-section").hidden = false;
    const action = $("update-action");
    const status = $("update-status");
    const latest = state.latest ? `v${state.latest}` : "";
    const loading = state.status === "downloading" || state.status === "extracting";
    const found = ["available", "downloading", "extracting", "ready"].includes(state.status) ||
      (state.status === "error" && state.latest);

    const badge = $("update-badge");
    badge.hidden = !found;
    badge.textContent = `Доступна ${latest}`;

    $("update-progress").hidden = !loading;
    $("update-progress-bar").style.width = `${Math.round(state.progress * 100)}%`;
    $("update-cancel").hidden = state.status !== "downloading";
    $("update-auto").checked = state.auto;
    $("update-notes").hidden = !found || !state.notes;
    $("update-notes-text").textContent = state.notes || "";

    action.hidden = loading;
    action.disabled = state.status === "checking";
    if (state.status === "ready") action.textContent = "Перезапустить и обновить";
    else if (found && state.can_install) action.textContent = "Скачать и установить";
    else action.textContent = "Проверить обновления";

    if (state.status === "checking") setStatus(status, "Проверяю…");
    else if (state.status === "none") setStatus(status, `У вас последняя версия: v${state.current}`, false, true);
    else if (state.status === "error") setStatus(status, state.error, true);
    else if (state.status === "downloading") {
      const total = state.size ? ` из ${formatMB(state.size)}` : "";
      setStatus(status, `Скачиваю ${latest}: ${Math.round(state.progress * 100)}%${total}`);
    } else if (state.status === "extracting") setStatus(status, "Распаковываю…");
    else if (state.status === "ready") setStatus(status, `${latest} скачана. Программа перезапустится в новой версии.`);
    else if (found) {
      setStatus(status, state.can_install
        ? `Доступна новая версия ${latest} (у вас v${state.current}).`
        : `Доступна ${latest}. Из исходников обновитесь через git pull.`);
    } else setStatus(status, `Версия v${state.current}`);
  }

  async function updateCall(method, url, body) {
    try {
      showUpdate(await api(method, url, body));
    } catch (e) {
      setStatus($("update-status"), e.message, true);
    }
  }

  $("update-action").addEventListener("click", () => {
    const s = updateState;
    if (!s) return;
    const found = s.latest && s.status !== "none";
    if (s.status === "ready") updateCall("POST", "/api/update/apply");
    else if (found && s.can_install) updateCall("POST", "/api/update/download");
    else updateCall("POST", "/api/update/check");
  });
  $("update-cancel").addEventListener("click", () => updateCall("DELETE", "/api/update/download"));
  $("update-auto").addEventListener("change", (e) =>
    updateCall("POST", "/api/update/auto", { enabled: e.target.checked }));

  // --- Что считать: списки слов из папки wordlists ---

  const wordListEl = $("word-list");
  const wordsStatusEl = $("words-status");
  const wordsRefreshBtn = $("words-refresh");

  function plural(n, one, few, many) {
    const mod10 = n % 10, mod100 = n % 100;
    if (mod10 === 1 && mod100 !== 11) return one;
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return few;
    return many;
  }

  function showWords(state) {
    $("words-section").hidden = false;
    const options = state.lists.map(
      (list) => new Option(`${list.name} — ${list.words} ${plural(list.words, "корень", "корня", "корней")}`, list.id)
    );
    wordListEl.replaceChildren(...options);
    wordListEl.value = state.active;
    const empty = !state.lists.length;
    $("words-edit").disabled = empty;
    setStatus(wordsStatusEl, empty ? "В папке нет ни одного списка" : "", empty);
  }

  async function loadWords() {
    wordsRefreshBtn.disabled = true;
    try {
      showWords(await api("GET", "/api/words"));
    } catch (e) {
      // нет связи с сервером: список обновится при переподключении
    } finally {
      wordsRefreshBtn.disabled = false;
    }
  }

  async function openWords(id) {
    try {
      showWords(await api("POST", "/api/words/open", { id }));
    } catch (e) {
      setStatus(wordsStatusEl, e.message, true);
    }
  }

  wordsRefreshBtn.addEventListener("click", loadWords);
  // Списки правят в Блокноте: вернулись в окно — показываем свежие названия и число корней.
  window.addEventListener("focus", loadWords);
  wordListEl.addEventListener("change", async () => {
    try {
      showWords(await api("POST", "/api/words/active", { id: wordListEl.value }));
    } catch (e) {
      setStatus(wordsStatusEl, e.message, true);
      loadWords();
    }
  });
  $("words-edit").addEventListener("click", () => openWords(wordListEl.value));
  $("words-folder").addEventListener("click", () => openWords(null));

  // --- WebSocket: счёт, звук, оформление и уровень микрофона ---

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onopen = () => {
      setOnline(true);
      refreshSpeech();
      loadDevices();
      loadWords();
      api("GET", "/api/version").then(({ version }) => ($("version").textContent = `v${version}`), () => {});
      api("GET", "/api/update").then(showUpdate, () => {});
    };
    ws.onmessage = (event) => {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch (e) {
        return;
      }
      if (msg.type === "mic_level") targetLevel = Math.max(targetLevel, levelToPosition(msg.level));
      else if (msg.type === "sound") showSound(msg);
      else if (msg.type === "update") showUpdate(msg);
      else if (msg.type === "style") {
        showServerPreset(msg.preset);
        showServerLabel(msg.label, msg.label_position);
      }
      else if (msg.count !== undefined) countEl.textContent = msg.count;
    };
    ws.onclose = () => {
      setOnline(false);
      setTimeout(connect, 2000);
    };
    ws.onerror = () => ws.close();
  }
  connect();
})();
