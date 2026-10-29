// Живые субтитры для OBS: /overlay/?show=subtitles (сервер — app/subtitles.py).
// Промежуточный текст обновляется по ходу речи, окончательный держится несколько секунд и гаснет.
// Параметры: &lines=2 (1–3 строки), &size=48 (px, без него — от размера окна),
// &color=ffffff, &hold=4 (секунд держать фразу), &box=1 (плашка под текстом).
(() => {
  "use strict";

  const params = new URLSearchParams(location.search);
  if (params.get("show") !== "subtitles") return;
  window.SUBTITLES_OVERLAY = true; // overlay.js тогда не рисует счётчик

  const RECONNECT_MS = 2000;
  const LINE_HEIGHT = 1.25; // как --sub-line в subtitles.css
  const AUTO_WIDTH_CHARS = 26; // без ?size в строку шириной в окно влезает примерно столько букв

  const clamp = (value, min, max) => Math.min(Math.max(value, min), max);
  const lines = clamp(parseInt(params.get("lines"), 10) || 2, 1, 3);
  const sizeParam = parseInt(params.get("size"), 10);
  const holdParam = parseFloat(params.get("hold"));
  const holdMs = (holdParam > 0 ? clamp(holdParam, 1, 30) : 4) * 1000;
  const colorRaw = (params.get("color") || "").replace(/^#/, "");

  const root = document.documentElement;
  root.removeAttribute("data-preset"); // у субтитров своё оформление, без пресетов счётчика
  root.setAttribute("data-show", "subtitles");
  if (params.get("box") === "1") root.setAttribute("data-sub-box", "");
  root.style.setProperty("--sub-lines", lines);
  if (/^([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$/i.test(colorRaw)) root.style.setProperty("--sub-color", "#" + colorRaw);

  function fitSize() {
    const px = sizeParam > 0
      ? clamp(sizeParam, 12, 300)
      // Без размера в адресе: строки занимают окно по высоте, но не мельче и не шире разумного.
      : clamp(Math.min(innerWidth / AUTO_WIDTH_CHARS, innerHeight / (lines * LINE_HEIGHT + 0.5)), 16, 160);
    root.style.setProperty("--sub-size", Math.floor(px) + "px");
  }
  fitSize();
  window.addEventListener("resize", fitSize);

  const wrap = document.createElement("div");
  wrap.className = "subtitles";
  const box = document.createElement("div");
  box.className = "subtitles-box empty";
  const textEl = document.createElement("span");
  box.append(textEl);
  wrap.append(box);
  document.body.append(wrap); // скрипт подключён в конце <body>

  let fadeTimer = null;

  function clear() {
    clearTimeout(fadeTimer);
    fadeTimer = null;
    textEl.textContent = "";
    box.className = "subtitles-box empty";
  }

  function show(text, final) {
    clearTimeout(fadeTimer);
    fadeTimer = null;
    textEl.textContent = text;
    box.className = "subtitles-box" + (final ? "" : " partial");
    if (!final) return;
    // Окончательная фраза держится holdMs и плавно гаснет (opacity в CSS), потом текст убираем.
    fadeTimer = setTimeout(() => {
      box.classList.add("faded");
      fadeTimer = setTimeout(clear, 700);
    }, holdMs);
  }

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onmessage = (event) => {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch (e) {
        return;
      }
      if (msg.type === "subtitle" && typeof msg.text === "string") show(msg.text, msg.final);
      else if (msg.type === "subtitles" && !msg.enabled) clear();
      else if (msg.type === "pause" && msg.paused) clear();
    };
    ws.onclose = () => {
      clear();
      setTimeout(connect, RECONNECT_MS);
    };
    ws.onerror = () => ws.close();
  }

  connect();
})();
