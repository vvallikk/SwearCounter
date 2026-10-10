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

  // --- Параметры из адреса: ?size=120&color=ffffff&mute=1&preset=neon&preview=1 ---
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

  const root = document.documentElement;
  function setSize(px) {
    size = px;
    root.style.setProperty("--size", px + "px");
  }
  setSize(size);
  if (preview) root.setAttribute("data-preview", "");

  const counterEl = document.getElementById("counter");
  const numberEl = document.getElementById("number");
  const labelEl = document.getElementById("label");
  const valueEl = document.getElementById("value");
  const glowEl = document.getElementById("glow");

  // Меряет счётчик при размере FIT_BASE_PX и масштабирует его под окно.
  // Размеры без transform (offsetWidth), поэтому идущая анимация не мешает.
  function fitToWindow() {
    if (!autoSize) return;
    const text = valueEl.textContent;
    setSize(FIT_BASE_PX);
    valueEl.textContent = text.padStart(FIT_MIN_DIGITS, "0");
    const width = counterEl.offsetWidth;
    const height = counterEl.offsetHeight;
    valueEl.textContent = text;
    if (!width || !height) return;
    const scale = Math.min((innerWidth * FIT_WIDTH) / width, (innerHeight * FIT_HEIGHT) / height);
    setSize(Math.max(8, Math.floor(FIT_BASE_PX * scale)));
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

  function findPreset(id) {
    return PRESETS.find((p) => p.id === id) || PRESETS[0];
  }

  function applyPreset(id) {
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
    plus.textContent = "+" + delta;
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

  // Хорёк: число исполняет «военный танец» (радостные прыжки боком с выгнутой спиной),
  // под ним пробегает хорёк и оставляет следы лапок, рядом выскакивает «гу-гу!».
  const FERRET_SVG =
    '<svg viewBox="0 0 120 44" xmlns="http://www.w3.org/2000/svg">' +
    '<path d="M22 26 Q4 22 2 30 Q8 34 22 31Z" style="fill:var(--fur-dark)"/>' + // хвост
    '<rect x="30" y="28" width="7" height="13" rx="3.5" style="fill:var(--fur-dark)"/>' + // лапы
    '<rect x="44" y="28" width="7" height="13" rx="3.5" style="fill:var(--fur-dark)"/>' +
    '<rect x="72" y="28" width="7" height="13" rx="3.5" style="fill:var(--fur-dark)"/>' +
    '<rect x="84" y="28" width="7" height="13" rx="3.5" style="fill:var(--fur-dark)"/>' +
    '<ellipse cx="58" cy="25" rx="38" ry="11" style="fill:var(--fur)"/>' + // туловище
    '<ellipse cx="60" cy="30" rx="26" ry="5" fill="#c99a6b"/>' + // светлое брюшко
    '<circle cx="92" cy="9" r="5" fill="#f3e2c7"/>' + // ухо
    '<ellipse cx="100" cy="19" rx="15" ry="11" fill="#f3e2c7"/>' + // голова
    '<path d="M90 16 Q101 11 112 17 Q103 21 90 21Z" style="fill:var(--fur-dark)"/>' + // «маска»
    '<circle cx="103" cy="17" r="2.6" fill="#111"/>' + // глаз
    '<circle cx="104" cy="16" r="0.9" fill="#fff"/>' +
    '<circle cx="114.5" cy="22" r="2.6" style="fill:var(--nose)"/>' + // нос
    "</svg>";
  const PAW_SVG =
    '<svg viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg" style="fill:var(--fur-dark)">' +
    '<ellipse cx="10" cy="13.5" rx="5" ry="4.5"/>' +
    '<circle cx="3.5" cy="7.5" r="2.2"/><circle cx="7.5" cy="4" r="2.2"/>' +
    '<circle cx="12.5" cy="4" r="2.2"/><circle cx="16.5" cy="7.5" r="2.2"/></svg>';
  const FERRET_RUN_MS = 1300;
  const PAW_COUNT = 6;

  function svgElement(className, svg) {
    const span = document.createElement("span");
    span.className = className;
    span.innerHTML = svg;
    numberEl.appendChild(span);
    return span;
  }

  function animateFerret(delta) {
    valueEl.animate(
      [
        { transform: "translate(0, 0) skewX(0) scale(1)" },
        { transform: "translate(-10%, -18%) skewX(12deg) scale(1.15, 1.2)", offset: 0.18 },
        { transform: "translate(-12%, 0) skewX(0) scale(1.2, 0.85)", offset: 0.32 },
        { transform: "translate(8%, -16%) skewX(-12deg) scale(1.15, 1.2)", offset: 0.52 },
        { transform: "translate(10%, 0) skewX(0) scale(1.2, 0.85)", offset: 0.68 },
        { transform: "translate(0, -6%) skewX(4deg) scale(1.05)", offset: 0.84 },
        { transform: "translate(0, 0) skewX(0) scale(1)" },
      ],
      { duration: 900, easing: "ease-in-out" }
    );

    glowEl.animate(
      [
        { opacity: 0, transform: "scale(0.6)" },
        { opacity: 0.45, transform: "scale(1)", offset: 0.25 },
        { opacity: 0, transform: "scale(1.3)" },
      ],
      { duration: 900, easing: "ease-out" }
    );

    // Хорёк бежит слева направо галопом: спина то выгибается, то вытягивается.
    // Направление меняется случайно, тогда хорёк разворачивается мордой по ходу.
    const dir = Math.random() < 0.5 ? 1 : -1;
    const from = -dir * size * 1.7;
    const to = dir * size * 1.7;
    const flip = dir === 1 ? "" : " scaleX(-1)";
    const ferret = svgElement("ferret", FERRET_SVG);
    const steps = [];
    const HOPS = 8;
    for (let i = 0; i <= HOPS; i++) {
      const x = from + ((to - from) * i) / HOPS;
      const up = i % 2 === 1;
      steps.push({
        transform: `translateX(${x}px) translateY(${up ? -size * 0.12 : 0}px) scaleY(${up ? 1.12 : 0.92})${flip}`,
        opacity: i === 0 || i === HOPS ? 0 : 1,
      });
    }
    ferret.animate(steps, { duration: FERRET_RUN_MS, easing: "linear" }).onfinish = () => ferret.remove();

    // Следы лапок появляются за хорьком и тают.
    for (let i = 0; i < PAW_COUNT; i++) {
      const share = (i + 1) / (PAW_COUNT + 1);
      const x = from + (to - from) * share;
      const y = i % 2 ? size * 0.05 : -size * 0.02;
      const paw = svgElement("paw", PAW_SVG);
      const turn = dir === 1 ? 90 : -90; // пальцы смотрят по ходу бега
      paw.animate(
        [
          { transform: `translate(${x}px, ${y}px) rotate(${turn}deg) scale(0.4)`, opacity: 0 },
          { transform: `translate(${x}px, ${y}px) rotate(${turn}deg) scale(1)`, opacity: 0.85, offset: 0.1 },
          { transform: `translate(${x}px, ${y}px) rotate(${turn}deg) scale(1)`, opacity: 0.85, offset: 0.6 },
          { transform: `translate(${x}px, ${y}px) rotate(${turn}deg) scale(1)`, opacity: 0 },
        ],
        { duration: 1400, delay: FERRET_RUN_MS * share, easing: "ease-out", fill: "backwards" }
      ).onfinish = () => paw.remove();
    }

    const goo = document.createElement("span");
    goo.className = "goo";
    goo.textContent = "гу-гу!";
    numberEl.appendChild(goo);
    goo.animate(
      [
        { transform: "scale(0.3) rotate(-20deg)", opacity: 0 },
        { transform: "scale(1.2) rotate(10deg)", opacity: 1, offset: 0.15 },
        { transform: "scale(1) rotate(-6deg)", opacity: 1, offset: 0.3 },
        { transform: "scale(1.05) rotate(6deg)", opacity: 1, offset: 0.45 },
        { transform: "translateY(-40%) scale(1) rotate(0)", opacity: 0 },
      ],
      { duration: 1100, delay: 120, easing: "ease-out", fill: "backwards" }
    ).onfinish = () => goo.remove();

    floatPlus(delta, [
      { transform: "translate(-50%, 0) rotate(0)", opacity: 0 },
      { transform: "translate(-65%, -60%) rotate(-10deg)", opacity: 1, offset: 0.2 },
      { transform: "translate(-35%, -100%) rotate(10deg)", opacity: 1, offset: 0.5 },
      { transform: "translate(-50%, -160%) rotate(0)", opacity: 0 },
    ], { duration: 1300, easing: "ease-out" });
  }

  // id пресета → анимация прибавления
  const INCREMENT_ANIMATIONS = {
    classic: animateClassic,
    impact: animateImpact,
    neon: animateNeon,
    retro: animateRetro,
    minimal: animateMinimal,
    explosion: animateExplosion,
    ferret: animateFerret,
  };

  function playIncrementAnimation(delta) {
    (INCREMENT_ANIMATIONS[currentPreset] || animateClassic)(delta);
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
    if (typeof msg.label === "string") applyLabel(msg.label, msg.label_position);
  }

  applyPreset(fixedPreset || "classic");

  // --- Предпросмотр: пример числа и анимация по таймеру ---
  if (preview) {
    let count = PREVIEW_COUNT;
    setCount(count);
    setInterval(() => {
      count += 1;
      setCount(count);
      playIncrementAnimation(1);
    }, PREVIEW_INTERVAL_MS);
    setTimeout(() => playIncrementAnimation(1), 400);
    // Страница управления меняет стиль без перезагрузки iframe тем же сообщением, что и сервер:
    // iframe.contentWindow.postMessage({ type: "style", preset: "neon", label: "Маты:" }, location.origin)
    window.addEventListener("message", (event) => {
      if (event.origin !== location.origin) return;
      const msg = event.data;
      if (!msg || msg.type !== "style") return;
      if (typeof msg.preset === "string") applyPreset(msg.preset); // в превью ?preset — только начальный
      if (typeof msg.label === "string") applyLabel(msg.label, msg.label_position);
    });
    return;
  }

  // --- Звук (overlay/sound.js) ---
  // Громкость и свой звук задаются на странице управления и приходят по WebSocket.
  if (!muted) {
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
      if (msg.type === "state") {
        setCount(msg.count);
      } else if (msg.type === "increment") {
        setCount(msg.count);
        playIncrementAnimation(msg.delta || 1);
        if (player) player.play();
      } else if (msg.type === "sound") {
        if (player) player.apply(msg);
      } else if (msg.type === "style") {
        handleStyle(msg);
      }
    };
    ws.onclose = () => setTimeout(connect, RECONNECT_MS);
    ws.onerror = () => ws.close();
  }

  connect();
})();
