// Раздел «Отчёт после стрима» (app/stream_report.py): куда отправлять, предпросмотр и отправка.
// Сохранённые вебхук и токен сервер не отдаёт: в поле видно только их хвост в подсказке,
// пустое поле при сохранении оставляет сохранённое.
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  if (!$("report-section")) return;

  const statusEl = $("report-status");
  const textEl = $("report-text");

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

  function showSecret(input, clear, secret, placeholder) {
    input.value = "";
    input.placeholder = secret.set ? `Сохранён: ${secret.hint}` : placeholder;
    clear.hidden = !secret.set;
  }

  function showLast(last) {
    const box = $("report-last");
    box.replaceChildren();
    if (!last || !last.results) return;
    const when = new Date(last.time * 1000).toLocaleString();
    const head = document.createElement("div");
    head.className = "report-last-head";
    head.textContent = last.auto ? `Отправлено после трансляции: ${when}` : `Отправлено вручную: ${when}`;
    box.append(head);
    for (const [target, result] of Object.entries(last.results)) {
      const line = document.createElement("div");
      line.className = `status-line ${result.ok ? "ok" : "error"}`;
      const name = target === "discord" ? "Discord" : "Telegram";
      line.textContent = result.ok ? `${name} — отправлено` : `${name} — ${result.error}`;
      box.append(line);
    }
  }

  function show(state) {
    showSecret($("report-discord"), $("report-discord-clear"), state.discord, "https://discord.com/api/webhooks/…");
    showSecret($("report-tg-token"), $("report-tg-clear"), state.telegram, "123456789:AAE…");
    if (document.activeElement !== $("report-tg-chat")) $("report-tg-chat").value = state.telegram.chat;
    $("report-auto").checked = state.auto;
    $("report-censor").checked = state.censor;
    $("report-send").disabled = !state.discord.set && !(state.telegram.set && state.telegram.chat);
    showLast(state.last);
  }

  async function save(body, okText) {
    try {
      show(await api("POST", "/api/stream-report", body));
      if (okText) setStatus(okText, false, true);
      if (!textEl.hidden) preview();
    } catch (e) {
      setStatus(e.message, true);
      load();
    }
  }

  async function preview() {
    try {
      textEl.textContent = (await api("GET", "/api/stream-report/preview")).text;
      textEl.hidden = false;
    } catch (e) {
      setStatus(e.message, true);
    }
  }

  async function load() {
    try {
      show(await api("GET", "/api/stream-report"));
    } catch (e) {
      // нет связи: раздел покажет данные при следующем открытии вкладки
    }
  }

  $("report-save").addEventListener("click", () => {
    const body = { telegram_chat: $("report-tg-chat").value };
    // Пустое поле — оставить сохранённое: сам секрет страница не знает.
    if ($("report-discord").value.trim()) body.discord_webhook = $("report-discord").value;
    if ($("report-tg-token").value.trim()) body.telegram_token = $("report-tg-token").value;
    save(body, "Сохранено");
  });
  $("report-discord-clear").addEventListener("click", () => save({ discord_webhook: "" }, ""));
  $("report-tg-clear").addEventListener("click", () => save({ telegram_token: "" }, ""));
  $("report-auto").addEventListener("change", () => save({ auto: $("report-auto").checked }, ""));
  $("report-censor").addEventListener("change", () => save({ censor: $("report-censor").checked }, ""));
  $("report-preview").addEventListener("click", preview);
  $("report-send").addEventListener("click", async () => {
    const button = $("report-send");
    button.disabled = true;
    setStatus("Отправляю…");
    try {
      const state = await api("POST", "/api/stream-report/send");
      show(state);
      setStatus("");
    } catch (e) {
      setStatus(e.message, true);
    } finally {
      button.disabled = false;
    }
  });
  // Автоотправка после трансляции меняет «последнюю отправку»: обновляем при каждом входе на вкладку.
  document.addEventListener("tabchange", (event) => {
    if (event.detail === "settings") load();
  });
  load();
})();
