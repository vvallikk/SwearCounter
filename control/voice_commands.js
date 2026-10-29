// Голосовые команды (app/voice_commands.py): кодовое слово, фразы команд и сцены OBS.
// Сохраняется при каждом изменении, как раздел «OBS». О сработавшей команде сервер
// сообщает по WebSocket, control.js пересылает это событием "voice-command".
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const section = $("voice-section");
  if (!section) return;

  const ACTIONS = ["pause", "resume", "increment", "reset"];
  const LABELS = { pause: "Пауза", resume: "Продолжить", increment: "+1", reset: "Сброс счёта", scene: "Сцена" };
  const statusEl = $("voice-status");
  const lastEl = $("voice-last");
  const scenesEl = $("voice-scenes");
  let current = null; // последнее состояние с сервера

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

  function setStatus(node, text, error, ok) {
    node.textContent = text;
    node.classList.toggle("error", Boolean(error));
    node.classList.toggle("ok", Boolean(ok));
  }

  const splitPhrases = (text) => text.split(",").map((p) => p.trim()).filter(Boolean);
  const joinPhrases = (list) => list.join(", ");
  const editing = (node) => document.activeElement === node;

  function sceneRow(item) {
    const row = document.createElement("div");
    row.className = "voice-row voice-scene";
    const scene = document.createElement("input");
    scene.className = "text-input voice-scene-name";
    scene.type = "text";
    scene.autocomplete = "off";
    scene.placeholder = "Сцена OBS";
    scene.setAttribute("list", "voice-scene-names");
    scene.setAttribute("aria-label", "Сцена OBS");
    scene.value = item.scene;
    const phrases = document.createElement("input");
    phrases.className = "text-input voice-scene-phrases";
    phrases.type = "text";
    phrases.autocomplete = "off";
    phrases.placeholder = "Например: сцена игра";
    phrases.setAttribute("aria-label", "Фразы");
    phrases.value = joinPhrases(item.phrases);
    const remove = document.createElement("button");
    remove.className = "secondary-btn square-btn voice-remove";
    remove.type = "button";
    remove.textContent = "✕";
    remove.title = "Удалить команду";
    remove.addEventListener("click", () => {
      row.remove();
      save();
    });
    for (const input of [scene, phrases]) input.addEventListener("change", save);
    const wrap = document.createElement("div");
    wrap.className = "voice-scene-phrases-wrap";
    wrap.append(phrases, remove);
    row.append(scene, wrap);
    return row;
  }

  function show(state) {
    current = state;
    $("voice-enabled").checked = state.enabled;
    $("voice-allow-reset").checked = state.allow_reset;
    if (!editing($("voice-wake"))) $("voice-wake").value = joinPhrases(state.wake_words);
    for (const action of ACTIONS) {
      const input = $(`voice-${action}`);
      if (!editing(input)) input.value = joinPhrases(state.phrases[action] || []);
    }
    $("voice-reset").disabled = !state.allow_reset;
    // Строки сцен перерисовываем, только если в них сейчас не печатают.
    if (!scenesEl.contains(document.activeElement)) scenesEl.replaceChildren(...state.scenes.map(sceneRow));
    section.classList.toggle("voice-off", !state.enabled);
    showLast(state.last);
  }

  function collect() {
    const phrases = {};
    for (const action of ACTIONS) phrases[action] = splitPhrases($(`voice-${action}`).value);
    const scenes = [...scenesEl.querySelectorAll(".voice-scene")].map((row) => ({
      scene: row.querySelector(".voice-scene-name").value.trim(),
      phrases: splitPhrases(row.querySelector(".voice-scene-phrases").value),
    }));
    return {
      enabled: $("voice-enabled").checked,
      wake_words: splitPhrases($("voice-wake").value),
      allow_reset: $("voice-allow-reset").checked,
      phrases,
      // Новая строка без сцены не сохраняется, пока сцену не выберут.
      scenes: scenes.filter((item) => item.scene),
    };
  }

  async function save() {
    try {
      show(await api("POST", "/api/voice-commands", collect()));
      setStatus(statusEl, "Сохранено");
    } catch (e) {
      setStatus(statusEl, e.message, true);
      if (current) show(current);
    }
  }

  function showLast(last) {
    if (!last) {
      setStatus(lastEl, "Последняя команда: —");
      return;
    }
    const time = new Date(last.time * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    const label = last.action === "scene" ? `${LABELS.scene} «${last.scene}»` : LABELS[last.action];
    const parts = [label, `«${last.phrase}»`, time];
    if (!last.ok) parts.push(last.error || "не выполнена");
    setStatus(lastEl, `Последняя команда: ${parts.join(" · ")}`, !last.ok, last.ok);
  }

  for (const id of ["voice-enabled", "voice-allow-reset", "voice-wake", ...ACTIONS.map((a) => `voice-${a}`)]) {
    $(id).addEventListener("change", save);
  }

  $("voice-scene-add").addEventListener("click", () => {
    const row = sceneRow({ scene: "", phrases: [] });
    scenesEl.append(row);
    row.querySelector(".voice-scene-name").focus();
  });

  $("voice-scenes-load").addEventListener("click", async () => {
    const button = $("voice-scenes-load");
    button.disabled = true;
    try {
      const { scenes } = await api("GET", "/api/obs/scenes");
      $("voice-scene-names").replaceChildren(...scenes.map((name) => new Option(name, name)));
      setStatus(statusEl, `Сцен в OBS: ${scenes.length}`);
    } catch (e) {
      setStatus(statusEl, e.message, true);
    } finally {
      button.disabled = false;
    }
  });

  window.addEventListener("voice-command", (event) => {
    if (current) current.last = event.detail;
    showLast(event.detail);
  });

  api("GET", "/api/voice-commands").then(show, () => {});
})();
