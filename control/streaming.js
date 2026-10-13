// Раздел «Трансляции»: чат Twitch и YouTube. Отдельный файл, чтобы не пересекаться с control.js.
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const section = $("streaming-section");
  if (!section) return;

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
    if (detail === "Not Found" || detail === "Method Not Allowed") {
      throw new Error("Сервер не знает этой команды: перезапустите приложение, оно запущено со старой версией");
    }
    throw new Error((typeof detail === "string" && detail) || `Ошибка сервера (${resp.status})`);
  }

  function setStatus(node, text, kind) {
    node.textContent = text;
    node.classList.toggle("error", kind === "error");
    node.classList.toggle("ok", kind === "ok");
  }

  const twitchStatus = $("twitch-status");
  const youtubeStatus = $("youtube-status");
  const saveStatus = $("streaming-save-status");

  const ids = {
    twitch: {
      enabled: "twitch-enabled", channel: "twitch-channel", command: "twitch-command", reply: "twitch-reply",
      cooldown: "twitch-cooldown", mod_commands: "twitch-mod-commands", announce_milestones: "twitch-announce-milestones",
      announce_text: "twitch-announce-text", announce_every: "twitch-announce-every",
      bits_per_swear: "twitch-bits", markers: "twitch-markers",
    },
    youtube: {
      enabled: "youtube-enabled", video: "youtube-video", command: "youtube-command",
      mod_commands: "youtube-mod-commands", superchat_swears: "youtube-superchat",
    },
  };

  // Поля, которые пользователь сейчас правит, не перезаписываем приходящим состоянием.
  function put(id, value) {
    const node = $(id);
    if (document.activeElement === node) return;
    if (node.type === "checkbox") node.checked = Boolean(value);
    else node.value = value === 0 ? "" : value;
  }

  function line(node, state, labels) {
    if (!state.enabled) return setStatus(node, "");
    if (state.status === "connected") return setStatus(node, labels.connected(state), "ok");
    if (state.status === "error") return setStatus(node, state.error || "Ошибка связи", "error");
    return setStatus(node, "Подключаюсь…");
  }

  function show(state) {
    for (const platform of ["twitch", "youtube"]) {
      const s = state[platform];
      if (!s) continue;
      for (const [key, id] of Object.entries(ids[platform])) put(id, s[key]);
    }
    $("twitch-token").placeholder = state.twitch.has_token ? "Токен сохранён (оставьте пустым, чтобы не менять)" : "Токен доступа Twitch";
    $("youtube-key").placeholder = state.youtube.has_token ? "Ключ сохранён (оставьте пустым, чтобы не менять)" : "Ключ API YouTube";
    line(twitchStatus, state.twitch, {
      connected: (s) => (s.login ? `Чат Twitch на связи (${s.login})` : "Чат Twitch на связи"),
    });
    line(youtubeStatus, state.youtube, {
      connected: (s) => (s.title ? `Чат YouTube на связи: ${s.title}` : "Чат YouTube на связи"),
    });
    $("twitch-test").disabled = state.twitch.status !== "connected";
    $("twitch-markers").disabled = state.twitch.status === "connected" && !state.twitch.can_mark;
  }

  function number(id) {
    return Math.max(0, Math.floor(Number($(id).value) || 0));
  }

  function collect() {
    return {
      twitch: {
        enabled: $("twitch-enabled").checked,
        channel: $("twitch-channel").value.trim(),
        token: $("twitch-token").value.trim() || null, // пусто — оставить сохранённый
        command: $("twitch-command").value.trim() || "!маты",
        reply: $("twitch-reply").value,
        cooldown: number("twitch-cooldown"),
        mod_commands: $("twitch-mod-commands").checked,
        announce_milestones: $("twitch-announce-milestones").checked,
        announce_text: $("twitch-announce-text").value,
        announce_every: number("twitch-announce-every"),
        bits_per_swear: number("twitch-bits"),
        markers: $("twitch-markers").checked,
      },
      youtube: {
        enabled: $("youtube-enabled").checked,
        video: $("youtube-video").value.trim(),
        api_key: $("youtube-key").value.trim() || null,
        command: $("youtube-command").value.trim() || "!маты",
        mod_commands: $("youtube-mod-commands").checked,
        superchat_swears: number("youtube-superchat"),
      },
    };
  }

  $("streaming-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = $("streaming-save");
    button.disabled = true;
    setStatus(saveStatus, "Сохраняю…");
    try {
      const state = await api("POST", "/api/streaming", collect());
      $("twitch-token").value = "";
      $("youtube-key").value = "";
      show(state);
      setStatus(saveStatus, "Сохранено", "ok");
    } catch (e) {
      setStatus(saveStatus, e.message, "error");
    } finally {
      button.disabled = false;
    }
  });

  $("twitch-test").addEventListener("click", async () => {
    const button = $("twitch-test");
    button.disabled = true;
    try {
      await api("POST", "/api/streaming/twitch/test");
      setStatus(saveStatus, "Сообщение отправлено в чат", "ok");
    } catch (e) {
      setStatus(saveStatus, e.message, "error");
    } finally {
      button.disabled = false;
    }
  });

  // Сообщение WebSocket {"type": "streaming", "platform": ..., status, error, ...}: control.js передаёт его сюда.
  let current = null;
  window.streamingUpdate = (msg) => {
    if (!current || !current[msg.platform]) return;
    const { type, platform, ...link } = msg;
    current[platform] = { ...current[platform], ...link };
    show(current);
  };

  async function load() {
    try {
      current = await api("GET", "/api/streaming");
      show(current);
    } catch (e) {
      setStatus(saveStatus, e.message, "error");
    }
  }
  load();
})();
