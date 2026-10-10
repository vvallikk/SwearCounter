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
    const resp = await fetch(url, init);
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
    if (loading || state.mic_pending) speechTimer = setTimeout(refreshSpeech, 1000);
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
    play.addEventListener("click", () => player.preview(id));
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
    const key = JSON.stringify([state.sounds, state.active]);
    if (key !== renderedSoundsKey) {
      renderedSoundsKey = key;
      soundListEl.replaceChildren(
        soundItem(null, "Стандартный звон", state.active === null),
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
  const presetGridEl = $("preset-grid");
  const presetCards = new Map();

  function buildPresets() {
    for (const preset of presets) {
      const card = el("button", "preset-card");
      card.type = "button";
      const frame = document.createElement("iframe");
      frame.src = `/overlay/?preview=1&preset=${encodeURIComponent(preset.id)}&size=34`;
      frame.title = `Превью: ${preset.title}`;
      frame.tabIndex = -1;
      frame.loading = "lazy";
      const text = el("span", "text");
      text.append(el("span", "title", preset.title), el("span", "desc", preset.description));
      card.append(frame, text);
      card.addEventListener("click", () => choosePreset(preset.id));
      presetCards.set(preset.id, card);
      presetGridEl.append(card);
    }
  }

  function showPreset(id) {
    if (presets.length === 0) return;
    $("preset-section").hidden = false;
    for (const [presetId, card] of presetCards) {
      card.classList.toggle("current", presetId === id);
      card.setAttribute("aria-pressed", String(presetId === id));
    }
  }

  async function choosePreset(id) {
    showPreset(id); // сразу, не дожидаясь сервера
    try {
      showPreset((await api("POST", "/api/overlay/preset", { preset: id })).preset);
    } catch (e) {
      setOnline(false);
    }
  }

  buildPresets();

  // --- Модель распознавания: карточки, выбор кликом, описание раскрывается ---

  const progressEl = $("progress");
  const progressBarEl = $("progress-bar");
  const speechStatusEl = $("speech-status");
  const speechNoteEl = $("speech-note");
  const modelListEl = $("model-list");
  const expandedModels = new Set();
  const STATUS_TEXT = {
    listening: "Модель работает",
    mic_error: "Модель загружена, но микрофон не открылся",
    error: "Ошибка распознавания, подробности в консоли приложения. Нажмите на модель, чтобы перезапустить",
    stopped: "Распознавание остановлено",
  };
  let renderedModelsKey = "";

  function modelCard(m, current, failed) {
    const card = el("div", "model-card");
    if (m.id === current) card.classList.add("current");
    if (!m.installed) card.classList.add("unavailable");

    const pick = el("button", "model-pick");
    pick.type = "button";
    const title = el("span", "title", m.title);
    title.append(el("span", "model-name", ` (${m.name})`));
    if (m.id === current) title.append(el("span", "badge", "выбрана"));
    else if (!m.installed) title.append(el("span", "badge", "не скачана"));
    pick.append(title, el("span", "summary", m.summary));
    // Упавшую модель можно перезапустить кликом по её же карточке.
    if (m.installed && (m.id !== current || failed)) pick.addEventListener("click", () => chooseModel(m.id));
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
      const hint = el("p", "specs", "Скачайте ");
      const link = el("a", "", "архив");
      link.href = m.url;
      hint.append(link, " и распакуйте его в папку models/");
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
    card.append(head, details);
    return card;
  }

  function showModels(state, loading) {
    $("model-section").hidden = false;
    // Перерисовываем только при изменениях: опрос идёт раз в секунду.
    const failed = state.status === "error";
    const key = JSON.stringify([state.models, state.model, failed]);
    if (key !== renderedModelsKey) {
      renderedModelsKey = key;
      modelListEl.replaceChildren(...state.models.map((m) => modelCard(m, state.model, failed)));
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

  async function chooseModel(id) {
    // Новая загрузка: полоса сразу с нуля, без анимации назад.
    progressBarEl.style.transition = "none";
    progressBarEl.style.width = "0";
    void progressBarEl.offsetWidth;
    progressBarEl.style.transition = "";
    try {
      showSpeech(await api("POST", "/api/speech/model", { model: id }));
    } catch (e) {
      setStatus(speechStatusEl, e.message, true);
    }
  }

  // --- WebSocket: счёт, звук, оформление и уровень микрофона ---

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onopen = () => {
      setOnline(true);
      refreshSpeech();
      loadDevices();
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
      else if (msg.type === "style") showPreset(msg.preset);
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
