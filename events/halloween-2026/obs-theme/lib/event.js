// EVENT: halloween-2026 — ВРЕМЕННО. Вся папка events/halloween-2026/obs-theme удаляется после 1 ноября 2026.
//
// Общее для всех страниц темы:
//  - HW.active: идёт ли евент. После HW.EVENT_ENDS страницы ничего не показывают,
//    даже если их забыли убрать из OBS. ?force=1 показывает тему в любой день (для проверки).
//  - HW.bus: откуда приходят команды. Обычные скрипты, без модулей: так страницы
//    открываются и двойным щелчком (file://), и в OBS.
(function () {
  "use strict";

  // Конец евента по местному времени: 2 ноября 2026, 00:00. До этого момента тема работает.
  const EVENT_ID = "halloween-2026";
  const EVENT_ENDS = new Date(2026, 10, 2, 0, 0, 0);

  const params = new URLSearchParams(location.search);
  const active = params.has("force") || Date.now() < EVENT_ENDS.getTime();
  if (!active) document.documentElement.classList.add("event-over");

  function param(name, fallback) {
    const v = params.get(name);
    return v === null || v === "" ? fallback : v;
  }
  function numParam(name, fallback) {
    const v = parseFloat(params.get(name));
    return Number.isFinite(v) ? v : fallback;
  }

  // --- Шина команд ---
  //
  // Команда — объект { action: "spider" | "alert" | "screen" | ..., ...данные }.
  // Источники:
  //  1. Streamer.bot WebSocket Server (по умолчанию ws://127.0.0.1:8080/):
  //     события Twitch/YouTube и свои команды через CPH.WebsocketBroadcastJson.
  //  2. OBS WebSocket 5 (ws://127.0.0.1:4455): запрос BroadcastCustomEvent из Streamer.bot,
  //     Touch Portal, Stream Deck и чего угодно, что умеет OBS WebSocket.
  //  3. postMessage от страницы предпросмотра index.html.
  //  4. Видимость источника в OBS: показали источник — страница получает action "shown".
  const handlers = {};
  function on(action, fn) { (handlers[action] = handlers[action] || []).push(fn); }
  function emit(msg) {
    if (!active || !msg || typeof msg !== "object") return;
    // Чужие команды (не для этой темы) игнорируем, если в них есть поле overlay.
    if (msg.overlay && msg.overlay !== "halloween" && msg.overlay !== EVENT_ID) return;
    const list = (handlers[msg.action] || []).concat(handlers["*"] || []);
    for (const fn of list) {
      try { fn(msg); } catch (e) { console.error("[halloween]", e); }
    }
  }

  function reconnecting(name, url, onOpen, onMessage) {
    let delay = 2000;
    function connect() {
      let ws;
      try { ws = new WebSocket(url); } catch (e) { return; }
      ws.onopen = () => { delay = 2000; console.info(`[halloween] ${name}: подключено`); onOpen(ws); };
      ws.onmessage = (e) => {
        let data;
        try { data = JSON.parse(e.data); } catch (_) { return; }
        onMessage(ws, data);
      };
      ws.onclose = (e) => {
        if (e.code === 4009) { console.warn(`[halloween] ${name}: неверный пароль, переподключение отключено`); return; }
        setTimeout(connect, delay);
        delay = Math.min(delay * 2, 30000);
      };
    }
    connect();
  }

  // Streamer.bot: подписываемся на свои команды и на события, из которых делаем алерты.
  const SB_EVENTS = {
    General: ["Custom"],
    Twitch: ["Follow", "Sub", "ReSub", "GiftSub", "GiftBomb", "Cheer", "Raid"],
    YouTube: ["NewSubscriber", "SuperChat", "SuperSticker", "NewSponsor", "MembershipGift"],
  };
  function startStreamerbot(url) {
    reconnecting("Streamer.bot", url, (ws) => {
      ws.send(JSON.stringify({ request: "Subscribe", id: "hw-sub", events: SB_EVENTS }));
    }, (ws, data) => {
      if (!data.event) {
        // CPH.WebsocketBroadcastJson в некоторых версиях приходит без обёртки.
        if (data.action) emit(data);
        return;
      }
      const src = data.event.source, type = data.event.type, d = data.data || {};
      if (src === "General" && type === "Custom") {
        emit(typeof d === "string" ? safeParse(d) : d);
        return;
      }
      const alert = HW.alertFromPlatform(src, type, d);
      if (alert) emit(alert);
    });
  }

  // OBS WebSocket 5: Hello → Identify (с паролем, если он задан) → события CustomEvent.
  async function sha256b64(text) {
    const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
    return btoa(String.fromCharCode(...new Uint8Array(buf)));
  }
  function startObs(url, password) {
    reconnecting("OBS WebSocket", url, () => {}, async (ws, msg) => {
      if (msg.op === 0) {
        const identify = { rpcVersion: 1, eventSubscriptions: 1 /* General: CustomEvent */ };
        const auth = msg.d && msg.d.authentication;
        if (auth) {
          if (!password) { console.warn("[halloween] OBS WebSocket просит пароль: добавьте ?obspass=..."); ws.close(); return; }
          const secret = await sha256b64(password + auth.salt);
          identify.authentication = await sha256b64(secret + auth.challenge);
        }
        ws.send(JSON.stringify({ op: 1, d: identify }));
      } else if (msg.op === 5 && msg.d.eventType === "CustomEvent") {
        emit(msg.d.eventData);
      }
    });
  }

  function safeParse(s) { try { return JSON.parse(s); } catch (_) { return null; } }

  function start() {
    if (!active) return;
    if (param("sb", "on") !== "off") startStreamerbot(param("sb", "on") === "on" ? "ws://127.0.0.1:8080/" : param("sb"));
    if (param("obs", "on") !== "off") startObs(param("obs", "on") === "on" ? "ws://127.0.0.1:4455" : param("obs"), param("obspass", ""));
    window.addEventListener("message", (e) => emit(e.data));
    // OBS сообщает браузерному источнику, что его показали или скрыли в сцене.
    window.addEventListener("obsSourceVisibleChanged", (e) => { if (e.detail && e.detail.visible) emit({ action: "shown" }); });
  }

  // --- Алерты из событий платформ ---
  // Поля событий Streamer.bot менялись между версиями, поэтому ищем имя в нескольких местах.
  function pick(obj, paths) {
    for (const p of paths) {
      let v = obj;
      for (const k of p.split(".")) v = v == null ? undefined : v[k];
      if (v !== undefined && v !== null && v !== "") return v;
    }
    return "";
  }
  const NAME = ["user.name", "user.display_name", "user_name", "displayName", "display_name", "userName",
                "user.login", "user_login", "from_broadcaster_user_name", "message.displayName", "author.name"];
  function alertFromPlatform(src, type, d) {
    const name = String(pick(d, NAME) || "Аноним");
    const text = pick(d, ["message.message", "text", "message", "comment"]);
    const msg = typeof text === "string" ? text : "";
    const map = {
      "Twitch.Follow": { kind: "follow" },
      "Twitch.Sub": { kind: "sub" },
      "Twitch.ReSub": { kind: "sub", amount: pick(d, ["cumulativeMonths", "cumulative_months", "months"]) },
      "Twitch.GiftSub": { kind: "gift", amount: 1 },
      "Twitch.GiftBomb": { kind: "gift", amount: pick(d, ["gifts", "total", "amount"]) },
      "Twitch.Cheer": { kind: "cheer", amount: pick(d, ["bits", "message.bits", "amount"]) },
      "Twitch.Raid": { kind: "raid", amount: pick(d, ["viewers", "viewerCount", "viewer_count"]) },
      "YouTube.NewSubscriber": { kind: "follow" },
      "YouTube.NewSponsor": { kind: "sub" },
      "YouTube.MembershipGift": { kind: "gift", amount: pick(d, ["count", "amount"]) },
      "YouTube.SuperChat": { kind: "donation", amount: pick(d, ["amount", "amountDisplayString"]) },
      "YouTube.SuperSticker": { kind: "donation", amount: pick(d, ["amount", "amountDisplayString"]) },
    };
    const base = map[`${src}.${type}`];
    if (!base) return null;
    return Object.assign({ action: "alert", user: name, message: msg, platform: src.toLowerCase() }, base);
  }

  window.HW = { EVENT_ID, EVENT_ENDS, active, params, param, numParam, on, emit, start, alertFromPlatform };
})();
