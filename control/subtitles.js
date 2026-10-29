// Раздел «Субтитры» на вкладке «Настройки»: выключатели и адрес источника для OBS
// (сервер — app/subtitles.py, оверлей — overlay/subtitles.js).
(() => {
  "use strict";

  const kit = window.controlKit;
  const section = document.getElementById("subtitles-section");
  if (!kit || !section) return;

  const enabledEl = document.getElementById("subtitles-enabled");
  const uncensoredEl = document.getElementById("subtitles-uncensored");
  const statusEl = document.getElementById("subtitles-status");
  const url = `${location.origin}/overlay/?show=subtitles`;

  document.getElementById("subtitles-url-text").textContent = url;
  kit.bindCopyLink(document.getElementById("subtitles-url"), url);
  kit.bindOpen(document.getElementById("subtitles-open"), "subtitles", url);

  function show(state) {
    enabledEl.checked = state.enabled;
    uncensoredEl.checked = state.uncensored;
    section.hidden = false;
  }
  window.showSubtitles = show; // то же состояние приходит по WebSocket из других окон

  async function send(body) {
    enabledEl.disabled = uncensoredEl.disabled = true;
    try {
      show(await kit.api("POST", "/api/subtitles", body));
      kit.setStatus(statusEl, "");
    } catch (e) {
      kit.setStatus(statusEl, e.message, true);
      kit.api("GET", "/api/subtitles").then(show).catch(() => {});
    } finally {
      enabledEl.disabled = uncensoredEl.disabled = false;
    }
  }

  enabledEl.addEventListener("change", () => send({ enabled: enabledEl.checked }));
  uncensoredEl.addEventListener("change", () => send({ uncensored: uncensoredEl.checked }));

  document.getElementById("subtitles-test").addEventListener("click", async () => {
    try {
      await kit.api("POST", "/api/subtitles/test");
      kit.setStatus(statusEl, "Пример отправлен в оверлей субтитров", false, true);
    } catch (e) {
      kit.setStatus(statusEl, e.message, true);
    }
  });

  // Сервер старее страницы — раздел остаётся скрытым.
  kit.api("GET", "/api/subtitles").then(show).catch(() => {});
})();
