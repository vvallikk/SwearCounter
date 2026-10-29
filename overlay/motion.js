// Анимации переходов оверлея: смена числа и появление/исчезновение счётчика.
//
// Общий список для оверлея и страницы управления (как presets.js): страница строит по нему
// выбор, оверлей — играет выбранное. Сервер хранит только id и проверяет его форму,
// незнакомый id оверлей заменяет значением по умолчанию.
//
// У сезонных вариантов есть поле event: { id, until }. После даты until (не включая её)
// вариант пропадает из выбора, а оверлей, где он выбран, переходит на вариант по умолчанию.
// Такие варианты временные: после события их можно удалить целиком (поиск по «EVENT:»).
(() => {
  "use strict";

  // EVENT: halloween-2026 — временно, до 3 ноября 2026
  const HALLOWEEN = { id: "halloween-2026", until: "2026-11-03" };

  // Смена числа: старые цифры уходят, новые приходят. Меняются только изменившиеся разряды.
  const TRANSITIONS = [
    { id: "none", title: "Без анимации", description: "Число меняется мгновенно, как раньше." },
    { id: "roll", title: "Прокрутка", description: "Цифры прокручиваются, как на счётчике пробега: вверх при прибавлении, вниз при сбросе." },
    { id: "flip", title: "Перекидное табло", description: "Цифры переворачиваются, как таблички на вокзальном табло." },
    { id: "fade", title: "Растворение", description: "Старая цифра расплывается, новая проявляется из размытия." },
    { id: "slot", title: "Слот-машина", description: "Разряды крутятся случайными цифрами и по очереди останавливаются." },
    { id: "glitch", title: "Глитч", description: "Цифры дёргаются и расслаиваются на цветные полосы, как сломанный экран." },
    { id: "spooky", title: "🎃 Привидение", description: "Хэллоуин: старые цифры стекают вниз, новые всплывают привидением. Только до 3 ноября.", event: HALLOWEEN },
  ];

  // Появление и исчезновение всего счётчика: при загрузке, когда источник OBS
  // становится видимым, и при автоскрытии. Исчезновение — та же анимация задом наперёд.
  const ENTRANCES = [
    { id: "none", title: "Без анимации", description: "Счётчик просто появляется и пропадает." },
    { id: "fade", title: "Плавно", description: "Мягкое проявление и затухание." },
    { id: "pop", title: "Выпрыгивание", description: "Вырастает из точки с пружинкой." },
    { id: "slide", title: "Выезд снизу", description: "Выезжает снизу и уезжает обратно." },
    { id: "drop", title: "Падение", description: "Падает сверху и подпрыгивает, как мячик." },
    { id: "swing", title: "Табличка", description: "Откидывается сверху на петлях, как вывеска." },
    { id: "blur", title: "Фокус", description: "Проявляется из сильного размытия, как камера при наводке." },
    { id: "glitch", title: "Глитч", description: "Появляется рывками с помехами." },
    { id: "spooky", title: "🎃 Из тумана", description: "Хэллоуин: всплывает из зелёного тумана и покачивается. Только до 3 ноября.", event: HALLOWEEN },
  ];

  const DEFAULT_TRANSITION = "roll";
  const DEFAULT_ENTRANCE = "fade";
  // Таймер меняется каждую секунду: резкие варианты на нём заменяются спокойными.
  const CALM = { slot: "roll", glitch: "fade" };

  function available(item, now) {
    if (!item || !item.event) return Boolean(item);
    return (now || new Date()) < new Date(item.event.until + "T00:00:00");
  }

  function resolve(list, id, fallback) {
    const item = list.find((t) => t.id === id);
    return available(item) ? item.id : fallback;
  }

  // ---------- Смена числа ----------

  const random = (n) => Math.floor(Math.random() * n);
  const GLITCH_GLYPHS = "#%&@$*?!01";

  // Кадры для старой (out) и новой (in) цифры. dir: 1 — число выросло, -1 — уменьшилось.
  const DIGIT_EFFECTS = {
    roll: (dir) => ({
      out: [
        { transform: "translateY(0)", opacity: 1 },
        { transform: `translateY(${-70 * dir}%)`, opacity: 0 },
      ],
      in: [
        { transform: `translateY(${80 * dir}%)`, opacity: 0 },
        { transform: `translateY(${-8 * dir}%)`, opacity: 1, offset: 0.75 },
        { transform: "translateY(0)", opacity: 1 },
      ],
      duration: 420,
      stagger: 70,
      easing: "cubic-bezier(.2,.7,.3,1)",
    }),
    flip: (dir) => ({
      out: [
        { transform: "rotateX(0)", opacity: 1 },
        { transform: `rotateX(${90 * dir}deg)`, opacity: 0.6, offset: 0.5 },
        { transform: `rotateX(${90 * dir}deg)`, opacity: 0 },
      ],
      in: [
        { transform: `rotateX(${-90 * dir}deg)`, opacity: 0 },
        { transform: `rotateX(${-90 * dir}deg)`, opacity: 0.6, offset: 0.5 },
        { transform: `rotateX(${12 * dir}deg)`, opacity: 1, offset: 0.82 },
        { transform: "rotateX(0)", opacity: 1 },
      ],
      duration: 520,
      stagger: 90,
      easing: "ease-in-out",
    }),
    fade: () => ({
      out: [
        { transform: "scale(1)", opacity: 1, filter: "blur(0)" },
        { transform: "scale(1.25)", opacity: 0, filter: "blur(0.12em)" },
      ],
      in: [
        { transform: "scale(0.8)", opacity: 0, filter: "blur(0.12em)" },
        { transform: "scale(1)", opacity: 1, filter: "blur(0)" },
      ],
      duration: 380,
      stagger: 40,
      easing: "ease-out",
    }),
    slot: (dir) => ({
      out: [
        { transform: "translateY(0)", opacity: 1 },
        { transform: `translateY(${-60 * dir}%)`, opacity: 0 },
      ],
      in: [
        { transform: `translateY(${-14 * dir}%)`, opacity: 1 },
        { transform: `translateY(${10 * dir}%)`, opacity: 1, offset: 0.45 },
        { transform: "translateY(0)", opacity: 1 },
      ],
      duration: 260,
      stagger: 160, // разряды останавливаются по очереди, справа налево
      easing: "ease-out",
      spin: { from: "0123456789", time: 380, step: 55 },
    }),
    glitch: () => ({
      out: [
        { transform: "translate(0, 0)", opacity: 1, clipPath: "inset(0 0 0 0)" },
        { transform: "translate(-12%, 0)", opacity: 1, clipPath: "inset(10% 0 55% 0)", offset: 0.3 },
        { transform: "translate(10%, 0)", opacity: 0.8, clipPath: "inset(60% 0 5% 0)", offset: 0.6 },
        { transform: "translate(0, 0)", opacity: 0, clipPath: "inset(45% 0 45% 0)" },
      ],
      in: [
        { transform: "translate(14%, 0) skewX(-12deg)", opacity: 0, clipPath: "inset(40% 0 40% 0)" },
        { transform: "translate(-10%, 0) skewX(10deg)", opacity: 1, clipPath: "inset(0 0 50% 0)", offset: 0.25 },
        { transform: "translate(6%, 0)", opacity: 1, clipPath: "inset(50% 0 0 0)", offset: 0.5 },
        { transform: "translate(-3%, 0)", opacity: 1, clipPath: "inset(0 0 0 0)", offset: 0.75 },
        { transform: "translate(0, 0)", opacity: 1, clipPath: "inset(0 0 0 0)" },
      ],
      duration: 360,
      stagger: 30,
      easing: "steps(6, end)",
      spin: { from: GLITCH_GLYPHS, time: 180, step: 45 },
      className: "mc-glitch",
    }),
    // EVENT: halloween-2026
    spooky: () => ({
      out: [
        { transform: "translateY(0) scale(1, 1)", opacity: 1, filter: "blur(0)" },
        { transform: "translateY(25%) scale(0.9, 1.35)", opacity: 0.8, filter: "blur(0.02em)", offset: 0.4 },
        { transform: "translateY(70%) scale(0.6, 1.8)", opacity: 0, filter: "blur(0.08em)" },
      ],
      in: [
        { transform: "translateY(60%) rotate(0) scale(0.7)", opacity: 0, filter: "blur(0.15em)" },
        { transform: "translateY(-12%) rotate(-7deg) scale(1.08)", opacity: 0.85, filter: "blur(0.03em)", offset: 0.45 },
        { transform: "translateY(4%) rotate(5deg) scale(1)", opacity: 1, filter: "blur(0)", offset: 0.7 },
        { transform: "translateY(-2%) rotate(-2deg)", opacity: 1, filter: "blur(0)", offset: 0.85 },
        { transform: "translateY(0) rotate(0)", opacity: 1, filter: "blur(0)" },
      ],
      duration: 900,
      stagger: 110,
      easing: "ease-out",
      className: "mc-spooky",
    }),
  };

  // Идущая смена числа на элементе: её можно досрочно закончить (settle)
  const running = new WeakMap();

  // Сразу показывает итоговое число, если смена ещё идёт
  function settle(valueEl) {
    const run = running.get(valueEl);
    if (run) run.finish();
  }

  // Меняет текст valueEl с from на to выбранной анимацией.
  // options.calm — для таймера: резкие варианты заменяются спокойными.
  function changeNumber(valueEl, from, to, id, options) {
    settle(valueEl);
    let effectId = resolve(TRANSITIONS, id, DEFAULT_TRANSITION);
    if (options && options.calm && CALM[effectId]) effectId = CALM[effectId];
    const make = DIGIT_EFFECTS[effectId];
    valueEl.textContent = to;
    if (!make || from === to || from === "") return;

    const a = Number(from);
    const b = Number(to);
    const dir = Number.isFinite(a) && Number.isFinite(b) && b < a ? -1 : 1;
    const fx = make(dir);
    // Разряды выравниваются по правому краю: 99 → 100 меняет все три, 41 → 42 — только последний
    const shift = to.length - from.length;
    const cells = [];
    const animations = [];
    const timers = [];
    valueEl.textContent = "";
    for (let i = 0; i < to.length; i++) {
      const cell = document.createElement("span");
      cell.className = "mc-cell";
      const fresh = document.createElement("span");
      fresh.className = "mc-in";
      fresh.textContent = to[i];
      cell.appendChild(fresh);
      valueEl.appendChild(cell);
      const old = from[i - shift] ?? "";
      if (old === to[i]) continue;
      if (fx.className) cell.classList.add(fx.className);
      cells.push(cell);
      const delay = (to.length - 1 - i) * fx.stagger;
      if (old) {
        const gone = document.createElement("span");
        gone.className = "mc-out";
        gone.textContent = old;
        cell.appendChild(gone);
        animations.push(gone.animate(fx.out, { duration: fx.duration, delay: fx.spin ? 0 : delay, easing: fx.easing, fill: "forwards" }));
      }
      let landAt = delay;
      if (fx.spin) {
        // Перебор случайных символов до остановки разряда
        const spinFor = fx.spin.time + delay;
        landAt = spinFor;
        const started = performance.now();
        const tick = () => {
          if (performance.now() - started >= spinFor) {
            fresh.textContent = to[i];
            return;
          }
          fresh.textContent = fx.spin.from[random(fx.spin.from.length)];
          timers.push(setTimeout(tick, fx.spin.step));
        };
        tick();
        animations.push(fresh.animate([{ opacity: 0.85, filter: "blur(0.03em)" }, { opacity: 1, filter: "blur(0)" }], { duration: spinFor }));
      }
      animations.push(fresh.animate(fx.in, { duration: fx.duration, delay: landAt, easing: fx.easing, fill: "backwards" }));
    }

    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      timers.forEach(clearTimeout);
      animations.forEach((anim) => anim.cancel());
      running.delete(valueEl);
      valueEl.textContent = to;
    };
    running.set(valueEl, { finish });
    Promise.all(animations.map((anim) => anim.finished)).then(finish, () => {});
    if (!animations.length) finish();
  }

  // ---------- Появление и исчезновение ----------

  const ENTRANCE_FRAMES = {
    fade: { frames: [{ opacity: 0 }, { opacity: 1 }], duration: 450, easing: "ease-out" },
    pop: {
      frames: [
        { opacity: 0, transform: "scale(0.2)" },
        { opacity: 1, transform: "scale(1.15)", offset: 0.6 },
        { opacity: 1, transform: "scale(0.95)", offset: 0.82 },
        { opacity: 1, transform: "scale(1)" },
      ],
      duration: 550,
      easing: "ease-out",
    },
    slide: {
      frames: [
        { opacity: 0, transform: "translateY(60%)" },
        { opacity: 1, transform: "translateY(-4%)", offset: 0.75 },
        { opacity: 1, transform: "translateY(0)" },
      ],
      duration: 500,
      easing: "cubic-bezier(.2,.8,.3,1)",
    },
    drop: {
      frames: [
        { opacity: 0, transform: "translateY(-120%)" },
        { opacity: 1, transform: "translateY(0)", offset: 0.45 },
        { opacity: 1, transform: "translateY(-18%)", offset: 0.62 },
        { opacity: 1, transform: "translateY(0)", offset: 0.78 },
        { opacity: 1, transform: "translateY(-5%)", offset: 0.89 },
        { opacity: 1, transform: "translateY(0)" },
      ],
      duration: 800,
      easing: "ease-in",
    },
    swing: {
      frames: [
        { opacity: 0, transform: "perspective(600px) rotateX(-95deg)" },
        { opacity: 1, transform: "perspective(600px) rotateX(25deg)", offset: 0.5 },
        { opacity: 1, transform: "perspective(600px) rotateX(-12deg)", offset: 0.72 },
        { opacity: 1, transform: "perspective(600px) rotateX(5deg)", offset: 0.88 },
        { opacity: 1, transform: "perspective(600px) rotateX(0)" },
      ],
      duration: 900,
      easing: "ease-out",
      origin: "50% 0",
    },
    blur: {
      frames: [
        { opacity: 0, transform: "scale(1.4)", filter: "blur(18px)" },
        { opacity: 1, transform: "scale(1)", filter: "blur(0)" },
      ],
      duration: 600,
      easing: "cubic-bezier(.2,.7,.2,1)",
    },
    glitch: {
      frames: [
        { opacity: 0, transform: "translate(0, 0)", clipPath: "inset(50% 0 50% 0)" },
        { opacity: 1, transform: "translate(-8%, 0) skewX(15deg)", clipPath: "inset(10% 0 60% 0)", offset: 0.2 },
        { opacity: 0.4, transform: "translate(6%, 0)", clipPath: "inset(55% 0 10% 0)", offset: 0.4 },
        { opacity: 1, transform: "translate(-3%, 0) skewX(-8deg)", clipPath: "inset(0 0 30% 0)", offset: 0.6 },
        { opacity: 0.7, transform: "translate(2%, 0)", clipPath: "inset(30% 0 0 0)", offset: 0.8 },
        { opacity: 1, transform: "translate(0, 0)", clipPath: "inset(0 0 0 0)" },
      ],
      duration: 500,
      easing: "steps(10, end)",
    },
    // EVENT: halloween-2026
    spooky: {
      frames: [
        { opacity: 0, transform: "translateY(40%) scale(0.85) rotate(0)", filter: "blur(14px) drop-shadow(0 0 0 #7dff5a)" },
        { opacity: 0.6, transform: "translateY(-6%) scale(1.04) rotate(-4deg)", filter: "blur(4px) drop-shadow(0 0 0.3em #7dff5a)", offset: 0.45 },
        { opacity: 1, transform: "translateY(3%) scale(1) rotate(3deg)", filter: "blur(0) drop-shadow(0 0 0.25em #7dff5a)", offset: 0.7 },
        { opacity: 1, transform: "translateY(-1%) rotate(-1deg)", filter: "blur(0) drop-shadow(0 0 0.1em #7dff5a)", offset: 0.86 },
        { opacity: 1, transform: "translateY(0) rotate(0)", filter: "blur(0) drop-shadow(0 0 0 #7dff5a)" },
      ],
      duration: 1400,
      easing: "ease-out",
    },
  };

  const shown = new WeakMap(); // элемент → последняя анимация появления/исчезновения

  function play(el, id, reverse) {
    const prev = shown.get(el);
    if (prev) prev.cancel();
    const fx = ENTRANCE_FRAMES[resolve(ENTRANCES, id, DEFAULT_ENTRANCE)];
    if (!fx) {
      // «Без анимации»: только видимость
      const anim = el.animate([{ opacity: reverse ? 0 : 1 }, { opacity: reverse ? 0 : 1 }], { duration: 1, fill: reverse ? "forwards" : "none" });
      shown.set(el, anim);
      return anim.finished.catch(() => {});
    }
    el.style.transformOrigin = fx.origin || "";
    const anim = el.animate(fx.frames, {
      duration: reverse ? Math.round(fx.duration * 0.7) : fx.duration,
      easing: reverse ? "ease-in" : fx.easing,
      direction: reverse ? "reverse" : "normal",
      fill: reverse ? "forwards" : "backwards", // после исчезновения счётчик остаётся скрытым
    });
    shown.set(el, anim);
    return anim.finished.catch(() => {});
  }

  window.OVERLAY_MOTION = {
    TRANSITIONS,
    ENTRANCES,
    DEFAULT_TRANSITION,
    DEFAULT_ENTRANCE,
    available,
    resolveTransition: (id) => resolve(TRANSITIONS, id, DEFAULT_TRANSITION),
    resolveEntrance: (id) => resolve(ENTRANCES, id, DEFAULT_ENTRANCE),
    changeNumber,
    settle,
    enter: (el, id) => play(el, id, false),
    exit: (el, id) => play(el, id, true),
  };
})();
