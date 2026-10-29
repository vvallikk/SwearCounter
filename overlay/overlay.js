(() => {
  "use strict";

  const RECONNECT_MS = 2000;
  // Подгонка под окно: число не уже MIN_DIGITS цифр и занимает такую долю окна,
  // чтобы рядом осталось место для «+N» и увеличения при анимации.
  const FIT_BASE_PX = 100;
  const FIT_MIN_DIGITS = 3;
  const FIT_WIDTH = 0.9;
  const FIT_HEIGHT = 0.7;
  const PREVIEW_INTERVAL_MS = 2500;
  const PREVIEW_COUNT = 42;
  const LABEL_RATIO = 0.4; // размер подписи от размера числа

  // --- Параметры из адреса: ?size=120&color=ffffff&mute=1&preset=neon&preview=1&counter=c1 ---
  const params = new URLSearchParams(location.search);
  // Без ?size число растягивается под размер окна (источника в OBS).
  const sizeParam = parseInt(params.get("size"), 10);
  const autoSize = !(sizeParam > 0);
  let size = autoSize ? 120 : Math.min(Math.max(sizeParam, 16), 1000);
  const colorRaw = (params.get("color") || "").replace(/^#/, "");
  // Явный цвет перекрывает цвет пресета; без него берётся цвет пресета.
  const colorOverride = /^([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$/i.test(colorRaw) ? "#" + colorRaw : null;
  const muted = params.get("mute") === "1";
  // ?preview=1 — предпросмотр для страницы управления: без WebSocket и без звука.
  const preview = params.get("preview") === "1";
  // ?preset=<id> закрепляет пресет; без него пресет приходит по WebSocket.
  const fixedPreset = params.get("preset") || null;
  // ?show=timer — вместо счёта таймер «без мата», ?show=goal — сколько осталось до цели.
  // Подпись у них своя: ?label=Без мата:
  const showTimer = params.get("show") === "timer";
  const showGoal = params.get("show") === "goal";
  const ownLabel = showTimer || showGoal;
  const timerLabel = params.get("label") || "";
  // ?counter=<id> — дополнительный счётчик со своим счётом, оформлением и подписью.
  const counterId = params.get("counter") || null;

  const root = document.documentElement;
  // Размер числа и подписи со страницы управления: проценты от базового размера.
  // baseSize — размер после подгонки под окно; size — число с учётом своего масштаба.
  let baseSize = size;
  let numberScale = 1;
  let labelScale = 1;
  function setSize(px) {
    baseSize = px;
    size = px * numberScale;
    root.style.setProperty("--size", size + "px");
    root.style.setProperty("--label-size", px * LABEL_RATIO * labelScale + "px");
  }
  setSize(size);

  function applyScale(msg) {
    const number = Number(msg.number_scale) / 100;
    const label = Number(msg.label_scale) / 100;
    if (!(number > 0) || !(label > 0)) return; // сервер старее страницы
    if (number === numberScale && label === labelScale) return;
    numberScale = number;
    labelScale = label;
    if (autoSize) fitToWindow();
    else setSize(baseSize);
  }
  if (preview) root.setAttribute("data-preview", "");

  const counterEl = document.getElementById("counter");
  const numberEl = document.getElementById("number");
  const labelEl = document.getElementById("label");
  const valueEl = document.getElementById("value");
  const glowEl = document.getElementById("glow");

  // Во сколько раз можно увеличить счётчик при размере FIT_BASE_PX, чтобы он влез в окно.
  // Размеры без transform (offsetWidth), поэтому идущая анимация не мешает.
  function fitScale() {
    const text = valueEl.textContent;
    setSize(FIT_BASE_PX);
    valueEl.textContent = text.padStart(FIT_MIN_DIGITS, "0");
    const width = counterEl.offsetWidth;
    const height = counterEl.offsetHeight;
    valueEl.textContent = text;
    if (!width || !height) return null;
    return Math.min((innerWidth * FIT_WIDTH) / width, (innerHeight * FIT_HEIGHT) / height);
  }

  // Подгоняет счётчик под окно, затем применяет свои масштабы числа и подписи, но не
  // больше, чем влезает в окно: при 200% ничего не вылезает за края.
  let fitRetry = 0;
  function fitToWindow() {
    if (!autoSize) return;
    const [savedNumber, savedLabel] = [numberScale, labelScale];
    numberScale = labelScale = 1;
    const plain = fitScale();
    [numberScale, labelScale] = [savedNumber, savedLabel];
    if (plain === null) {
      // Окно скрыто (вкладка страницы управления): подгоним, когда его покажут
      setSize(FIT_BASE_PX);
      if (!fitRetry) fitRetry = requestAnimationFrame(() => { fitRetry = 0; fitToWindow(); });
      return;
    }
    const scaled = numberScale === 1 && labelScale === 1 ? plain : fitScale();
    setSize(Math.max(8, Math.floor(FIT_BASE_PX * Math.min(plain, scaled ?? plain))));
  }

  window.addEventListener("resize", fitToWindow);
  if (document.fonts) document.fonts.ready.then(fitToWindow);

  function setCount(n) {
    const text = String(n);
    const grew = text.length !== valueEl.textContent.length;
    valueEl.textContent = text;
    if (grew) fitToWindow();
  }

  // --- Пресеты (overlay/presets.js) ---
  const PRESETS = window.OVERLAY_PRESETS || [{ id: "classic", color: "#ffffff" }];
  let currentPreset = "classic";
  let player = null; // звук (создаётся ниже, если оверлей не в превью и не без звука)

  // Идущие временные события (app/events.py, сообщение "events"); null — ещё не знаем.
  let activeEvents = null;
  let wantedPreset = "classic"; // пресет, который просили: если это оформление события, оно вернётся

  // Оформление события после его окончания не показывается: вместо него — фирменное (первое).
  function findPreset(id) {
    const preset = PRESETS.find((p) => p.id === id);
    if (preset && preset.event && activeEvents && !activeEvents.includes(preset.event)) return PRESETS[0];
    return preset || PRESETS[0];
  }

  function applyPreset(id) {
    wantedPreset = id;
    const preset = findPreset(id);
    currentPreset = preset.id;
    root.setAttribute("data-preset", preset.id);
    root.style.setProperty("--color", colorOverride || preset.color || "#ffffff");
    if (player) player.setStandard(preset.sound); // у пресета может быть свой стандартный звук
    fitToWindow(); // у пресетов разные шрифты и ширина цифр
  }

  // --- Анимации ---

  // «+N», уплывающее вверх. Кадры можно заменить для своего пресета.
  function floatPlus(delta, keyframes, options) {
    const plus = document.createElement("span");
    plus.className = "plus";
    plus.textContent = delta < 0 ? "−" + -delta : "+" + delta; // в отсчёте до цели число убывает
    numberEl.appendChild(plus);
    const anim = plus.animate(
      keyframes || [
        { transform: "translate(-50%, 0) scale(0.6)", opacity: 0 },
        { transform: "translate(-50%, -60%) scale(1.1)", opacity: 1, offset: 0.2 },
        { transform: "translate(-50%, -160%) scale(1)", opacity: 0 },
      ],
      options || { duration: 1200, easing: "ease-out" }
    );
    anim.onfinish = () => plus.remove();
  }

  // Классика: подпрыгивание, вспышка, «+N»
  function animateClassic(delta) {
    valueEl.animate(
      [
        { transform: "translateY(0) scale(1)" },
        { transform: "translateY(-12%) scale(1.3)", offset: 0.3 },
        { transform: "translateY(0) scale(0.92)", offset: 0.65 },
        { transform: "translateY(0) scale(1)" },
      ],
      { duration: 550, easing: "ease-out" }
    );

    glowEl.animate(
      [
        { opacity: 0, transform: "scale(0.6)" },
        { opacity: 0.6, transform: "scale(1)", offset: 0.2 },
        { opacity: 0, transform: "scale(1.3)" },
      ],
      { duration: 700, easing: "ease-out" }
    );

    floatPlus(delta);
  }

  // Мем: удар с увеличением и тряска, «+N» влетает с поворотом
  function animateImpact(delta) {
    valueEl.animate(
      [
        { transform: "scale(1) rotate(0)" },
        { transform: "scale(1.35) rotate(-4deg)", offset: 0.12 },
        { transform: "scale(1.2) translateX(-6%) rotate(3deg)", offset: 0.24 },
        { transform: "scale(1.15) translateX(6%) rotate(-3deg)", offset: 0.36 },
        { transform: "scale(1.1) translateX(-4%) rotate(2deg)", offset: 0.48 },
        { transform: "scale(1.05) translateX(3%) rotate(-1deg)", offset: 0.6 },
        { transform: "scale(1) translateX(-1%) rotate(0)", offset: 0.75 },
        { transform: "scale(1) rotate(0)" },
      ],
      { duration: 600, easing: "linear" }
    );

    floatPlus(delta, [
      { transform: "translate(-50%, -40%) scale(2.2) rotate(-12deg)", opacity: 0 },
      { transform: "translate(-50%, -70%) scale(1) rotate(-8deg)", opacity: 1, offset: 0.15 },
      { transform: "translate(-50%, -80%) scale(1.05) rotate(-8deg)", opacity: 1, offset: 0.6 },
      { transform: "translate(-50%, -150%) scale(0.9) rotate(-8deg)", opacity: 0 },
    ], { duration: 1200, easing: "ease-out" });
  }

  // Неон: мерцание вывески, яркая вспышка, светящийся «+N»
  function animateNeon(delta) {
    valueEl.animate(
      [
        { opacity: 1, transform: "scale(1)" },
        { opacity: 0.25, transform: "scale(1.08)", offset: 0.08 },
        { opacity: 1, transform: "scale(1.12)", offset: 0.16 },
        { opacity: 0.4, transform: "scale(1.1)", offset: 0.24 },
        { opacity: 1, transform: "scale(1.1)", offset: 0.34 },
        { opacity: 1, transform: "scale(1)" },
      ],
      { duration: 800, easing: "ease-out" }
    );

    glowEl.animate(
      [
        { opacity: 0, transform: "scale(0.7)" },
        { opacity: 0.55, transform: "scale(1)", offset: 0.3 },
        { opacity: 0.2, transform: "scale(1.15)", offset: 0.6 },
        { opacity: 0, transform: "scale(1.3)" },
      ],
      { duration: 1100, easing: "ease-out" }
    );

    floatPlus(delta, [
      { transform: "translate(-50%, 0)", opacity: 0 },
      { transform: "translate(-50%, -60%)", opacity: 1, offset: 0.15 },
      { transform: "translate(-50%, -60%)", opacity: 0.3, offset: 0.25 },
      { transform: "translate(-50%, -80%)", opacity: 1, offset: 0.35 },
      { transform: "translate(-50%, -160%)", opacity: 0 },
    ], { duration: 1300, easing: "ease-out" });
  }

  // Ретро: движение рывками (steps), как спрайт в старой игре
  function animateRetro(delta) {
    valueEl.animate(
      [
        { transform: "translateY(0) scale(1)" },
        { transform: "translateY(-16%) scale(1.2)", offset: 0.4 },
        { transform: "translateY(0) scale(1)" },
      ],
      { duration: 480, easing: "steps(6, end)" }
    );

    floatPlus(delta, [
      { transform: "translate(-50%, 0)", opacity: 1 },
      { transform: "translate(-50%, -150%)", opacity: 1, offset: 0.8 },
      { transform: "translate(-50%, -150%)", opacity: 0 },
    ], { duration: 1100, easing: "steps(8, end)" });
  }

  // Минимализм: число мягко въезжает снизу, «+N» тихо всплывает
  function animateMinimal(delta) {
    valueEl.animate(
      [
        { transform: "translateY(18%)", opacity: 0.2 },
        { transform: "translateY(0)", opacity: 1 },
      ],
      { duration: 320, easing: "cubic-bezier(0.2, 0.8, 0.2, 1)" }
    );

    floatPlus(delta, [
      { transform: "translate(-50%, 0)", opacity: 0 },
      { transform: "translate(-50%, -80%)", opacity: 0.9, offset: 0.3 },
      { transform: "translate(-50%, -140%)", opacity: 0 },
    ], { duration: 1000, easing: "ease-out" });
  }

  // Цензура (фирменный): плашка вздрагивает, а над ней вылетает ругань комиксов — «#!@%».
  const CENSOR_GLYPHS = ["#", "!", "@", "%", "&", "*", "$", "?"];
  let censorLast = "";

  function animateCensor(delta) {
    const tilt = (Math.random() < 0.5 ? -1 : 1) * (2 + Math.random() * 2);
    valueEl.animate(
      [
        { transform: "translate(0, 0) rotate(0) scale(1)" },
        { transform: `translate(-3%, -6%) rotate(${-tilt}deg) scale(1.14)`, offset: 0.18 },
        { transform: `translate(3%, 2%) rotate(${tilt}deg) scale(1.08)`, offset: 0.4 },
        { transform: `translate(-2%, 0) rotate(${-tilt / 2}deg) scale(1.03)`, offset: 0.65 },
        { transform: "translate(0, 0) rotate(0) scale(1)" },
      ],
      { duration: 420, easing: "cubic-bezier(.3, 1.4, .5, 1)" }
    );
    // Четыре символа, без повтора предыдущей «ругани»
    let text;
    do {
      text = Array.from({ length: 4 }, () => CENSOR_GLYPHS[Math.floor(Math.random() * CENSOR_GLYPHS.length)]).join("");
    } while (text === censorLast);
    censorLast = text;
    const bubble = document.createElement("span");
    bubble.className = "plus censor-bubble";
    bubble.textContent = delta < 0 ? "−" + -delta : text;
    numberEl.appendChild(bubble);
    const drift = (Math.random() - 0.5) * 30;
    const anim = bubble.animate(
      [
        { transform: "translate(-50%, 10%) rotate(-8deg) scale(0.4)", opacity: 0 },
        { transform: `translate(calc(-50% + ${drift / 2}%), -70%) rotate(5deg) scale(1.15)`, opacity: 1, offset: 0.25 },
        { transform: `translate(calc(-50% + ${drift}%), -110%) rotate(-3deg) scale(1)`, opacity: 1, offset: 0.75 },
        { transform: `translate(calc(-50% + ${drift}%), -150%) rotate(0) scale(0.9)`, opacity: 0 },
      ],
      { duration: 1100, easing: "ease-out" }
    );
    anim.onfinish = () => bubble.remove();
  }

  // Взрыв: резкое увеличение, вспышка и разлетающиеся искры
  const SPARK_COUNT = 12;

  function animateExplosion(delta) {
    valueEl.animate(
      [
        { transform: "scale(1)" },
        { transform: "scale(1.7) rotate(-3deg)", offset: 0.18 },
        { transform: "scale(0.85) rotate(2deg)", offset: 0.45 },
        { transform: "scale(1.06)", offset: 0.7 },
        { transform: "scale(1)" },
      ],
      { duration: 650, easing: "ease-out" }
    );

    glowEl.animate(
      [
        { opacity: 0, transform: "scale(0.3)" },
        { opacity: 0.9, transform: "scale(1)", offset: 0.15 },
        { opacity: 0, transform: "scale(1.6)" },
      ],
      { duration: 650, easing: "ease-out" }
    );

    for (let i = 0; i < SPARK_COUNT; i++) {
      const spark = document.createElement("span");
      spark.className = "spark";
      numberEl.appendChild(spark);
      const angle = (i / SPARK_COUNT) * Math.PI * 2 + Math.random() * 0.4;
      const dist = size * (0.7 + Math.random() * 0.5);
      const dx = Math.cos(angle) * dist;
      const dy = Math.sin(angle) * dist;
      const anim = spark.animate(
        [
          { transform: "translate(0, 0) scale(1.2)", opacity: 1 },
          { transform: `translate(${dx * 0.7}px, ${dy * 0.7}px) scale(0.9)`, opacity: 1, offset: 0.5 },
          { transform: `translate(${dx}px, ${dy + size * 0.15}px) scale(0.3)`, opacity: 0 },
        ],
        { duration: 600 + Math.random() * 250, easing: "cubic-bezier(0.1, 0.7, 0.3, 1)" }
      );
      anim.onfinish = () => spark.remove();
    }

    floatPlus(delta, [
      { transform: "translate(-50%, 0) scale(0.3)", opacity: 0 },
      { transform: "translate(-50%, -70%) scale(1.5)", opacity: 1, offset: 0.15 },
      { transform: "translate(-50%, -90%) scale(1.1)", opacity: 1, offset: 0.4 },
      { transform: "translate(-50%, -160%) scale(1)", opacity: 0 },
    ], { duration: 1200, easing: "ease-out" });
  }

  // 🎃 Проклятый мат (событие «Хеллоуин», временное): число вздрагивает, как от испуга,
  // от него разлетаются летучие мыши и призраки, «+N» стекает зелёной слизью.
  const SPOOKS = ["🦇", "🦇", "👻", "💀", "🦇"];

  function spook(glyph, angle, dist, duration, delay = 0) {
    const el = document.createElement("span");
    el.className = "spook";
    el.textContent = glyph;
    numberEl.appendChild(el);
    const dx = Math.cos(angle) * dist;
    const dy = Math.sin(angle) * dist;
    const flip = dx < 0 ? -1 : 1;
    const anim = el.animate(
      [
        { transform: `translate(-50%, -50%) scale(0.3) scaleX(${flip})`, opacity: 0 },
        { transform: `translate(calc(-50% + ${dx * 0.3}px), calc(-50% + ${dy * 0.3 - size * 0.1}px)) scale(1) scaleX(${flip})`, opacity: 1, offset: 0.25 },
        { transform: `translate(calc(-50% + ${dx * 0.7}px), calc(-50% + ${dy * 0.7 + size * 0.08}px)) scale(0.9) scaleX(${flip})`, opacity: 1, offset: 0.6 },
        { transform: `translate(calc(-50% + ${dx}px), calc(-50% + ${dy - size * 0.1}px)) scale(0.6) scaleX(${flip})`, opacity: 0 },
      ],
      { duration, delay, easing: "ease-out", fill: "backwards" }
    );
    anim.onfinish = () => el.remove();
  }

  function animateHalloween(delta) {
    valueEl.animate(
      [
        { transform: "translate(0, 0) scale(1) skewX(0)" },
        { transform: "translate(-2%, -4%) scale(1.22) skewX(-6deg)", offset: 0.12 },
        { transform: "translate(3%, 1%) scale(1.15) skewX(5deg)", offset: 0.24 },
        { transform: "translate(-2%, 0) scale(1.1) skewX(-3deg)", offset: 0.36 },
        { transform: "translate(1%, 0) scale(1.04) skewX(2deg)", offset: 0.5 },
        { transform: "translate(0, 0) scale(1) skewX(0)" },
      ],
      { duration: 650, easing: "ease-out" }
    );
    glowEl.animate(
      [
        { opacity: 0, transform: "scale(0.5)" },
        { opacity: 0.75, transform: "scale(1)", offset: 0.2 },
        { opacity: 0.3, transform: "scale(1.1)", offset: 0.5 },
        { opacity: 0, transform: "scale(1.35)" },
      ],
      { duration: 900, easing: "ease-out" }
    );
    const count = 2 + Math.floor(Math.random() * 2);
    for (let i = 0; i < count; i++) {
      // Вверх-влево и вверх-вправо, чтобы не улетать за низ окна
      const angle = -Math.PI / 2 + (i % 2 ? 1 : -1) * (0.5 + Math.random() * 0.9);
      spook(SPOOKS[Math.floor(Math.random() * SPOOKS.length)], angle, size * (0.8 + Math.random() * 0.5), 1300 + Math.random() * 400, i * 90);
    }
    floatPlus(delta, [
      { transform: "translate(-50%, -30%) scaleY(0.6)", opacity: 0 },
      { transform: "translate(-50%, -70%) scaleY(1.15)", opacity: 1, offset: 0.2 },
      { transform: "translate(-50%, -85%) scaleY(1.3) scaleX(0.9)", opacity: 1, offset: 0.55 },
      { transform: "translate(-50%, -150%) scaleY(1.6) scaleX(0.7)", opacity: 0 },
    ], { duration: 1300, easing: "ease-in-out" });
  }

  // Проклятие (каждое 13-е ругательство во время события): зелёный огонь, тряска, черепа и «☠ 13 ☠»
  const CURSE_MS = 2600;
  let curseTimer = null;

  function curse(count) {
    root.setAttribute("data-cursed", "");
    clearTimeout(curseTimer);
    curseTimer = setTimeout(() => root.removeAttribute("data-cursed"), CURSE_MS);
    const shake = [];
    for (let i = 0; i <= 16; i++) {
      const k = 1 - i / 16;
      shake.push({ transform: `translate(${(i % 2 ? 1 : -1) * 4 * k}%, ${(i % 3 - 1) * 3 * k}%) rotate(${(i % 2 ? -1 : 1) * 4 * k}deg) scale(${1 + 0.35 * k})` });
    }
    valueEl.animate(shake, { duration: 1100, delay: 450, easing: "linear" });
    glowEl.animate(
      [
        { opacity: 0, transform: "scale(0.4)", filter: "hue-rotate(80deg)" },
        { opacity: 1, transform: "scale(1.3)", filter: "hue-rotate(80deg)", offset: 0.2 },
        { opacity: 0.6, transform: "scale(1.1)", filter: "hue-rotate(80deg)", offset: 0.6 },
        { opacity: 0, transform: "scale(1.6)", filter: "hue-rotate(80deg)" },
      ],
      { duration: CURSE_MS, easing: "ease-out" }
    );
    for (let i = 0; i < 8; i++) {
      spook(i % 2 ? "💀" : "👻", (2 * Math.PI * i) / 8, size * 0.9, 1700, 400 + i * 60);
    }
    const bubble = document.createElement("span");
    bubble.className = "plus curse-bubble";
    bubble.textContent = `☠ ${count} ☠`;
    numberEl.appendChild(bubble);
    const anim = bubble.animate(
      [
        { transform: "translate(-50%, 20%) scale(0.2)", opacity: 0 },
        { transform: "translate(-50%, -45%) scale(1.4)", opacity: 1, offset: 0.2 },
        { transform: "translate(-50%, -60%) scale(1.25)", opacity: 1, offset: 0.75 },
        { transform: "translate(-50%, -110%) scale(1)", opacity: 0 },
      ],
      { duration: CURSE_MS, delay: 300, easing: "ease-out", fill: "backwards" }
    );
    anim.onfinish = () => bubble.remove();
  }

  // id пресета → анимация прибавления
  const INCREMENT_ANIMATIONS = {
    swearcounter: animateCensor,
    classic: animateClassic,
    impact: animateImpact,
    neon: animateNeon,
    retro: animateRetro,
    minimal: animateMinimal,
    explosion: animateExplosion,
    halloween: animateHalloween,
  };

  // Проклятие события показывает только его оформление: на остальных счёт идёт как обычно.
  function cursedPreset() {
    return findPreset(currentPreset).event === "halloween";
  }

  // Что получает анимация личного оформления (animation.js набора, см. docs/PRESETS.md)
  function animationApi(preset) {
    return {
      root,
      counter: counterEl,
      number: numberEl,
      value: valueEl,
      label: labelEl,
      glow: glowEl,
      size, // текущий размер цифр в пикселях
      base: `/overlay/custom/${preset.id}/`, // адрес файлов набора: api.base + "coin.png"
      floatPlus,
      builtin: Object.assign({}, INCREMENT_ANIMATIONS), // встроенные анимации по id
    };
  }

  // Особое число (10, 50, 100… или цель): поверх обычной анимации — покачивание и звёзды
  const SPARKS = 12;
  function celebrate() {
    valueEl.animate(
      [
        { transform: "scale(1) rotate(0)" },
        { transform: "scale(1.25) rotate(-8deg)", offset: 0.25 },
        { transform: "scale(1.25) rotate(8deg)", offset: 0.5 },
        { transform: "scale(1.12) rotate(-4deg)", offset: 0.75 },
        { transform: "scale(1) rotate(0)" },
      ],
      { duration: 1200, delay: 500, easing: "ease-in-out" }
    );
    for (let i = 0; i < SPARKS; i++) {
      const spark = document.createElement("span");
      spark.className = "spark";
      spark.textContent = "★";
      numberEl.appendChild(spark);
      const angle = (2 * Math.PI * i) / SPARKS;
      // Разлёт в пределах числа: источник в OBS обычно подогнан под него, дальше звёзды обрежутся
      const x = Math.cos(angle) * numberEl.offsetWidth * 0.6;
      const y = Math.sin(angle) * numberEl.offsetHeight * 0.6;
      const anim = spark.animate(
        [
          { transform: "translate(-50%, -50%) scale(0.3)", opacity: 0 },
          { transform: "translate(-50%, -50%) scale(1)", opacity: 1, offset: 0.15 },
          { transform: `translate(calc(-50% + ${x}px), calc(-50% + ${y}px)) scale(0.6)`, opacity: 0 },
        ],
        { duration: 1400, delay: 300, easing: "ease-out", fill: "backwards" }
      );
      anim.onfinish = () => spark.remove();
    }
  }

  function playIncrementAnimation(delta) {
    const preset = findPreset(currentPreset);
    const own = (window.OVERLAY_ANIMATIONS || {})[preset.id];
    if (own) {
      try {
        own(delta, animationApi(preset));
        return;
      } catch (e) {
        console.error(`Анимация оформления ${preset.id}:`, e); // ошибка в наборе — играем встроенную
      }
    }
    // У личного оформления без своей анимации — встроенная по полю animation
    (INCREMENT_ANIMATIONS[preset.id] || INCREMENT_ANIMATIONS[preset.animation] || animateClassic)(delta);
  }

  // Подпись рядом с числом: text — строка (пустая — без подписи), position — left/right/top/bottom
  function applyLabel(text, position) {
    labelEl.textContent = text;
    labelEl.hidden = !text;
    root.setAttribute("data-label-position", position || "left");
    fitToWindow();
  }

  // Сообщение "style": пресет (если он не закреплён в адресе) и подпись
  function handleStyle(msg) {
    if (fixedPreset === null && typeof msg.preset === "string") applyPreset(msg.preset);
    applyScale(msg);
    // Подпись со страницы управления относится к счёту. У цели она из адреса,
    // у таймера — из адреса, а если её там нет, то со страницы управления.
    if (showTimer) applyLabel(timerLabel || msg.timer_label || "", msg.label_position);
    else if (ownLabel) applyLabel(timerLabel, msg.label_position);
    else if (typeof msg.label === "string") applyLabel(msg.label, msg.label_position);
  }

  // --- Таймер «без мата» (?show=timer): сервер присылает состояние, секунды отсчитываем здесь ---
  let timerState = { elapsed: 0, running: false, at: performance.now() };

  function formatDuration(seconds) {
    const total = Math.floor(seconds);
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = String(total % 60).padStart(2, "0");
    return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
  }

  function renderTimer() {
    const now = timerState.elapsed + (timerState.running ? (performance.now() - timerState.at) / 1000 : 0);
    setCount(formatDuration(now));
  }

  // --- Отсчёт до цели (?show=goal): «—», пока цель не задана ---
  let goalState = { count: 0, goal: 0 };

  function renderGoal() {
    setCount(goalState.goal ? Math.max(goalState.goal - goalState.count, 0) : "—");
  }

  applyPreset(fixedPreset || "classic");

  // --- Предпросмотр: пример числа и анимация по таймеру ---
  if (preview) {
    let count = PREVIEW_COUNT;
    let shown = true; // видно ли превью на странице управления (поле visible в сообщении)
    let timer = null;
    setCount(count);
    // Анимация идёт, только пока превью видно: на скрытой вкладке и в свёрнутом окне она ни к чему.
    function updateTimer() {
      const run = shown && !document.hidden;
      if (run && timer === null) {
        timer = setInterval(() => {
          count += 1;
          setCount(count);
          playIncrementAnimation(1);
          if (count % 13 === 0 && cursedPreset()) curse(count); // превью проклятия на 52, 65…
        }, PREVIEW_INTERVAL_MS);
      } else if (!run && timer !== null) {
        clearInterval(timer);
        timer = null;
      }
    }
    updateTimer();
    document.addEventListener("visibilitychange", updateTimer);
    setTimeout(() => playIncrementAnimation(1), 400);
    // Страница управления меняет стиль без перезагрузки iframe тем же сообщением, что и сервер:
    // iframe.contentWindow.postMessage({ type: "style", preset: "neon", label: "Маты:", visible: true }, location.origin)
    window.addEventListener("message", (event) => {
      if (event.origin !== location.origin) return;
      const msg = event.data;
      if (!msg || msg.type !== "style") return;
      if (typeof msg.preset === "string") applyPreset(msg.preset); // в превью ?preset — только начальный
      applyScale(msg);
      if (typeof msg.label === "string") applyLabel(msg.label, msg.label_position);
      if (typeof msg.visible === "boolean") {
        // Пока iframe был скрыт, мерить было нечего: подгоняем размер, когда его показали.
        if (msg.visible && !shown) fitToWindow();
        shown = msg.visible;
        updateTimer();
      }
    });
    return;
  }

  // --- Звук (overlay/sound.js) ---
  // Громкость и свой звук задаются на странице управления и приходят по WebSocket.
  if (showTimer) {
    renderTimer();
    setInterval(renderTimer, 1000);
  }
  if (showGoal) renderGoal();
  // Дополнительный счётчик: подпись и пресет свои, положение подписи — как у основного.
  let labelPosition = "left";
  let extraLabel = "";
  function handleCounters(list) {
    const counter = list.find((c) => c.id === counterId);
    if (!counter) {
      setCount("—"); // счётчик удалили
      return;
    }
    setCount(counter.count);
    if (fixedPreset === null) applyPreset(counter.preset);
    extraLabel = counter.label;
    applyLabel(extraLabel, labelPosition);
  }

  if (!muted && !ownLabel) {
    player = window.createDingPlayer();
    player.setStandard(findPreset(currentPreset).sound);
  }

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
      if (msg.type === "events") {
        // Событие началось или закончилось: оформление события появляется или пропадает
        activeEvents = Array.isArray(msg.active) ? msg.active : [];
        applyPreset(wantedPreset);
        return;
      }
      if (counterId) {
        if (msg.type === "counters") {
          handleCounters(msg.counters);
        } else if (msg.type === "extra_increment" && msg.id === counterId) {
          setCount(msg.count);
          playIncrementAnimation(msg.delta || 1);
          if (player) player.play();
        } else if (msg.type === "sound") {
          if (player) player.apply(msg);
        } else if (msg.type === "style") {
          labelPosition = msg.label_position;
          applyScale(msg);
          applyLabel(extraLabel, labelPosition);
        } else if (msg.type === "presets") {
          location.reload();
        }
        return;
      }
      if (showTimer) {
        if (msg.type === "timer") {
          timerState = { elapsed: msg.elapsed, running: msg.running, at: performance.now() };
          renderTimer();
        } else if (msg.type === "style") {
          handleStyle(msg);
        } else if (msg.type === "presets") {
          location.reload();
        }
        return;
      }
      if (showGoal) {
        if (msg.type === "state" || msg.type === "increment") {
          const left = goalState.goal - goalState.count;
          goalState.count = msg.count;
          renderGoal();
          if (msg.type === "increment" && goalState.goal && left > 0) {
            playIncrementAnimation(-Math.min(msg.delta || 1, left));
            if (msg.milestone === goalState.goal && cursedPreset()) curse(goalState.goal);
            else if (msg.milestone === goalState.goal) celebrate();
          }
        } else if (msg.type === "goals") {
          goalState.goal = msg.goal;
          renderGoal();
        } else if (msg.type === "style") {
          handleStyle(msg);
        } else if (msg.type === "presets") {
          location.reload();
        }
        return;
      }
      if (msg.type === "state") {
        setCount(msg.count);
      } else if (msg.type === "increment") {
        setCount(msg.count);
        playIncrementAnimation(msg.delta || 1);
        // В «Проклятом мате» особые числа и цель тоже отмечаются проклятием, а не звёздами и фанфарами
        const cursed = cursedPreset() && (msg.curse || msg.milestone);
        if (cursed) curse(msg.count);
        else if (msg.milestone) celebrate();
        if (player) (cursed ? player.playCurse : msg.milestone ? player.playFanfare : player.play)();
      } else if (msg.type === "sound") {
        if (player) player.apply(msg);
      } else if (msg.type === "style") {
        handleStyle(msg);
      } else if (msg.type === "presets") {
        location.reload(); // поставили или удалили личное оформление: заново грузим наборы
      }
    };
    ws.onclose = () => setTimeout(connect, RECONNECT_MS);
    ws.onerror = () => ws.close();
  }

  connect();
})();
