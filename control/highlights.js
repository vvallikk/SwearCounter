// Хайлайты: моменты со словами и таймкоды для описания видео (app/highlights.py).
// Отдельный файл со своим опросом сервера: не пересекается с control.js.
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const section = $("highlights-section");
  if (!section) return;

  const POLL_MS = 3000;
  const BASE_NAMES = { stream: "начала трансляции", record: "начала записи", start: "запуска программы" };
  const OBS_LOST = "Нет связи с OBS: проверьте, что он запущен и порт с паролем указаны в настройках";
  const statusEl = $("highlights-status");
  const leadEl = $("highlights-lead");
  const checks = { obs: $("highlights-obs"), chapter: $("highlights-chapter"), clip: $("highlights-clip") };
  let state = null;
  let timer = null;

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
      throw new Error("Нет связи с приложением. Проверьте, что оно запущено, и повторите");
    }
    if (resp.ok && url.includes("/text")) return resp.text();
    const data = await resp.json().catch(() => null);
    if (resp.ok) return data;
    const detail = data && data.detail;
    throw new Error((typeof detail === "string" && detail) || `Ошибка сервера (${resp.status})`);
  }

  function setStatus(text, error, ok) {
    statusEl.textContent = text;
    statusEl.classList.toggle("error", Boolean(error));
    statusEl.classList.toggle("ok", Boolean(ok));
  }

  function lead() {
    const n = Math.round(Number(leadEl.value));
    return Number.isFinite(n) ? Math.min(30, Math.max(0, n)) : 3;
  }

  function formatTime(seconds) {
    const total = Math.max(0, Math.floor(seconds));
    const h = Math.floor(total / 3600), m = Math.floor((total % 3600) / 60), s = total % 60;
    const pad = (n) => String(n).padStart(2, "0");
    return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
  }

  function show(data) {
    state = data;
    section.hidden = false;
    for (const [key, box] of Object.entries(checks)) box.checked = Boolean(data.options[key]);

    const list = $("highlights-list");
    list.replaceChildren();
    for (const m of data.moments.slice().reverse()) {
      const item = document.createElement("li");
      const time = document.createElement("span");
      time.className = "highlight-time";
      time.textContent = formatTime(m.time);
      const label = document.createElement("span");
      label.textContent = "Слово";
      const details = document.createElement("span");
      details.textContent = (m.count > 1 ? `×${m.count}` : "") + (m.words.length ? `${m.count > 1 ? " " : ""}${m.words.slice(0, 5).join(", ")}` : "");
      details.setAttribute("translate", "no");
      item.append(time, label, details);
      if (m.clips.length) {
        const clip = document.createElement("span");
        clip.className = "highlight-clip";
        clip.textContent = "клип";
        clip.title = m.clips.join("\n");
        item.append(clip);
      }
      list.append(item);
    }

    const n = data.moments.length;
    $("highlights-summary").textContent = n
      ? `Моментов: ${n} · Отсчёт: ${BASE_NAMES[data.base] || data.base}`
      : "Пока пусто: момент появится с первого засчитанного слова.";
    for (const id of ["highlights-copy", "highlights-txt", "highlights-csv"]) $(id).disabled = !n;

    const wantsObs = data.options.obs || data.options.chapter || data.options.clip;
    if (data.error) {
      setStatus(data.error, true);
    } else if (wantsObs && !data.obs.connected) {
      setStatus(OBS_LOST);
    } else if (statusEl.classList.contains("error") || statusEl.textContent === OBS_LOST) {
      setStatus("");
    }
  }

  async function load() {
    try {
      show(await api("GET", `/api/highlights?lead=${lead()}`));
    } catch (e) {
      // Старый сервер без хайлайтов — раздел не показываем.
    }
  }

  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      if (!document.hidden) await load();
      schedule();
    }, POLL_MS);
  }

  async function saveOptions() {
    const body = {};
    for (const [key, box] of Object.entries(checks)) body[key] = box.checked;
    try {
      show(await api("POST", "/api/highlights", body));
      setStatus("Сохранено", false, true);
    } catch (e) {
      setStatus(e.message, true);
    }
  }

  function base() {
    return state ? state.base : "start";
  }

  async function copy() {
    try {
      const text = await api("GET", `/api/highlights/text?format=chapters&base=${base()}&lead=${lead()}`);
      await navigator.clipboard.writeText(text);
      setStatus("Скопировано: вставьте в описание видео", false, true);
    } catch (e) {
      setStatus(e.message, true);
    }
  }

  async function save(format) {
    try {
      const { path } = await api("POST", "/api/highlights/export", { format, base: base(), lead: lead() });
      setStatus(`Сохранено: ${path}`, false, true);
    } catch (e) {
      setStatus(e.message, true);
    }
  }

  // Подтверждение вторым нажатием: confirm() во встроенных браузерах (док OBS) не работает.
  const restart = $("highlights-restart");
  let armed = null;
  function disarm() {
    clearTimeout(armed);
    armed = null;
    restart.textContent = "Начать заново";
    restart.classList.remove("confirm");
  }
  restart.addEventListener("click", async () => {
    if (armed === null) {
      restart.textContent = "Точно начать заново?";
      restart.classList.add("confirm");
      armed = setTimeout(disarm, 3000);
      return;
    }
    disarm();
    try {
      show(await api("DELETE", "/api/highlights"));
      setStatus("");
    } catch (e) {
      setStatus(e.message, true);
    }
  });

  try {
    const saved = Number(localStorage.getItem("highlights-lead"));
    if (Number.isFinite(saved) && saved >= 0 && saved <= 30) leadEl.value = saved;
  } catch (e) {
    // Без localStorage остаётся значение по умолчанию.
  }
  leadEl.addEventListener("change", () => {
    leadEl.value = lead();
    try { localStorage.setItem("highlights-lead", String(lead())); } catch (e) { /* не страшно */ }
    load();
  });
  for (const box of Object.values(checks)) box.addEventListener("change", saveOptions);
  $("highlights-copy").addEventListener("click", copy);
  $("highlights-txt").addEventListener("click", () => save("chapters"));
  $("highlights-csv").addEventListener("click", () => save("csv"));
  document.addEventListener("visibilitychange", () => { if (!document.hidden) load(); });

  load();
  schedule();
})();
