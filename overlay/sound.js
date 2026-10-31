// Звук оповещения: общий для оверлея и страницы управления (кнопка «Проверить»).
//
// Какой звук играет, по порядку: звук, выбранный в библиотеке на странице управления
// (/api/sound/file/<id>); стандартный звук пресета — синтезированный звон, у личного оформления —
// файл из набора (/overlay/custom/<id>/<файл>); если файла нет — звон.
// Во время события (app/events.py) в списке есть и его звуки (поле event_sounds) из overlay/sounds/<событие>/.
// Режим «рандом» (поле random): на каждый мат и проклятие играет случайный звук из отмеченных (pool),
// "standard" в нём — стандартный звук.
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
  // Звуки события: id -> адрес файла, и уже готовые звуки: id -> AudioBuffer
  const eventUrls = new Map();
  const ready = new Map();
  let pool = []; // режим «рандом»: id отмеченных звуков; пусто — режим выключен

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

  // Несколько файлов: готовые из них списком (играет случайный), ни одного — null.
  async function fetchAll(files) {
    const sounds = await Promise.all(files.map((f) => fetchBuffer(`/overlay/sounds/${f}`).catch(() => null)));
    const loaded = sounds.filter(Boolean);
    return loaded.length ? loaded : null;
  }

  // Стандартный звук по имени (ding) или адресу. null в ответе — играть синтезированный.
  function loadStandard(name) {
    let promise = standards.get(name);
    if (!promise) {
      const std = STANDARD[name];
      const url = std ? std.file && `/overlay/sounds/${std.file}` : name;
      // Звук без файла (звон) только синтезируется: не запрашиваем то, чего нет.
      promise = (std && std.files ? fetchAll(std.files) : url ? fetchBuffer(url) : Promise.resolve(null))
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

  // Звук из библиотеки или события (id) или стандартный (null).
  function load(id) {
    if (id === null) return loadStandard(standardName);
    const url = eventUrls.get(id) || `/api/sound/file/${encodeURIComponent(id)}`;
    let promise = buffers.get(id);
    if (!promise) {
      promise = fetchBuffer(url)
        .catch(() => null)
        .then((sound) => {
          if (!sound && buffers.get(id) === promise) buffers.delete(id); // не кешируем неудачу
          if (sound) ready.set(id, sound);
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
    eventUrls.clear();
    for (const s of state.event_sounds || []) eventUrls.set(s.id, s.url);
    const ids = new Set((state.sounds || []).map((s) => s.id).concat([...eventUrls.keys()]));
    for (const id of buffers.keys()) if (!ids.has(id)) buffers.delete(id);
    for (const id of ready.keys()) if (!ids.has(id)) ready.delete(id);
    ids.forEach(load); // заранее, чтобы «Прослушать» не ждал загрузки
    const id = state.active || null;
    activeId = id;
    pool = state.random ? state.pool || [] : [];
    loadStandard(standardName);
    const sound = id && (await load(id));
    // Пока грузили, могли выбрать другой звук.
    if (activeId === id) buffer = sound || null;
  }

  // Стандартный звук зависит от пресета оформления (поле sound в presets.js).
  function setStandard(name) {
    const own = typeof name === "string" && name.startsWith("/overlay/custom/");
    standardName = STANDARD[name] || own ? name : "ding";
    loadStandard(standardName);
    if (standardName === "halloween") loadStandard("curse"); // смех проклятия — заранее
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

  // Особое число: цензурное «пиии» на то время, пока число запикано (overlay.js, celebrate)
  function synthBleep(ctx, out) {
    const t = ctx.currentTime + 0.6;
    const osc = ctx.createOscillator();
    osc.type = "sine";
    osc.frequency.value = 1000;
    const gain = ctx.createGain();
    gain.gain.setValueAtTime(0.0001, t);
    gain.gain.exponentialRampToValueAtTime(1, t + 0.01);
    gain.gain.setValueAtTime(1, t + 0.98);
    gain.gain.exponentialRampToValueAtTime(0.0001, t + 1.03);
    osc.connect(gain).connect(out);
    osc.start(t);
    osc.stop(t + 1.05);
  }

  // --- Событие «Хеллоуин» (app/events.py): синтезированные замены, если файлы не загрузились ---

  // Жуткий завывающий тон, как терменвокс, с дрожью и спадом вниз
  function synthSpooky(ctx, out) {
    const t = ctx.currentTime + 0.01;
    const osc = ctx.createOscillator();
    osc.type = "sawtooth";
    osc.frequency.setValueAtTime(880, t);
    osc.frequency.exponentialRampToValueAtTime(220, t + 1.1);
    const wobble = ctx.createOscillator();
    wobble.frequency.value = 7;
    const depth = ctx.createGain();
    depth.gain.value = 40;
    wobble.connect(depth).connect(osc.frequency);
    const filter = ctx.createBiquadFilter();
    filter.type = "lowpass";
    filter.frequency.value = 1800;
    const gain = ctx.createGain();
    gain.gain.setValueAtTime(0.0001, t);
    gain.gain.exponentialRampToValueAtTime(1, t + 0.04);
    gain.gain.exponentialRampToValueAtTime(0.0001, t + 1.2);
    osc.connect(filter).connect(gain).connect(out);
    osc.start(t);
    wobble.start(t);
    osc.stop(t + 1.25);
    wobble.stop(t + 1.25);
  }

  // Проклятие: три низких удара, как колокол на кладбище
  function synthCurse(ctx, out) {
    const t = ctx.currentTime + 0.01;
    [0, 0.45, 0.9].forEach((delay) => bell(ctx, out, 98, t + delay, 1)); // G2
  }

  // Звуки события Хеллоуин (overlay/sounds/halloween/, источники — в README.md там же)
  const HALLOWEEN_SCREAMS = [
    "halloween/scream-stab.ogg",
    "halloween/ghost-shriek.ogg",
    "halloween/banshee.ogg",
    "halloween/jumpscare-hit.ogg",
    "halloween/jumpscare-low.ogg",
    "halloween/ghost-moan.ogg",
    "halloween/witch-cackle.ogg",
    "halloween/demon-laugh.ogg",
    "halloween/door-creak.ogg",
  ];

  // Стандартные звуки: файл в overlay/sounds/ (необязательно) и синтезированная замена,
  // которая играет, если файла нет или он не загрузился. files — несколько файлов, играет случайный.
  const STANDARD = {
    ding: { file: null, synth: synthDing, level: 0.3 }, // без ослабления звон слишком громкий
    halloween: { files: HALLOWEEN_SCREAMS, synth: synthSpooky, level: 0.25 },
    curse: { file: "halloween/evil-laugh.ogg", synth: synthCurse, level: 0.4 },
  };

  function pick(list) {
    return list[Math.floor(Math.random() * list.length)];
  }

  // Готовый стандартный звук; из нескольких файлов — случайный.
  function standardBuffer(name) {
    const sound = standardsReady.get(name) || null;
    return Array.isArray(sound) ? pick(sound) : sound;
  }

  // Режим «рандом»: случайный из отмеченных. "standard" — стандартный звук;
  // не загруженный ещё звук тоже даёт стандартный, а не тишину.
  function randomPick() {
    const id = pick(pool);
    if (id === "standard") return standardBuffer(standardName);
    return ready.get(id) || standardBuffer(standardName);
  }

  // name — стандартный звук, чья синтезированная замена играет без sound.
  function play(sound, name = standardName) {
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
      const { synth, level } = STANDARD[name] || STANDARD.ding;
      out.gain.value = level * volume;
      synth(ctx, out);
    }
  }

  // Выбранный звук; если он из библиотеки, но не загрузился, — стандартный.
  function playActive() {
    if (pool.length) return play(randomPick());
    play((activeId && buffer) || standardBuffer(standardName));
  }

  // Проклятие события (каждое 13-е ругательство): в режиме «рандом» — случайный из отмеченных,
  // иначе злой смех, без файла — удары колокола.
  function playCurse() {
    if (pool.length) return play(randomPick());
    loadStandard("curse");
    play(standardBuffer("curse"), "curse");
  }

  function playBleep() {
    const ctx = context();
    if (!ctx || volume === 0) return;
    const out = ctx.createGain();
    out.gain.value = 0.3 * volume;
    out.connect(ctx.destination);
    synthBleep(ctx, out);
  }

  // Прослушать звук из библиотеки (id) или стандартный (null), не меняя выбранный.
  async function preview(id) {
    context(); // запускаем звук сразу по клику, пока файл догружается
    const sound = (id && (await load(id))) || (await load(null));
    play(Array.isArray(sound) ? pick(sound) : sound);
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

  return { apply, play: playActive, playBleep, playCurse, preview, setStandard, canDecode, setVolume: (v) => (volume = v / 100) };
};
