// Звук оповещения: общий для оверлея и страницы управления (кнопка «Проверить»).
//
// Какой звук играет, по порядку: звук, выбранный в библиотеке на странице управления
// (/api/sound/file/<id>); файл overlay/sounds/ding.mp3; синтезированный звон.
window.createDingPlayer = function createDingPlayer() {
  "use strict";

  let audioCtx = null;
  let buffer = null;
  let volume = 1;
  let loadedVersion = null;

  function context() {
    if (!audioCtx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return null;
      audioCtx = new AC();
    }
    if (audioCtx.state === "suspended") audioCtx.resume().catch(() => {});
    return audioCtx;
  }

  // Стандартный звук: overlay/sounds/ding.mp3 или, если его нет, синтезированный (null).
  async function standardBuffer() {
    try {
      return await fetchBuffer("/overlay/sounds/ding.mp3");
    } catch (e) {
      return null;
    }
  }

  function soundUrl(id, version) {
    return `/api/sound/file/${encodeURIComponent(id)}?v=${version}`;
  }

  async function fetchBuffer(url) {
    const resp = await fetch(url, { cache: "no-store" });
    if (!resp.ok) return null;
    const ctx = context();
    if (!ctx) return null;
    return ctx.decodeAudioData(await resp.arrayBuffer());
  }

  // state — ответ /api/sound или сообщение "sound" из WebSocket.
  async function apply(state) {
    volume = Math.max(0, Math.min(100, state.volume)) / 100;
    if (state.version === loadedVersion) return;
    loadedVersion = state.version;
    let next = null;
    try {
      next = state.active ? await fetchBuffer(soundUrl(state.active, state.version)) : null;
    } catch (e) {
      next = null; // файл не прочитался — будет стандартный звук
    }
    if (!next) next = await standardBuffer();
    // Пока грузили, могла прийти ещё более новая версия.
    if (loadedVersion === state.version) buffer = next;
  }

  // Один удар колокольчика: основной тон и негармонический обертон с затуханием
  function bell(ctx, out, freq, start, level) {
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
      gain.gain.exponentialRampToValueAtTime(amp * level, start + 0.005);
      gain.gain.exponentialRampToValueAtTime(0.0001, start + dur);
      osc.connect(gain).connect(out);
      osc.start(start);
      osc.stop(start + dur + 0.05);
    }
  }

  function synthDing(ctx, out) {
    const t = ctx.currentTime + 0.01;
    bell(ctx, out, 1318.5, t, 1.0); // E6
    bell(ctx, out, 1975.5, t + 0.09, 0.8); // B6
    bell(ctx, out, 2637.0, t + 0.18, 0.5); // E7
  }

  function play(sound = buffer) {
    const ctx = context();
    if (!ctx || volume === 0) return;
    const out = ctx.createGain();
    out.connect(ctx.destination);
    if (sound) {
      out.gain.value = volume;
      const src = ctx.createBufferSource();
      src.buffer = sound;
      src.connect(out);
      src.start();
    } else {
      out.gain.value = 0.3 * volume; // без ослабления синтезированный звон слишком громкий
      synthDing(ctx, out);
    }
  }

  // Прослушать звук из библиотеки (id) или стандартный (null), не меняя выбранный.
  async function preview(id) {
    let sound = null;
    try {
      sound = id ? await fetchBuffer(soundUrl(id, Date.now())) : await standardBuffer();
    } catch (e) {
      sound = null;
    }
    play(sound);
  }

  // Проверяет, что файл можно проиграть, до отправки на сервер.
  async function canDecode(arrayBuffer) {
    const ctx = context();
    if (!ctx) return false;
    try {
      await ctx.decodeAudioData(arrayBuffer.slice(0));
      return true;
    } catch (e) {
      return false;
    }
  }

  // В обычном браузере звук разрешается только после клика по странице (в OBS это не нужно)
  document.addEventListener("pointerdown", () => context());

  return { apply, play: () => play(), preview, canDecode, setVolume: (v) => (volume = v / 100) };
};
