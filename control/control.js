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

  // --- Вкладки: открывается последняя (или та, что в адресе: #settings) ---

  const tabButtons = [...document.querySelectorAll(".tab")];
  const TABS = tabButtons.map((b) => b.dataset.tab);

  function selectTab(name, focus) {
    if (!TABS.includes(name)) return;
    for (const button of tabButtons) {
      const selected = button.dataset.tab === name;
      button.setAttribute("aria-selected", String(selected));
      button.tabIndex = selected ? 0 : -1;
      $(`tab-${button.dataset.tab}`).hidden = !selected;
      if (selected && focus) button.focus();
    }
    try {
      localStorage.setItem("tab", name);
    } catch (e) {
      // без хранилища просто не запомним
    }
    if (location.hash && location.hash !== `#${name}`) history.replaceState(null, "", location.pathname + location.search);
    document.dispatchEvent(new CustomEvent("tabchange", { detail: name }));
  }

  function savedTab() {
    try {
      return localStorage.getItem("tab");
    } catch (e) {
      return null;
    }
  }

  for (const button of tabButtons) {
    button.addEventListener("click", () => {
      selectTab(button.dataset.tab);
      // Новая вкладка открывается с начала, а не посередине прошлой.
      if (window.scrollY > 0) window.scrollTo(0, 0);
    });
    button.addEventListener("keydown", (event) => {
      const here = TABS.indexOf(button.dataset.tab);
      let index = null;
      if (event.key === "ArrowRight") index = (here + 1) % TABS.length;
      else if (event.key === "ArrowLeft") index = (here - 1 + TABS.length) % TABS.length;
      else if (event.key === "Home") index = 0;
      else if (event.key === "End") index = TABS.length - 1;
      if (index === null) return;
      event.preventDefault();
      selectTab(TABS[index], true);
    });
  }
  const hashTab = location.hash.slice(1);
  selectTab(TABS.includes(hashTab) ? hashTab : TABS.includes(savedTab()) ? savedTab() : "counter");
  window.addEventListener("hashchange", () => selectTab(location.hash.slice(1)));

  // Показывает раздел на вкладке настроек и прокручивает к нему.
  function showInSettings(node) {
    selectTab("settings");
    if (window.setSectionOpen) window.setSectionOpen(node, true);
    node.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  $("update-badge").addEventListener("click", (event) => {
    event.preventDefault();
    showInSettings($("update-section"));
  });

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

  // Показывает счёт: число «подпрыгивает» на каждом новом слове.
  let shownCount = null;

  function showCount(value) {
    if (typeof value !== "number") return;
    const grew = shownCount !== null && value > shownCount;
    countEl.textContent = value;
    countEl.classList.toggle("long", value >= 1000 && value < 10000);
    countEl.classList.toggle("huge", value >= 10000);
    if (grew) {
      countEl.classList.remove("bump");
      void countEl.offsetWidth; // перезапуск анимации
      countEl.classList.add("bump");
    }
    shownCount = value;
    currentCount = value;
  }

  function setOnline(online) {
    document.body.classList.toggle("offline", !online);
    dotEl.classList.toggle("online", online);
    statusEl.textContent = online ? "Подключено" : "Нет связи с сервером";
  }

  async function post(url, button) {
    button.disabled = true;
    try {
      showCount((await api("POST", url)).count);
    } catch (e) {
      setOnline(false);
    } finally {
      button.disabled = false;
    }
  }

  incBtn.addEventListener("click", () => post("/api/increment", incBtn));

  const pauseBtn = $("pause");
  let paused = false;

  function showPause(on) {
    paused = on;
    pauseBtn.setAttribute("aria-pressed", String(on));
    pauseBtn.textContent = on ? "▶ Продолжить" : "⏸ Пауза";
    pauseBtn.title = on ? "Снова считать сказанное" : "Не считать сказанное: на перерыв, катсцену или чужой голос";
    countEl.classList.toggle("paused", on);
    $("pause-note").hidden = !on;
    if (on) targetLevel = 0;
  }

  pauseBtn.addEventListener("click", async () => {
    pauseBtn.disabled = true;
    try {
      showPause((await api("POST", "/api/pause", { paused: !paused })).paused);
    } catch (e) {
      setOnline(false);
    } finally {
      pauseBtn.disabled = false;
    }
  });
  confirmByTwoClicks(resetBtn, "Точно сбросить?", () => post("/api/reset", resetBtn));

  // --- Адрес оверлея копируется по клику ---

  const overlayUrl = `${location.origin}/overlay/`;
  const timerOverlayUrl = `${overlayUrl}?show=timer`;
  const goalOverlayUrl = `${overlayUrl}?show=goal`;
  $("overlay-url-text").textContent = overlayUrl;
  $("timer-url-text").textContent = timerOverlayUrl;
  $("goal-url-text").textContent = goalOverlayUrl;

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

  function bindCopyLink(button, url) {
    const label = button.querySelector(".copy-label");
    let copiedTimer = null;
    button.addEventListener("click", async () => {
      const ok = await copyText(url);
      button.classList.toggle("copied", ok);
      label.textContent = ok ? "Скопировано ✓" : "Не удалось скопировать";
      clearTimeout(copiedTimer);
      copiedTimer = setTimeout(() => {
        button.classList.remove("copied");
        label.textContent = "Копировать";
      }, 2000);
    });
  }
  bindCopyLink($("overlay-url"), overlayUrl);
  bindCopyLink($("timer-url"), timerOverlayUrl);
  bindCopyLink($("goal-url"), goalOverlayUrl);

  // --- Дополнительные счётчики: свой список слов, счёт и оверлей (?counter=<id>) ---

  const MAX_COUNTERS = 5;
  const countersListEl = $("counters-list");
  const countersStatusEl = $("counters-status");
  let extraCounters = [];
  let wordLists = []; // приходят вместе со списками слов (showWords)
  const openCounters = new Set(); // у каких счётчиков раскрыты настройки

  async function counterRequest(method, url, body) {
    try {
      const result = await api(method, url, body);
      if (result.counters) showCounters(result.counters);
      setStatus(countersStatusEl, "");
      return result;
    } catch (e) {
      setStatus(countersStatusEl, e.message, true);
      return null;
    }
  }

  function counterSetting(counter, label, control) {
    const row = el("label", "row counter-setting", label);
    row.append(control);
    return row;
  }

  function renderCounter(counter) {
    const details = el("details", "counter-item");
    details.open = openCounters.has(counter.id);
    details.addEventListener("toggle", () => {
      if (details.open) openCounters.add(counter.id);
      else openCounters.delete(counter.id);
    });
    const summary = el("summary", "counter-head");
    const count = el("b", "counter-count", String(counter.count));
    count.dataset.counter = counter.id;
    const inc = el("button", "secondary-btn", "+1");
    inc.type = "button";
    inc.addEventListener("click", (e) => {
      e.preventDefault(); // кнопка внутри summary не раскрывает настройки
      counterRequest("POST", `/api/counters/${counter.id}/increment`);
    });
    const reset = el("button", "secondary-btn", "Сбросить");
    reset.type = "button";
    reset.addEventListener("click", (e) => e.preventDefault());
    confirmByTwoClicks(reset, "Точно?", () => counterRequest("POST", `/api/counters/${counter.id}/reset`));
    summary.append(el("span", "counter-name", counter.name), count, inc, reset);

    const body = el("div", "counter-body");
    const list = el("select");
    list.append(...listOptions(wordLists));
    if (!wordLists.some((l) => l.id === counter.list)) list.prepend(new Option(`${counter.list} (нет файла)`, counter.list));
    list.value = counter.list;
    list.addEventListener("change", () => counterRequest("POST", `/api/counters/${counter.id}`, { list: list.value }));
    const preset = el("select");
    preset.append(...presets.map((p) => new Option(p.title, p.id)));
    if (!presets.some((p) => p.id === counter.preset)) preset.prepend(new Option(counter.preset, counter.preset));
    preset.value = counter.preset;
    preset.addEventListener("change", () => counterRequest("POST", `/api/counters/${counter.id}`, { preset: preset.value }));
    const label = el("input", "text-input");
    label.maxLength = 40;
    label.value = counter.label;
    label.placeholder = "без подписи";
    label.addEventListener("change", () => counterRequest("POST", `/api/counters/${counter.id}`, { label: label.value }));
    const wrap = (select) => {
      const node = el("div", "select-wrap");
      node.append(select);
      return node;
    };

    const url = `${overlayUrl}?counter=${counter.id}`;
    const link = el("button", "copy-link");
    link.type = "button";
    link.title = "Нажмите, чтобы скопировать";
    link.append(el("span", "", url), el("span", "copy-label", "Копировать"));
    bindCopyLink(link, url);
    const remove = el("button", "secondary-btn", "Удалить счётчик");
    remove.type = "button";
    confirmByTwoClicks(remove, "Точно удалить?", () => counterRequest("DELETE", `/api/counters/${counter.id}`));

    body.append(
      counterSetting(counter, "Список слов", wrap(list)),
      counterSetting(counter, "Оформление", wrap(preset)),
      counterSetting(counter, "Подпись", label),
      el("div", "note", "Оверлей этого счётчика:"),
      link,
      remove,
    );
    details.append(summary, body);
    return details;
  }

  function renderCounters() {
    // Пока что-то редактируют, список не перерисовываем: сбросился бы ввод.
    if (countersListEl.contains(document.activeElement) && document.activeElement.matches("input, select")) return;
    countersListEl.replaceChildren(...extraCounters.map(renderCounter));
    const addList = $("counter-list");
    const chosen = addList.value;
    addList.replaceChildren(...listOptions(wordLists));
    if (chosen) addList.value = chosen;
    $("counter-add").hidden = extraCounters.length >= MAX_COUNTERS || !wordLists.length;
    $("counters-section").hidden = !wordLists.length;
  }

  function showCounters(counters) {
    extraCounters = counters;
    renderCounters();
  }

  function showExtraCount(msg) {
    const counter = extraCounters.find((c) => c.id === msg.id);
    if (counter) counter.count = msg.count;
    const node = countersListEl.querySelector(`[data-counter="${CSS.escape(msg.id)}"]`);
    if (node) node.textContent = msg.count;
  }

  $("counter-add").addEventListener("submit", async (event) => {
    event.preventDefault();
    const result = await counterRequest("POST", "/api/counters", {
      name: $("counter-name").value,
      list: $("counter-list").value,
    });
    if (result) $("counter-name").value = "";
  });

  // --- Цели: особые числа и отсчёт «осталось N» ---

  const milestonesEl = $("milestones");
  const goalEl = $("goal");
  const goalsStatusEl = $("goals-status");
  let goalsState = { milestones: [], goal: 0 };
  let currentCount = 0;

  function renderGoalLeft() {
    $("goal-line").hidden = !goalsState.goal;
    $("goal-links").hidden = !goalsState.goal;
    $("goal-left").textContent = Math.max(goalsState.goal - currentCount, 0);
  }

  function showGoals(state) {
    goalsState = state;
    $("goals-section").hidden = false;
    if (document.activeElement !== milestonesEl) milestonesEl.value = state.milestones.join(", ");
    if (document.activeElement !== goalEl) goalEl.value = state.goal || "";
    renderGoalLeft();
  }

  async function saveGoals() {
    const parts = milestonesEl.value.split(/[\s,;]+/).filter(Boolean);
    if (parts.some((part) => !/^\d+$/.test(part))) {
      setStatus(goalsStatusEl, "Особые числа — целые числа через запятую", true);
      return;
    }
    if (goalEl.value !== "" && !/^\d+$/.test(goalEl.value)) {
      setStatus(goalsStatusEl, "Цель — целое число; пустое поле — без цели", true);
      return;
    }
    try {
      const state = await api("POST", "/api/goals", { milestones: parts.map(Number), goal: Number(goalEl.value) });
      showGoals(state);
      milestonesEl.value = state.milestones.join(", ");
      goalEl.value = state.goal || "";
      setStatus(goalsStatusEl, "Сохранено", false, true);
    } catch (e) {
      setStatus(goalsStatusEl, e.message, true);
    }
  }
  milestonesEl.addEventListener("change", saveGoals);
  goalEl.addEventListener("change", saveGoals);

  // --- Статистика по сессиям ---

  const statsStatusEl = $("stats-status");
  let statsTimer = null;

  function pluralize(n, one, few, many) {
    const d = n % 10, dd = n % 100;
    if (d === 1 && dd !== 11) return one;
    if (d >= 2 && d <= 4 && (dd < 12 || dd > 14)) return few;
    return many;
  }

  function showStats(state) {
    $("stats-section").hidden = false;
    const chart = $("stats-chart");
    chart.replaceChildren();
    const max = Math.max(1, ...state.sessions.map((s) => s.count));
    for (const s of state.sessions) {
      const bar = el("div", "stats-bar");
      bar.style.height = `${(s.count / max) * 100}%`;
      const start = new Date(s.start * 1000);
      const date = start.toLocaleString(document.documentElement.lang, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
      bar.title = `${date} · ${formatDuration(s.end - s.start)} · ${s.count} ${pluralize(s.count, "слово", "слова", "слов")}`;
      chart.append(bar);
    }
    const n = state.session_count;
    let text = n
      ? `${n} ${pluralize(n, "сессия", "сессии", "сессий")} · всего ${state.total} ${pluralize(state.total, "слово", "слова", "слов")}`
      : "Пока пусто: сессия начинается с первого слова после запуска или сброса.";
    if (state.top.length) text += ` · чаще всего: ${state.top.slice(0, 5).map(([w, c]) => `${w} ${c}`).join(", ")}`;
    $("stats-summary").textContent = text;
    $("stats-export").disabled = $("stats-clear").disabled = !n;
  }

  async function loadStats() {
    try {
      showStats(await api("GET", "/api/stats"));
    } catch (e) {
      // Старый сервер без статистики — раздел просто не показываем.
    }
  }

  // Счёт меняется часто: статистику перечитываем не чаще раза в пару секунд.
  function refreshStatsSoon() {
    if (statsTimer === null) statsTimer = setTimeout(() => { statsTimer = null; loadStats(); }, 2000);
  }

  $("stats-export").addEventListener("click", async () => {
    try {
      const { path } = await api("POST", "/api/stats/export");
      setStatus(statsStatusEl, `Сохранено: ${path}`, false, true);
    } catch (e) {
      setStatus(statsStatusEl, e.message, true);
    }
  });
  confirmByTwoClicks($("stats-clear"), "Точно очистить?", async () => {
    try {
      showStats(await api("DELETE", "/api/stats"));
      setStatus(statsStatusEl, "");
    } catch (e) {
      setStatus(statsStatusEl, e.message, true);
    }
  });

  // --- Таймер «без мата»: сервер присылает состояние, секунды отсчитываем здесь ---

  let timerState = { elapsed: 0, record: 0, running: false, at: performance.now() };

  function formatDuration(seconds) {
    const total = Math.floor(seconds);
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = String(total % 60).padStart(2, "0");
    return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
  }

  function renderTimer() {
    const now = timerState.elapsed + (timerState.running ? (performance.now() - timerState.at) / 1000 : 0);
    $("timer-now").textContent = formatDuration(now);
    $("timer-record").textContent = formatDuration(Math.max(timerState.record, now));
  }

  function showTimer(msg) {
    timerState = { elapsed: msg.elapsed, record: msg.record, running: msg.running, at: performance.now() };
    renderTimer();
  }
  setInterval(() => {
    if (!document.hidden) renderTimer();
  }, 1000);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) renderTimer();
  });

  // Предпросмотр оверлея: окно программы не открывает вкладки, поэтому браузер запускает сервер.
  function bindOpen(button, show, fallbackUrl) {
    button.addEventListener("click", () => {
      // Если программа не ответила (страница открыта не из неё), откроем вкладку сами.
      const path = show ? `/api/overlay/open?show=${show}` : "/api/overlay/open";
      api("POST", path).catch(() => window.open(fallbackUrl, "_blank"));
    });
  }
  bindOpen($("overlay-open"), "", overlayUrl);
  bindOpen($("timer-open"), "timer", timerOverlayUrl);
  bindOpen($("goal-open"), "goal", goalOverlayUrl);

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
    else if (state.status === "no_key") text = "Микрофон откроется, когда будет введён API-ключ";
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

  // Кадры рисуются, только пока есть сигнал; тишина и скрытая вкладка ничего не стоят.
  // Шкала двигается через transform (композитор), а не через width (раскладка).
  let meterFrame = 0;
  let drawnLevel = -1;

  function drawMeter() {
    meterFrame = 0;
    shownLevel = targetLevel > shownLevel ? targetLevel : shownLevel * 0.88;
    targetLevel *= 0.8;
    if (shownLevel < 0.004 && targetLevel < 0.004) shownLevel = targetLevel = 0;
    if (Math.abs(shownLevel - drawnLevel) > 0.003 || shownLevel === 0) {
      drawnLevel = shownLevel;
      meterMaskEl.style.transform = `scaleX(${1 - shownLevel})`;
    }
    if (shownLevel > 0 || targetLevel > 0) meterFrame = requestAnimationFrame(drawMeter);
  }

  function wakeMeter() {
    if (!meterFrame) meterFrame = requestAnimationFrame(drawMeter);
  }

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
  let standardSoundName = "Стандартный звон";
  const STANDARD_NAMES = { ding: "Стандартный звон" };

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
    const key = JSON.stringify([state.sounds, state.active, standardSound, standardSoundName]);
    if (key !== renderedSoundsKey) {
      renderedSoundsKey = key;
      soundListEl.replaceChildren(
        soundItem(null, standardSoundName, state.active === null),
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

  // Встроенные пресеты и личные оформления из /api/presets/custom (папка presets/ рядом с программой)
  const builtinPresets = (window.OVERLAY_PRESETS || []).slice();
  let presets = builtinPresets;
  const presetEl = $("preset");
  const presetPreviewEl = $("preset-preview");
  const presetDescEl = $("preset-desc");
  const presetOwnerEl = $("preset-owner");
  const presetStatusEl = $("preset-status");
  const presetInput = $("preset-input");
  const presetInstallBtn = $("preset-install");
  const presetRemoveBtn = $("preset-remove");
  const presetExportBtn = $("preset-export");
  const presetLinkToggle = $("preset-link-toggle");
  const presetLinkForm = $("preset-link-form");
  const presetLinkEl = $("preset-link");
  const presetLinkBtn = $("preset-link-install");
  const MAX_PACK_MB = 20;
  let shownPreset = null;
  let wantedPreset = null; // id, который просили показать: личное оформление могло ещё не загрузиться
  let presetRequests = 0; // сколько выборов ещё не подтвердил сервер

  function renderPresetOptions() {
    const custom = presets.filter((p) => p.custom);
    const options = builtinPresets.map((p) => new Option(p.title, p.id));
    if (custom.length) {
      const group = el("optgroup");
      group.label = "Личные оформления";
      group.append(...custom.map((p) => new Option(p.title, p.id)));
      options.push(group);
    }
    presetEl.replaceChildren(...options);
    if (shownPreset) presetEl.value = shownPreset;
  }
  renderPresetOptions();

  async function loadCustomPresets() {
    let custom;
    try {
      custom = await api("GET", "/api/presets/custom");
    } catch (e) {
      return; // сервер старее страницы или недоступен: остаются встроенные
    }
    const changed = JSON.stringify(custom) !== JSON.stringify(presets.filter((p) => p.custom));
    presets = builtinPresets.concat(custom);
    renderPresetOptions();
    renderCounters();
    if (wantedPreset !== null) showPreset(wantedPreset);
    // В превью наборы подключаются при загрузке страницы оверлея: после изменений перезагружаем его,
    // выбранное оформление превью получит заново по событию load (sendPreviewStyle).
    // Именно src заново, а не contentWindow.location.reload(): пока iframe грузится,
    // в нём ещё about:blank, и reload перезагрузил бы пустую страницу вместо превью.
    if (changed && presetPreviewEl.getAttribute("src")) presetPreviewEl.src = presetPreviewEl.getAttribute("src");
  }

  // Превью загружается один раз, а стиль в нём меняется сообщением. Если бы iframe
  // перезагружался на каждую смену, при быстром переключении превью могло пропасть.
  function sendPreviewStyle() {
    const win = presetPreviewEl.contentWindow;
    if (!win || !shownPreset) return;
    const message = {
      type: "style",
      preset: shownPreset,
      label: labelTextEl.value.trim(),
      label_position: labelPositionEl.value,
      visible: !$("tab-look").hidden, // на скрытой вкладке превью не анимируется
    };
    win.postMessage(message, location.origin);
  }
  presetPreviewEl.addEventListener("load", sendPreviewStyle);
  document.addEventListener("tabchange", sendPreviewStyle);

  function showPreset(id) {
    wantedPreset = id;
    const preset = presets.find((p) => p.id === id) || presets[0];
    if (!preset) return;
    $("preset-section").hidden = false;
    presetEl.value = preset.id;
    presetDescEl.textContent = preset.description;
    presetOwnerEl.textContent = preset.owner ? `Личное оформление для: ${preset.owner}` : "";
    presetOwnerEl.hidden = !preset.owner;
    presetRemoveBtn.hidden = !preset.custom;
    presetExportBtn.hidden = !preset.custom;
    if (preset.custom && preset.sound) {
      standardSound = preset.sound; // адрес звука из набора
      standardSoundName = `Звук оформления «${preset.title}»`;
    } else {
      standardSound = STANDARD_NAMES[preset.sound] ? preset.sound : "ding";
      standardSoundName = STANDARD_NAMES[standardSound];
    }
    player.setStandard(standardSound);
    if (soundState) showSound(soundState);
    if (shownPreset === preset.id) return;
    const first = shownPreset === null;
    shownPreset = preset.id;
    // Без ?size число в превью подгоняется под рамку, как в OBS.
    if (first) presetPreviewEl.src = `/overlay/?preview=1&preset=${encodeURIComponent(preset.id)}`;
    else sendPreviewStyle();
  }

  // Ответ сервера на установку: показываем и сразу включаем оформление, ради него и ставили.
  async function finishInstall(resp) {
    const body = await resp.json().catch(() => null);
    if (!resp.ok) {
      setStatus(presetStatusEl, (body && body.detail) || `Ошибка сервера (${resp.status})`, true);
      return false;
    }
    await loadCustomPresets();
    showPreset(body.id);
    presetRequests += 1;
    try {
      await api("POST", "/api/overlay/preset", { preset: body.id });
    } finally {
      presetRequests -= 1;
    }
    setStatus(presetStatusEl, `Оформление «${body.title}» установлено и включено`, false, true);
    return true;
  }

  presetInstallBtn.addEventListener("click", () => presetInput.click());
  presetInput.addEventListener("change", async () => {
    const file = presetInput.files[0];
    presetInput.value = ""; // чтобы тот же архив можно было выбрать ещё раз
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".zip")) {
      return setStatus(presetStatusEl, "Оформление ставится из zip-архива", true);
    }
    if (file.size > MAX_PACK_MB * 1024 * 1024) {
      return setStatus(presetStatusEl, `Архив больше ${MAX_PACK_MB} МБ`, true);
    }
    presetInstallBtn.disabled = true;
    setStatus(presetStatusEl, "Установка…");
    try {
      const resp = await fetch("/api/presets/custom", {
        method: "PUT",
        headers: { "Content-Type": "application/zip" },
        body: file,
      });
      await finishInstall(resp);
    } catch (e) {
      setStatus(presetStatusEl, "Не удалось установить оформление", true);
    } finally {
      presetInstallBtn.disabled = false;
    }
  });

  presetLinkToggle.addEventListener("click", () => {
    presetLinkForm.hidden = !presetLinkForm.hidden;
    if (!presetLinkForm.hidden) presetLinkEl.focus();
  });

  presetLinkForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const url = presetLinkEl.value.trim();
    if (!url) return;
    presetLinkBtn.disabled = true;
    setStatus(presetStatusEl, "Скачивание и установка…");
    try {
      const resp = await fetch("/api/presets/custom/url", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });
      if (await finishInstall(resp)) {
        presetLinkEl.value = "";
        presetLinkForm.hidden = true;
      }
    } catch (e) {
      setStatus(presetStatusEl, "Не удалось установить оформление", true);
    } finally {
      presetLinkBtn.disabled = false;
    }
  });

  presetExportBtn.addEventListener("click", async () => {
    const id = presetEl.value;
    presetExportBtn.disabled = true;
    try {
      const { path } = await api("POST", `/api/presets/custom/${encodeURIComponent(id)}/export`);
      setStatus(presetStatusEl, `Архив сохранён: ${path}`, false, true);
    } catch (e) {
      setStatus(presetStatusEl, e.message, true);
    } finally {
      presetExportBtn.disabled = false;
    }
  });

  confirmByTwoClicks(presetRemoveBtn, "Точно удалить?", async () => {
    const id = presetEl.value;
    try {
      await api("DELETE", `/api/presets/custom/${encodeURIComponent(id)}`);
      setStatus(presetStatusEl, "Оформление удалено");
      await loadCustomPresets(); // выбранное сервер сам сменит на «Классику»
    } catch (e) {
      setStatus(presetStatusEl, e.message, true);
    }
  });

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
    no_model: "Модель ещё не скачана. Скачайте любую модель ниже — она включится сама",
    listening: "Модель работает",
    mic_error: "Модель загружена, но микрофон не открылся",
    no_key: "Для облачной модели нужен API-ключ сервиса: введите его в карточке модели ниже",
    error: "Ошибка распознавания, подробности в консоли приложения. Нажмите на модель, чтобы перезапустить",
    stopped: "Распознавание остановлено",
  };
  let renderedModelsKey = "";
  // Язык речи: показываем модели только этого языка. Сначала — язык выбранной модели.
  const speechLanguageEl = $("speech-language");
  let speechLanguage = null;
  let shownSpeech = null; // последнее состояние, чтобы перерисовать при смене языка

  speechLanguageEl.addEventListener("change", () => {
    speechLanguage = speechLanguageEl.value;
    if (shownSpeech) showModels(...shownSpeech);
  });

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

  // grouped — карточка внутри группы провайдера: заголовок и ключ показаны один раз у группы.
  function modelCard(m, current, failed, grouped = false) {
    const card = el("div", "model-card");
    const download = m.download;
    const active = download && download.status !== "error"; // качается или распаковывается
    // Модель «выбрана», только когда скачана: до этого работает прежняя (или никакая).
    const selected = m.id === current && m.installed;
    if (selected) card.classList.add("current");
    if (active) card.classList.add("downloading");
    if (!m.installed && !active) card.classList.add("missing");

    const pick = el("button", "model-pick");
    pick.type = "button";
    const title = el("span", "title", grouped ? m.name : m.title);
    if (!grouped) title.append(el("span", "model-name", `(${m.name})`));
    if (m.cloud && !grouped) title.append(el("span", "badge cloud", "облако"));
    if (selected) title.append(el("span", "badge", "выбрана"));
    else if (active) title.append(el("span", "badge", "скачивается"));
    else if (!m.installed) title.append(el("span", "badge", `не скачана · ${m.download_size}`));
    pick.append(title, el("span", "summary", m.summary));
    // Включается кликом только скачанная модель; упавшую можно перезапустить кликом по ней же.
    if (!active && m.installed && (!selected || failed)) pick.addEventListener("click", () => chooseModel(m));
    else pick.setAttribute("aria-disabled", "true");

    const details = el("div", "model-details");
    details.id = `model-details-${m.id}`;
    details.hidden = !expandedModels.has(m.id);
    details.append(el("p", "", m.description));
    if (!m.cloud) {
      details.append(
        el("p", "specs", `Размер на диске: ${m.disk} · в памяти: ${m.memory}`),
        el("p", "specs", `Загрузка в память при запуске: ${m.load_time}`)
      );
    }
    if (!m.installed && m.cloud) {
      details.append(el("p", "specs", `Кнопка «Скачать» загружает только детектор речи (${m.download_size}).`));
    } else if (!m.installed) {
      const hint = el("p", "specs", `Скачивается кнопкой «Скачать» (${m.download_size}).`);
      // Вручную предлагаем ставить только модели из одного архива: модель из нескольких
      // файлов проще и надёжнее скачать кнопкой.
      if (m.url && !m.files.length) {
        const link = el("a", "", "архив");
        link.href = m.url;
        hint.append(" Или скачайте ", link, " вручную и распакуйте в папку models/ рядом с программой.");
      }
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
    head.append(pick);
    const action = modelAction(m, selected, active);
    if (action) head.append(action);
    head.append(expand);
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
      card.append(el("div", "model-download status-line error", `${download.error}. Нажмите «Скачать», чтобы попробовать ещё раз`));
    }
    if (m.cloud && !grouped) card.append(cloudKeyRow(m));
    card.append(details);
    return card;
  }

  // Облачная модель: поле для API-ключа сервиса, одно на все модели этого сервиса.
  function cloudKeyRow(m) {
    const provider = (shownSpeech && shownSpeech[0].providers[m.provider]) || { title: m.provider };
    const box = el("div", "model-download cloud-key");
    if (m.has_key) {
      const row = el("div", "row");
      row.append(el("span", "download-text", `Ключ ${provider.title} сохранён. Звук фраз уходит в ${provider.title}.`));
      const remove = el("button", "secondary-btn small-btn", "Удалить ключ");
      remove.type = "button";
      confirmByTwoClicks(remove, "Удалить?", () => keyCall("DELETE", `/api/speech/cloud-key/${m.provider}`, null, remove));
      row.append(remove);
      box.append(row);
      return box;
    }
    box.append(el("div", "download-text", `Звук фраз будет отправляться в ${provider.title}: нужен ваш API-ключ.`));
    const row = el("div", "row key-row");
    const input = document.createElement("input");
    input.type = "password";
    input.className = "text-input key-input";
    input.placeholder = `API-ключ ${provider.title}`;
    input.autocomplete = "off";
    input.spellcheck = false;
    const save = el("button", "secondary-btn small-btn", "Сохранить ключ");
    save.type = "button";
    save.addEventListener("click", () => keyCall("PUT", "/api/speech/cloud-key", { provider: m.provider, key: input.value }, save));
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") save.click();
    });
    row.append(input, save);
    box.append(row);
    if (provider.keys_page) {
      const link = el("a", "", "Где взять ключ");
      link.href = provider.keys_page;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      box.append(link);
    }
    return box;
  }

  // Группа облачных моделей одного сервиса: ключ вводится один раз, под ним — его модели.
  function providerGroup(provider, models, current, failed) {
    const info = (shownSpeech && shownSpeech[0].providers[provider]) || { title: provider };
    const group = el("section", "provider-group");
    const hasKey = models.some((m) => m.has_key);
    const head = el("div", "provider-head");
    head.append(el("span", "provider-name", info.title));
    head.append(el("span", `badge${hasKey ? " ok" : ""}`, hasKey ? "ключ сохранён" : "нужен ключ"));
    group.append(head);
    group.append(cloudKeyRow(models[0]));
    const list = el("div", "model-list");
    list.append(...models.map((m) => modelCard(m, current, failed, true)));
    group.append(list);
    return group;
  }

  async function keyCall(method, url, body, button) {
    button.disabled = true;
    try {
      showSpeech(await api(method, url, body || undefined));
    } catch (e) {
      setStatus(speechStatusEl, e.message, true);
      button.disabled = false;
    }
  }

  // Кнопка в карточке: «Скачать» у нескачанной модели, корзина — у скачанной.
  function modelAction(m, selected, active) {
    if (active) return null;
    const box = el("div", "model-action");
    let button;
    if (!m.installed) {
      button = el("button", "secondary-btn small-btn", "⬇ Скачать");
      button.title = `Скачать модель (${m.download_size})`;
      button.addEventListener("click", () => modelCall("POST", `/api/speech/download/${encodeURIComponent(m.id)}`, button));
    } else {
      button = el("button", "icon-btn", "🗑");
      if (selected) {
        button.disabled = true;
        button.title = "Выбранную модель удалить нельзя: сначала выберите другую";
      } else {
        button.title = "Удалить модель с диска";
        confirmByTwoClicks(button, "Удалить?", () =>
          modelCall("DELETE", `/api/speech/model/${encodeURIComponent(m.id)}`, button));
      }
    }
    button.type = "button";
    box.append(button);
    return box;
  }

  async function modelCall(method, url, button) {
    button.disabled = true;
    try {
      showSpeech(await api(method, url));
    } catch (e) {
      setStatus(speechStatusEl, e.message, true);
      button.disabled = false;
    }
  }

  // Вкладки «На компьютере» / «Облако»: пятнадцать карточек в одном списке не обозреть.
  let modelGroup = null; // "local" | "cloud"; пока null — берётся группа выбранной модели
  const modelTabsEl = el("div", "model-tabs");
  modelTabsEl.setAttribute("role", "group");
  modelTabsEl.setAttribute("aria-label", "Где распознавать");
  modelListEl.before(modelTabsEl);

  function renderModelTabs(models, current) {
    const counts = { local: 0, cloud: 0 };
    for (const m of models) counts[m.cloud ? "cloud" : "local"] += 1;
    const labels = { local: "На компьютере", cloud: "Облако (по API-ключу)" };
    const buttons = ["local", "cloud"].map((group) => {
      const button = el("button", "model-tab", `${labels[group]} · ${counts[group]}`);
      button.type = "button";
      button.setAttribute("aria-pressed", String(modelGroup === group));
      if (current && Boolean(current.cloud) === (group === "cloud")) button.append(el("span", "model-tab-dot"));
      button.addEventListener("click", () => {
        modelGroup = group;
        renderedModelsKey = null;
        if (shownSpeech) showModels(...shownSpeech);
      });
      return button;
    });
    modelTabsEl.replaceChildren(...buttons);
  }

  function showModels(state, loading) {
    $("model-section").hidden = false;
    shownSpeech = [state, loading];
    if (speechLanguage === null) {
      const current = state.models.find((m) => m.id === state.model);
      speechLanguage = (current && current.language) || "ru";
      speechLanguageEl.value = speechLanguage;
    }
    $("speech-language-note").hidden = speechLanguage === "ru";
    const inLanguage = state.models.filter((m) => m.language === speechLanguage);
    const currentModel = state.models.find((m) => m.id === state.model && m.installed);
    if (modelGroup === null) modelGroup = currentModel && currentModel.cloud ? "cloud" : "local";
    const models = inLanguage.filter((m) => Boolean(m.cloud) === (modelGroup === "cloud"));
    // Перерисовываем только при изменениях: опрос идёт раз в секунду.
    const failed = state.status === "error";
    // Байты скачивания в ключ не входят: полосы обновляются на месте, без перерисовки карточек.
    const key = JSON.stringify([
      state.models.map((m) => [m.id, m.installed, m.has_key, m.download && m.download.status, m.download && m.download.error]),
      state.model,
      failed,
      speechLanguage,
      modelGroup,
    ]);
    if (key !== renderedModelsKey) {
      renderedModelsKey = key;
      downloadBars.clear();
      renderModelTabs(inLanguage, currentModel);
      if (modelGroup === "cloud") {
        const providers = [...new Set(models.map((m) => m.provider))];
        modelListEl.replaceChildren(
          ...providers.map((p) => providerGroup(p, models.filter((m) => m.provider === p), state.model, failed))
        );
      } else {
        modelListEl.replaceChildren(...models.map((m) => modelCard(m, state.model, failed)));
      }
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
        (downloading.id === state.wanted || state.status === "no_model" ? "Когда скачается, она включится сама. " : "") +
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
    // Новая загрузка: полоса сразу с нуля, без анимации назад.
    progressBarEl.style.transition = "none";
    progressBarEl.style.width = "0";
    void progressBarEl.offsetWidth;
    progressBarEl.style.transition = "";
    try {
      showSpeech(await api("POST", "/api/speech/model", { model: m.id }));
    } catch (e) {
      setStatus(speechStatusEl, e.message, true);
    }
  }

  function cancelDownload(id, button) {
    return modelCall("DELETE", `/api/speech/download/${encodeURIComponent(id)}`, button);
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
    badge.textContent = state.force ? `Обязательно ${latest}` : `Доступна ${latest}`;
    badge.classList.toggle("force", !!state.force);
    showLock(state);

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
      const kind = state.force ? "обязательная версия" : "новая версия";
      setStatus(status, state.can_install
        ? `Доступна ${kind} ${latest} (у вас v${state.current}).`
        : `Доступна ${kind} ${latest}. Из исходников обновитесь через git pull` +
          (state.force ? " (собранная программа без неё не работает)." : "."));
    } else setStatus(status, `Версия v${state.current}`);
  }

  // Обязательное обновление в собранной программе: всё, кроме раздела обновлений,
  // закрыто затемнением и недоступно с клавиатуры (сервер такие запросы тоже отклоняет).
  function showLock(state) {
    const locked = !!state.locked;
    document.body.classList.toggle("update-locked", locked);
    $("update-lock-note").hidden = !locked;
    if (state.html_url && /^https:\/\//i.test(state.html_url)) $("update-manual").href = state.html_url;
    // Раздел обновлений лежит на вкладке настроек: открываем её и закрываем всё вокруг раздела.
    const section = $("update-section");
    if (locked) selectTab("settings");
    const panel = $("tab-settings");
    for (const node of [...document.querySelector("main").children, ...panel.children]) {
      if (node !== section && node !== panel) node.inert = locked;
    }
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

  // --- Автозапуск: с Windows, при запуске OBS и при начале трансляции ---

  const autostartStatusEl = $("autostart-status");
  const obsPasswordEl = $("obs-password");

  function showAutostart(state) {
    // Порт и пароль OBS (раздел «OBS») нужны и без автозапуска.
    // Поле порта не трогаем, пока его редактируют.
    if (document.activeElement !== $("obs-port")) $("obs-port").value = state.obs_port;
    obsPasswordEl.placeholder = state.has_password
      ? "Пароль сохранён (пусто — не менять)"
      : "Пароль (если задан в OBS)";
    if (!state.available) return; // реестр и процессы OBS есть только в Windows
    $("autostart-section").hidden = false;
    $("autostart-windows").checked = state.windows;
    $("autostart-obs").value = state.obs;
    $("autostart-stream").value = state.stream;
  }

  function autostartChoice() {
    return {
      windows: $("autostart-windows").checked,
      obs: $("autostart-obs").value,
      stream: $("autostart-stream").value,
      obs_port: Number($("obs-port").value) || 4455,
      obs_password: obsPasswordEl.value || null, // пусто — оставить сохранённый
    };
  }

  async function saveAutostart(statusEl = autostartStatusEl) {
    try {
      showAutostart(await api("POST", "/api/autostart", autostartChoice()));
      obsPasswordEl.value = "";
      setStatus(statusEl, "Сохранено", false, true);
    } catch (e) {
      setStatus(statusEl, e.message, true);
      api("GET", "/api/autostart").then(showAutostart, () => {});
    }
  }

  for (const id of ["autostart-windows", "autostart-obs", "autostart-stream"]) {
    $(id).addEventListener("change", () => saveAutostart());
  }

  // --- OBS: порт и пароль, сброс при начале трансляции или записи, смена сцены по порогу ---

  const obsStatusEl = $("obs-status");
  const obsSceneEl = $("obs-scene");

  $("obs-ws-form").addEventListener("submit", (event) => {
    event.preventDefault();
    saveAutostart(obsStatusEl);
  });
  $("obs-check").addEventListener("click", async () => {
    const button = $("obs-check");
    const { obs_port, obs_password } = autostartChoice();
    button.disabled = true;
    setStatus(obsStatusEl, "Подключаюсь к OBS…");
    try {
      const result = await api("POST", "/api/autostart/obs-check", { obs_port, obs_password });
      setStatus(obsStatusEl, result.streaming
        ? "OBS на связи, трансляция идёт" : "OBS на связи. Не забудьте сохранить порт и пароль", false, true);
    } catch (e) {
      setStatus(obsStatusEl, e.message, true);
    } finally {
      button.disabled = false;
    }
  });

  // Выбранная сцена есть в списке, даже если список из OBS ещё не загружен.
  function setSceneOptions(names, selected) {
    const all = selected && !names.includes(selected) ? [selected, ...names] : names;
    obsSceneEl.replaceChildren(obsSceneEl.options[0]);
    for (const name of all) obsSceneEl.add(new Option(name, name));
    obsSceneEl.value = selected;
  }

  function showObsStatus(status) {
    if (!status.enabled) setStatus(obsStatusEl, "");
    else if (status.connected) setStatus(obsStatusEl, "OBS на связи", false);
    else setStatus(obsStatusEl, status.error || "Подключаюсь к OBS…", Boolean(status.error));
  }

  function showObs(state) {
    $("obs-reset-stream").checked = state.reset_stream;
    $("obs-reset-record").checked = state.reset_record;
    if (document.activeElement !== $("obs-scene-at")) $("obs-scene-at").value = state.scene_at || "";
    const names = [...obsSceneEl.options].slice(1).map((o) => o.value);
    setSceneOptions(names, state.scene);
    showObsStatus(state.status);
  }

  async function saveObs() {
    try {
      showObs(await api("POST", "/api/obs", {
        reset_stream: $("obs-reset-stream").checked,
        reset_record: $("obs-reset-record").checked,
        scene: obsSceneEl.value,
        scene_at: Number($("obs-scene-at").value) || 0,
      }));
    } catch (e) {
      setStatus(obsStatusEl, e.message, true);
      api("GET", "/api/obs").then(showObs, () => {});
    }
  }

  for (const id of ["obs-reset-stream", "obs-reset-record", "obs-scene", "obs-scene-at"]) {
    $(id).addEventListener("change", saveObs);
  }
  $("obs-scenes-load").addEventListener("click", async () => {
    const button = $("obs-scenes-load");
    button.disabled = true;
    try {
      setSceneOptions((await api("GET", "/api/obs/scenes")).scenes, obsSceneEl.value);
    } catch (e) {
      setStatus(obsStatusEl, e.message, true);
    } finally {
      button.disabled = false;
    }
  });

  // --- Горячие клавиши: «+1», пауза и сброс, даже когда окно свёрнуто ---

  const hotkeysStatusEl = $("hotkeys-status");
  const hotkeyButtons = document.querySelectorAll(".hotkey");
  const HOTKEY_LABELS = {
    NumAdd: "Num +", NumSubtract: "Num −", NumMultiply: "Num *", NumDivide: "Num /", NumDecimal: "Num .",
    Minus: "-", Equal: "=", Backquote: "`", Up: "↑", Down: "↓", Left: "←", Right: "→",
  };
  const HOTKEY_ACTIONS = { increment: "+1", pause: "Пауза", reset: "Сбросить" };
  let recordingHotkey = null; // кнопка, которая ждёт сочетание

  function hotkeyLabel(combo) {
    return combo.split("+").map((part) => HOTKEY_LABELS[part] || part).join(" + ");
  }

  function showHotkeys(state) {
    if (!state.available) return; // RegisterHotKey есть только в Windows
    $("hotkeys-section").hidden = false;
    for (const button of hotkeyButtons) {
      const combo = state.hotkeys[button.dataset.action] || "";
      const failed = state.failed.includes(button.dataset.action);
      button.dataset.combo = combo;
      button.textContent = combo ? hotkeyLabel(combo) : "не задано";
      button.classList.toggle("empty", !combo);
      button.classList.toggle("failed", failed);
      button.classList.remove("recording");
      button.title = failed ? "Сочетание занято другой программой" : "";
    }
    const failed = state.failed.map((action) => HOTKEY_ACTIONS[action]);
    if (failed.length) {
      setStatus(hotkeysStatusEl, `Занято другой программой, выберите другое: ${failed.join(", ")}`, true);
    }
  }

  // KeyboardEvent.code → имя клавиши, как его понимает сервер (app/hotkeys.py).
  function hotkeyKeyName(code) {
    let m;
    if ((m = code.match(/^Key([A-Z])$/)) || (m = code.match(/^Digit(\d)$/))) return m[1];
    if (/^F\d{1,2}$/.test(code)) return code;
    if ((m = code.match(/^Numpad(\d|Add|Subtract|Multiply|Divide|Decimal)$/))) return "Num" + m[1];
    if ((m = code.match(/^Arrow(Up|Down|Left|Right)$/))) return m[1];
    if (["Space", "PageUp", "PageDown", "End", "Home", "Insert", "Delete", "Pause", "Minus", "Equal", "Backquote"]
      .includes(code)) return code;
    return null;
  }

  function stopRecording() {
    if (!recordingHotkey) return;
    const button = recordingHotkey;
    recordingHotkey = null;
    button.classList.remove("recording");
    button.textContent = button.dataset.combo ? hotkeyLabel(button.dataset.combo) : "не задано";
  }

  async function saveHotkey(action, combo) {
    setStatus(hotkeysStatusEl, "");
    try {
      showHotkeys(await api("POST", "/api/hotkeys", { action, combo }));
      if (!hotkeysStatusEl.classList.contains("error")) setStatus(hotkeysStatusEl, "Сохранено", false, true);
    } catch (e) {
      setStatus(hotkeysStatusEl, e.message, true);
      api("GET", "/api/hotkeys").then(showHotkeys, () => {});
    }
  }

  for (const button of hotkeyButtons) {
    button.addEventListener("click", () => {
      const again = recordingHotkey === button;
      stopRecording();
      if (again) return;
      recordingHotkey = button;
      button.classList.add("recording");
      button.textContent = "Нажмите сочетание…";
    });
    button.addEventListener("blur", stopRecording);
    button.addEventListener("keydown", (e) => {
      if (recordingHotkey !== button) return;
      e.preventDefault();
      e.stopPropagation();
      const mods = [];
      if (e.ctrlKey) mods.push("Ctrl");
      if (e.altKey) mods.push("Alt");
      if (e.shiftKey) mods.push("Shift");
      if (e.metaKey) mods.push("Win");
      if (e.key === "Escape" && !mods.length) return stopRecording();
      if (e.key === "Backspace" && !mods.length) {
        stopRecording();
        return saveHotkey(button.dataset.action, "");
      }
      const key = hotkeyKeyName(e.code);
      if (!key) {
        // Пока зажаты только модификаторы, показываем их и ждём основную клавишу.
        button.textContent = mods.length ? mods.join(" + ") + " + …" : "Нажмите сочетание…";
        return;
      }
      stopRecording();
      saveHotkey(button.dataset.action, [...mods, key].join("+"));
    });
  }

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

  function listOptions(lists) {
    return lists.map(
      (list) => new Option(`${list.name} — ${list.words} ${plural(list.words, "корень", "корня", "корней")}`, list.id)
    );
  }

  function showWords(state) {
    $("words-section").hidden = false;
    wordLists = state.lists;
    wordListEl.replaceChildren(...listOptions(state.lists));
    renderCounters();
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

  // --- Версия и кнопка «Поддержать» (способы задаёт SUPPORT_LINKS в app/__init__.py) ---

  function showVersion({ version, support, order_email: orderEmail }) {
    $("version").textContent = `v${version}`;
    $("order-offer").hidden = !orderEmail;
    // Только https: в ссылку не должен попасть javascript: или другой протокол.
    const links = (Array.isArray(support) ? support : [])
      .filter((l) => l && typeof l.url === "string" && /^https:\/\//i.test(l.url));
    const box = $("support-links");
    box.replaceChildren(...links.map((l) => {
      const a = document.createElement("a");
      a.className = "support-card";
      a.href = l.url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      if (typeof l.qr === "string" && /^[\w/-]+\.png$/.test(l.qr)) {
        const img = document.createElement("img");
        img.src = l.qr;
        img.alt = `QR-код ${l.name}`;
        a.append(img);
      }
      a.append(String(l.name || l.url));
      return a;
    }));
    $("support").hidden = $("support-open").hidden = !links.length;
  }

  // --- Заказ оформления у автора ---
  // Письмо собирает сервер. Если на компьютере есть почтовая программа, он открывает её,
  // иначе предлагает сайт почты отправителя (Gmail, Яндекс, Mail) с уже заполненным письмом.

  const orderDialog = $("order-dialog");
  const orderForm = $("order-form");
  const orderEmailEl = $("order-email");
  const orderDescriptionEl = $("order-description");
  const orderStatusEl = $("order-status");
  const orderSendBtn = $("order-send");
  const orderFallback = $("order-fallback");
  const orderWebmail = $("order-webmail");
  const orderCopyBtn = $("order-copy");
  const orderCopyTextBtn = $("order-copy-text");
  let orderLetter = null;

  function showOrderLetter(res) {
    orderLetter = res;
    const web = res.webmail;
    const webOk = web && typeof web.url === "string" && /^https:\/\//i.test(web.url);
    orderWebmail.hidden = !webOk;
    orderWebmail.removeAttribute("href");
    if (webOk) {
      orderWebmail.href = web.url;
      orderWebmail.textContent = `Открыть в ${web.name}`;
    }
    orderCopyBtn.replaceChildren(res.email, el("span", "copy-label", "Скопировать"));
    orderCopyBtn.classList.remove("copied");
    orderCopyTextBtn.textContent = "Скопировать текст письма";
    orderFallback.hidden = false;

    let text;
    if (res.opened) {
      text = "Письмо открылось в почтовой программе: проверьте его и отправьте.";
      if (webOk) text += ` Если удобнее, напишите из ${web.name}.`;
    } else if (webOk && web.filled) {
      text = `Нажмите «Открыть в ${web.name}»: письмо автору уже заполнено, останется отправить.`;
    } else if (webOk) {
      text = `Нажмите «Открыть в ${web.name}» и вставьте в новое письмо адрес автора и текст: их можно скопировать.`;
    } else {
      text = "Напишите автору с любой почты: адрес и текст письма можно скопировать.";
    }
    setStatus(orderStatusEl, text, false, res.opened);
  }

  $("order-open").addEventListener("click", () => {
    setStatus(orderStatusEl, "");
    orderFallback.hidden = true;
    orderSendBtn.textContent = "Отправить";
    orderDialog.showModal();
    (orderEmailEl.value ? orderDescriptionEl : orderEmailEl).focus();
  });
  $("order-cancel").addEventListener("click", () => orderDialog.close());
  // Описание поменяли: прежние ссылки и текст письма устарели.
  orderForm.addEventListener("input", () => {
    if (orderFallback.hidden) return;
    orderFallback.hidden = true;
    orderSendBtn.textContent = "Отправить";
    setStatus(orderStatusEl, "");
  });

  orderCopyBtn.addEventListener("click", async () => {
    const ok = await copyText(orderLetter ? orderLetter.email : "");
    orderCopyBtn.classList.toggle("copied", ok);
    orderCopyBtn.lastChild.textContent = ok ? "Скопировано" : "Не скопировалось";
  });
  orderCopyTextBtn.addEventListener("click", async () => {
    if (!orderLetter) return;
    const ok = await copyText(`Тема: ${orderLetter.subject}\n\n${orderLetter.body}`);
    orderCopyTextBtn.textContent = ok ? "✓ Текст скопирован" : "Не скопировалось";
  });

  orderForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const email = orderEmailEl.value.trim();
    const description = orderDescriptionEl.value.trim();
    if (!orderEmailEl.checkValidity() || !email) {
      setStatus(orderStatusEl, "Укажите почту, на которую автор сможет ответить", true);
      orderEmailEl.focus();
      return;
    }
    if (!description) {
      setStatus(orderStatusEl, "Опишите, каким должно быть оформление", true);
      orderDescriptionEl.focus();
      return;
    }
    orderSendBtn.disabled = true;
    setStatus(orderStatusEl, "Готовлю письмо…");
    try {
      showOrderLetter(await api("POST", "/api/order", { email, description }));
      orderSendBtn.textContent = "Ещё раз";
    } catch (e) {
      setStatus(orderStatusEl, e.message, true);
    } finally {
      orderSendBtn.disabled = false;
    }
  });

  // Сердечко в углу и пункт трея «Поддержать автора»: раскрыть блок и прокрутить к нему.
  function openSupport() {
    const details = $("support");
    if (details.hidden) return;
    details.open = true;
    showInSettings(details);
  }
  window.openSupport = openSupport;
  $("support-open").addEventListener("click", openSupport);

  // --- WebSocket: счёт, звук, оформление и уровень микрофона ---

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onopen = () => {
      setOnline(true);
      refreshSpeech();
      loadDevices();
      loadWords();
      loadCustomPresets();
      loadStats();
      api("GET", "/api/version").then(showVersion, () => {});
      api("GET", "/api/update").then(showUpdate, () => {});
      api("GET", "/api/autostart").then(showAutostart, () => {});
      api("GET", "/api/obs").then(showObs, () => {});
      api("GET", "/api/hotkeys").then(showHotkeys, () => {});
    };
    ws.onmessage = (event) => {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch (e) {
        return;
      }
      if (msg.type === "mic_level") {
        targetLevel = Math.max(targetLevel, levelToPosition(msg.level));
        wakeMeter();
      }
      else if (msg.type === "sound") showSound(msg);
      else if (msg.type === "update") showUpdate(msg);
      else if (msg.type === "presets") loadCustomPresets();
      else if (msg.type === "pause") showPause(msg.paused);
      else if (msg.type === "timer") showTimer(msg);
      else if (msg.type === "goals") showGoals(msg);
      else if (msg.type === "obs") showObsStatus(msg);
      else if (msg.type === "counters") showCounters(msg.counters);
      else if (msg.type === "extra_increment") showExtraCount(msg);
      else if (msg.type === "style") {
        showServerPreset(msg.preset);
        showServerLabel(msg.label, msg.label_position);
      }
      else if (msg.count !== undefined) {
        showCount(msg.count);
        renderGoalLeft();
        refreshStatsSoon();
      }
    };
    ws.onclose = () => {
      setOnline(false);
      setTimeout(connect, 2000);
    };
    ws.onerror = () => ws.close();
  }
  connect();
})();
