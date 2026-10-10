// Звук оповещения: общий для оверлея и страницы управления (кнопка «Проверить»).
//
// Какой звук играет, по порядку: звук, выбранный в библиотеке на странице управления
// (/api/sound/file/<id>); стандартный звук пресета — файл из overlay/sounds/
// (ding.mp3, у хорька ferret.mp3); если файла нет — его синтезированная замена.
window.createDingPlayer = function createDingPlayer() {
  "use strict";

  let audioCtx = null;
  let buffer = null; // выбранный звук из библиотеки
  let volume = 1;
  let activeId = null;
  // Раскодированные звуки: id -> Promise<AudioBuffer | null>. Id у каждого файла свой,
  // поэтому звук скачивается и раскодируется один раз, а «Прослушать» играет сразу.
  const buffers = new Map();
  // Стандартные звуки: имя -> Promise<AudioBuffer | null>, и уже готовые: имя -> AudioBuffer | null
  const standards = new Map();
  const standardsReady = new Map();
  let standardName = "ding";

  function context() {
    if (!audioCtx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return null;
      audioCtx = new AC();
    }
    if (audioCtx.state === "suspended") audioCtx.resume().catch(() => {});
    return audioCtx;
  }

  async function fetchBuffer(url) {
    const resp = await fetch(url, { cache: "no-store" });
    if (!resp.ok) return null;
    const ctx = context();
    if (!ctx) return null;
    return ctx.decodeAudioData(await resp.arrayBuffer());
  }

  // Стандартный звук по имени (ding, ferret). null в ответе — играть синтезированный.
  function loadStandard(name) {
    let promise = standards.get(name);
    if (!promise) {
      promise = fetchBuffer(`/overlay/sounds/${name}.mp3`)
        .catch(() => {
          standards.delete(name); // сеть недоступна — попробуем в следующий раз
          return null;
        })
        .then((sound) => {
          standardsReady.set(name, sound);
          return sound;
        });
      standards.set(name, promise);
    }
    return promise;
  }

  // Звук из библиотеки (id) или стандартный (null).
  function load(id) {
    if (id === null) return loadStandard(standardName);
    let promise = buffers.get(id);
    if (!promise) {
      promise = fetchBuffer(`/api/sound/file/${encodeURIComponent(id)}`)
        .catch(() => null)
        .then((sound) => {
          if (!sound && buffers.get(id) === promise) buffers.delete(id); // не кешируем неудачу
          return sound;
        });
      buffers.set(id, promise);
    }
    return promise;
  }

  // state — ответ /api/sound или сообщение "sound" из WebSocket.
  // Завершается, когда выбранный звук готов к проигрыванию.
  async function apply(state) {
    volume = Math.max(0, Math.min(100, state.volume)) / 100;
    const ids = new Set((state.sounds || []).map((s) => s.id));
    for (const id of buffers.keys()) if (!ids.has(id)) buffers.delete(id);
    ids.forEach(load); // заранее, чтобы «Прослушать» не ждал загрузки
    const id = state.active || null;
    activeId = id;
    loadStandard(standardName);
    const sound = id && (await load(id));
    // Пока грузили, могли выбрать другой звук.
    if (activeId === id) buffer = sound || null;
  }

  // Стандартный звук зависит от пресета оформления (поле sound в presets.js).
  function setStandard(name) {
    standardName = SYNTH[name] ? name : "ding";
    loadStandard(standardName);
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

  // «Гуканье» хорька (dooking): серия коротких мягких «дук» с плавающей высотой,
  // как радостное квохтанье во время «военного танца».
  function synthDook(ctx, out) {
    const t = ctx.currentTime + 0.01;
    const count = 5 + Math.floor(Math.random() * 3);
    for (let i = 0; i < count; i++) {
      const start = t + i * (0.085 + Math.random() * 0.03);
      const pitch = 420 + Math.random() * 140;
      const osc = ctx.createOscillator();
      osc.type = "triangle";
      osc.frequency.setValueAtTime(pitch * 1.35, start);
      osc.frequency.exponentialRampToValueAtTime(pitch, start + 0.05);
      // Полосовой фильтр делает тон глухим, «горловым», а не свистящим.
      const filter = ctx.createBiquadFilter();
      filter.type = "bandpass";
      filter.frequency.value = pitch * 2;
      filter.Q.value = 1.5;
      const gain = ctx.createGain();
      const level = 0.7 + Math.random() * 0.3;
      gain.gain.setValueAtTime(0.0001, start);
      gain.gain.exponentialRampToValueAtTime(level, start + 0.008);
      gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.07);
      osc.connect(filter).connect(gain).connect(out);
      osc.start(start);
      osc.stop(start + 0.1);
    }
  }

  // Синтезированная замена стандартного звука, если файла нет: [функция, громкость]
  const SYNTH = {
    ding: [synthDing, 0.3], // без ослабления звон слишком громкий
    ferret: [synthDook, 0.9],
  };

  function play(sound) {
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
      const [synth, level] = SYNTH[standardName];
      out.gain.value = level * volume;
      synth(ctx, out);
    }
  }

  // Выбранный звук; если он из библиотеки, но не загрузился, — стандартный.
  function playActive() {
    play((activeId && buffer) || standardsReady.get(standardName) || null);
  }

  // Прослушать звук из библиотеки (id) или стандартный (null), не меняя выбранный.
  async function preview(id) {
    context(); // запускаем звук сразу по клику, пока файл догружается
    play((id && (await load(id))) || (await load(null)));
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

  return { apply, play: playActive, preview, setStandard, canDecode, setVolume: (v) => (volume = v / 100) };
};
