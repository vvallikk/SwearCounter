(() => {
  "use strict";

  const RECONNECT_MS = 2000;

  // --- Параметры из адреса: ?size=120&color=ffffff&mute=1 ---
  const params = new URLSearchParams(location.search);
  const size = Math.min(Math.max(parseInt(params.get("size"), 10) || 120, 16), 1000);
  const colorRaw = (params.get("color") || "ffffff").replace(/^#/, "");
  const color = /^([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$/i.test(colorRaw) ? "#" + colorRaw : "#ffffff";
  const muted = params.get("mute") === "1";

  document.documentElement.style.setProperty("--size", size + "px");
  document.documentElement.style.setProperty("--color", color);

  const counterEl = document.getElementById("counter");
  const valueEl = document.getElementById("value");
  const glowEl = document.getElementById("glow");

  function setCount(n) {
    valueEl.textContent = String(n);
  }

  // --- Анимации ---
  function playIncrementAnimation(delta) {
    // Подпрыгивание числа
    valueEl.animate(
      [
        { transform: "translateY(0) scale(1)" },
        { transform: "translateY(-12%) scale(1.3)", offset: 0.3 },
        { transform: "translateY(0) scale(0.92)", offset: 0.65 },
        { transform: "translateY(0) scale(1)" },
      ],
      { duration: 550, easing: "ease-out" }
    );

    // Вспышка
    glowEl.animate(
      [
        { opacity: 0, transform: "scale(0.6)" },
        { opacity: 0.6, transform: "scale(1)", offset: 0.2 },
        { opacity: 0, transform: "scale(1.3)" },
      ],
      { duration: 700, easing: "ease-out" }
    );

    // «+1», уплывающее вверх
    const plus = document.createElement("span");
    plus.className = "plus";
    plus.textContent = "+" + delta;
    counterEl.appendChild(plus);
    const anim = plus.animate(
      [
        { transform: "translate(-50%, 0) scale(0.6)", opacity: 0 },
        { transform: "translate(-50%, -60%) scale(1.1)", opacity: 1, offset: 0.2 },
        { transform: "translate(-50%, -160%) scale(1)", opacity: 0 },
      ],
      { duration: 1200, easing: "ease-out" }
    );
    anim.onfinish = () => plus.remove();
  }

  // --- Звук ---
  let audioCtx = null;
  let dingBuffer = null; // загруженный sounds/ding.mp3, если он есть

  function getAudioContext() {
    if (!audioCtx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return null;
      audioCtx = new AC();
    }
    if (audioCtx.state === "suspended") audioCtx.resume().catch(() => {});
    return audioCtx;
  }

  async function loadDingFile() {
    try {
      const resp = await fetch("sounds/ding.mp3", { cache: "no-store" });
      if (!resp.ok) return; // файла нет — будем синтезировать звук
      const ctx = getAudioContext();
      if (!ctx) return;
      dingBuffer = await ctx.decodeAudioData(await resp.arrayBuffer());
    } catch (e) {
      dingBuffer = null;
    }
  }

  // Один удар колокольчика: основной тон и негармонический обертон с затуханием
  function bell(ctx, out, freq, start, volume) {
    const partials = [
      [1, 1, 1.4],
      [2.76, 0.25, 0.6],
    ];
    for (const [mul, amp, dur] of partials) {
      const osc = ctx.createOscillator();
      osc.type = "sine";
      osc.frequency.value = freq * mul;
      const gain = ctx.createGain();
      gain.gain.setValueAtTime(0.0001, start);
      gain.gain.exponentialRampToValueAtTime(amp * volume, start + 0.005);
      gain.gain.exponentialRampToValueAtTime(0.0001, start + dur);
      osc.connect(gain).connect(out);
      osc.start(start);
      osc.stop(start + dur + 0.05);
    }
  }

  function synthDing(ctx) {
    const out = ctx.createGain();
    out.gain.value = 0.3;
    out.connect(ctx.destination);
    const t = ctx.currentTime + 0.01;
    bell(ctx, out, 1318.5, t, 1.0); // E6
    bell(ctx, out, 1975.5, t + 0.09, 0.8); // B6
    bell(ctx, out, 2637.0, t + 0.18, 0.5); // E7
  }

  function playDing() {
    if (muted) return;
    const ctx = getAudioContext();
    if (!ctx) return;
    if (dingBuffer) {
      const src = ctx.createBufferSource();
      src.buffer = dingBuffer;
      src.connect(ctx.destination);
      src.start();
    } else {
      synthDing(ctx);
    }
  }

  // В обычном браузере звук разрешается только после клика по странице (в OBS это не нужно)
  document.addEventListener("pointerdown", () => getAudioContext());

  // --- WebSocket с автопереподключением ---
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
      if (msg.type === "state") {
        setCount(msg.count);
      } else if (msg.type === "increment") {
        setCount(msg.count);
        playIncrementAnimation(msg.delta || 1);
        playDing();
      }
    };
    ws.onclose = () => setTimeout(connect, RECONNECT_MS);
    ws.onerror = () => ws.close();
  }

  if (!muted) loadDingFile();
  connect();
})();
