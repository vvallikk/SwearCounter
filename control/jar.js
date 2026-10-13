// «Банка матов»: стеклянная банка на вкладке «Счётчик». Каждое засчитанное слово — монета,
// которая падает в банку. Банка наполняется до ближайшей отметки: цели, особого числа
// или (если ни того ни другого нет) круглого числа. Достигли отметки — банка «полна»,
// вспыхивает и опустошается под следующий круг.
//
// Снаружи: SwearJar.mount(контейнер, подпись) и SwearJar.update(счёт, {goal, milestones}).
// Модуль ничего не знает о сервере: счёт и цели ему передаёт control.js.
(() => {
  "use strict";

  const SVG_NS = "http://www.w3.org/2000/svg";
  const CAPACITY = 80; // сколько монет умещается в полную банку
  const COLUMNS = 5;
  const FULL_HOLD_MS = 2600; // сколько банка остаётся «полной» перед опустошением
  const MAX_FALLING = 3; // за один раз анимируется не больше монет: остальные просто появляются
  // Круглые числа: отметки, когда своих целей нет. Дальше шаг — порядок числа.
  const AUTO_STEPS = [10, 25, 50, 100, 250, 500, 1000, 2500, 5000];

  const reduceMotion = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;

  function svg(tag, attrs, parent) {
    const node = document.createElementNS(SVG_NS, tag);
    for (const [name, value] of Object.entries(attrs || {})) node.setAttribute(name, value);
    if (parent) parent.append(node);
    return node;
  }

  // Следующая отметка и предыдущая: между ними «наполняется» банка.
  function tier(count, goal, milestones) {
    const own = [...new Set([...(milestones || []), goal || 0])].filter((n) => n > 0).sort((a, b) => a - b);
    const last = own.length ? own[own.length - 1] : 0;
    // Свои отметки кончились: дальше круглые числа, а после них — следующий порядок.
    const marks = own.concat(AUTO_STEPS.filter((n) => n > last));
    const top = marks[marks.length - 1];
    if (count >= top) {
      const step = 10 ** Math.floor(Math.log10(Math.max(count, 10)));
      const previous = Math.floor(count / step) * step;
      return { previous, target: previous + step, goal: false };
    }
    const target = marks.find((n) => n > count);
    const previous = marks.filter((n) => n <= count).pop() || 0;
    return { previous, target, goal: Boolean(goal) && target === goal };
  }

  // Монеты лежат «в разброс», но всегда одинаково: место монеты зависит только от номера.
  function slot(index) {
    const row = Math.floor(index / COLUMNS);
    const col = index % COLUMNS;
    const noise = Math.sin(index * 12.9898) * 43758.5453;
    const jitter = noise - Math.floor(noise) - 0.5;
    return {
      x: 25 + col * 15.5 + (row % 2) * 6 + jitter * 3,
      y: 129 - row * 6.5 + jitter * 1.5,
      tilt: jitter * 24,
    };
  }

  function build(container, caption) {
    const root = svg("svg", {
      class: "jar-svg",
      viewBox: "0 0 120 150",
      "aria-hidden": "true",
      focusable: "false",
    });
    const defs = svg("defs", {}, root);
    const coinGradient = svg("linearGradient", { id: "jar-coin", x1: "0", y1: "0", x2: "0", y2: "1" }, defs);
    svg("stop", { offset: "0", "stop-color": "var(--jar-coin-top)" }, coinGradient);
    svg("stop", { offset: "1", "stop-color": "var(--jar-coin-bottom)" }, coinGradient);
    const body = "M22 30 Q16 30 16 40 L16 124 Q16 142 36 142 L84 142 Q104 142 104 124 L104 40 Q104 30 98 30 Z";
    svg("clipPath", { id: "jar-clip" }, defs).append(svg("path", { d: body }));
    const coin = svg("g", { id: "jar-coin-shape" }, defs);
    svg("ellipse", { cx: 0, cy: 0, rx: 8, ry: 5.4, fill: "var(--jar-coin-edge)" }, coin);
    svg("ellipse", { cx: 0, cy: -0.6, rx: 7.2, ry: 4.6, fill: "url(#jar-coin)" }, coin);
    svg("ellipse", { cx: 0, cy: -0.6, rx: 3.6, ry: 2.2, fill: "none", stroke: "var(--jar-coin-edge)", "stroke-width": 0.9, opacity: 0.55 }, coin);

    svg("ellipse", { class: "jar-shadow", cx: 60, cy: 145, rx: 40, ry: 4 }, root);
    svg("path", { class: "jar-back", d: body }, root);
    const pile = svg("g", { class: "jar-pile", "clip-path": "url(#jar-clip)" }, root);
    svg("path", { class: "jar-glass", d: body }, root);
    svg("path", { class: "jar-shine", d: "M24 44 L24 118" }, root);
    svg("rect", { class: "jar-rim", x: 24, y: 22, width: 72, height: 10, rx: 5 }, root);
    const falling = svg("g", { class: "jar-falling" }, root);
    const sparks = svg("g", { class: "jar-sparks" }, root);
    for (const [x, y, delay] of [[10, 40, 0], [110, 52, 0.25], [24, 14, 0.5], [98, 10, 0.15], [60, 4, 0.4]]) {
      svg("path", {
        class: "jar-spark", d: "M0 -5 L1.4 -1.4 L5 0 L1.4 1.4 L0 5 L-1.4 1.4 L-5 0 L-1.4 -1.4 Z",
        transform: `translate(${x} ${y})`, style: `animation-delay:${delay}s`,
      }, sparks);
    }
    container.append(root);
    return { root, pile, falling, caption };
  }

  const state = {
    parts: null,
    coins: [], // <use> монет в банке по порядку
    count: null,
    shown: 0, // сколько монет нарисовано
    holdTimer: null,
    holdTarget: null,
    options: { goal: 0, milestones: [] },
  };

  function addCoin(index, hidden) {
    const { x, y, tilt } = slot(index);
    const use = svg("use", { href: "#jar-coin-shape", class: "jar-coin" }, state.parts.pile);
    use.setAttribute("transform", `translate(${x.toFixed(1)} ${y.toFixed(1)}) rotate(${tilt.toFixed(0)})`);
    if (hidden) use.style.visibility = "hidden";
    state.coins.push(use);
    return { use, x, y, tilt };
  }

  function setCoins(n) {
    while (state.coins.length > n) state.coins.pop().remove();
    while (state.coins.length < n) addCoin(state.coins.length);
  }

  function drop(placed) {
    const { falling } = state.parts;
    const copy = svg("use", { href: "#jar-coin-shape", class: "jar-coin" }, falling);
    const base = `translate(${placed.x.toFixed(1)} ${placed.y.toFixed(1)}) rotate(${placed.tilt.toFixed(0)})`;
    copy.setAttribute("transform", base);
    const spin = (Math.random() < 0.5 ? -1 : 1) * 90;
    const fall = copy.animate(
      [
        { transform: `translate(${placed.x + (Math.random() - 0.5) * 16}px, -34px) rotate(${spin}deg)`, opacity: 0 },
        { opacity: 1, offset: 0.15 },
        { transform: `translate(${placed.x}px, ${placed.y}px) rotate(${placed.tilt}deg)`, opacity: 1 },
      ],
      { duration: 460, easing: "cubic-bezier(.4,0,.9,.6)", fill: "forwards" }
    );
    // CSS-трансформ SVG-элемента задан атрибутом: для анимации используем px и translate().
    fall.onfinish = () => {
      copy.remove();
      placed.use.style.visibility = "";
    };
  }

  function wobble() {
    if (!state.parts || (reduceMotion && reduceMotion.matches)) return;
    state.parts.root.animate(
      [
        { transform: "rotate(0) scale(1)" },
        { transform: "rotate(-2.5deg) scale(1.03, .97)", offset: 0.25 },
        { transform: "rotate(1.8deg) scale(.99, 1.01)", offset: 0.55 },
        { transform: "rotate(0) scale(1)" },
      ],
      { duration: 380, easing: "ease-out", delay: 380 }
    );
  }

  function coinsFor(progress, count) {
    if (count <= 0) return 0;
    return Math.min(CAPACITY, Math.max(1, Math.round(progress * CAPACITY)));
  }

  function captionText(count, info) {
    const left = info.target - count;
    if (info.goal) return `Банка до цели ${info.target} · осталось ${left}`;
    return `Банка до ${info.target} · осталось ${left}`;
  }

  function celebrate(on) {
    state.parts.root.classList.toggle("full", on);
    const box = state.parts.caption.parentElement;
    if (box) box.classList.toggle("celebrate", on);
  }

  function render(count, animate) {
    const parts = state.parts;
    const info = tier(count, state.options.goal, state.options.milestones);
    const progress = (count - info.previous) / (info.target - info.previous);
    const want = coinsFor(progress, count);
    const had = state.coins.length;
    const grew = animate && count > (state.count ?? count) && want > had;
    if (grew) {
      const placed = [];
      while (state.coins.length < want) placed.push(addCoin(state.coins.length, true));
      const motion = !(reduceMotion && reduceMotion.matches);
      placed.forEach((p, i) => {
        if (!motion || i < placed.length - MAX_FALLING) p.use.style.visibility = "";
        else setTimeout(() => drop(p), (i - (placed.length - MAX_FALLING)) * 90);
      });
      wobble();
    } else {
      setCoins(want);
    }
    parts.caption.textContent = captionText(count, info);
    celebrate(false);
  }

  function update(count, options) {
    if (!state.parts || typeof count !== "number") return;
    if (options) state.options = { goal: options.goal || 0, milestones: options.milestones || [] };
    const previous = state.count;
    const before = previous === null ? null : tier(previous, state.options.goal, state.options.milestones);
    const now = tier(count, state.options.goal, state.options.milestones);
    // Перешли за отметку вверх: банка полна. Секунду-другую держим её полной, потом круг заново.
    if (before && count > previous && before.target !== now.target && state.holdTarget === null) {
      state.holdTarget = before.target;
      const { parts } = state;
      setCoins(CAPACITY);
      celebrate(true);
      parts.caption.textContent = before.goal ? "Цель достигнута! Банка полна" : "Банка полна!";
      wobble();
      clearTimeout(state.holdTimer);
      state.holdTimer = setTimeout(() => {
        state.holdTarget = null;
        render(state.count, false);
      }, FULL_HOLD_MS);
    } else if (state.holdTarget === null) {
      render(count, previous !== null);
    }
    state.count = count;
  }

  function mount(container, caption) {
    if (state.parts) return;
    state.parts = build(container, caption);
  }

  window.SwearJar = { mount, update, tier };
})();
