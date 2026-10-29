// Анимации окна программы: переходы между вкладками, ползунок выбранной вкладки,
// раскрытие и сворачивание разделов, появление строк состояния.
//
// Вариант хранится в браузере (как тема) и задаётся атрибутом data-motion на <html>
// ещё до отрисовки (скрипт в index.html): smooth, spring, slide или none.
// Оверлей в OBS этот выбор не затрагивает, у него свои анимации (overlay/motion.js).
(() => {
  "use strict";

  const STORAGE_KEY = "uiMotion";
  const MODES = ["smooth", "spring", "slide", "none"];
  const root = document.documentElement;
  const mode = () => (MODES.includes(root.dataset.motion) ? root.dataset.motion : "smooth");

  const SPRING = "cubic-bezier(.34, 1.56, .64, 1)";
  const EASE = "cubic-bezier(.2, .7, .2, 1)";

  // Кадры появления вкладки. dir: 1 — открыли вкладку правее прежней, -1 — левее.
  const PANEL_IN = {
    smooth: () => ({
      frames: [{ opacity: 0, transform: "translateY(6px)" }, { opacity: 1, transform: "none" }],
      options: { duration: 220, easing: EASE },
    }),
    spring: () => ({
      frames: [{ opacity: 0, transform: "translateY(14px) scale(0.97)" }, { opacity: 1, transform: "none" }],
      options: { duration: 420, easing: SPRING },
    }),
    slide: (dir) => ({
      frames: [{ opacity: 0, transform: `translateX(${36 * dir}px)` }, { opacity: 1, transform: "none" }],
      options: { duration: 280, easing: EASE },
    }),
  };

  // --- Вкладки ---
  const tabs = document.querySelector(".tabs");
  const tabButtons = tabs ? [...tabs.querySelectorAll(".tab")] : [];
  const order = tabButtons.map((b) => b.dataset.tab);
  let current = (tabButtons.find((b) => b.getAttribute("aria-selected") === "true") || {}).dataset?.tab;

  // Ползунок под выбранной вкладкой: переезжает к новой, а не перепрыгивает
  let indicator = null;
  if (tabs) {
    indicator = document.createElement("span");
    indicator.className = "tab-indicator";
    indicator.setAttribute("aria-hidden", "true");
    tabs.prepend(indicator);
    tabs.classList.add("has-indicator");
  }

  function placeIndicator(instant) {
    const button = tabButtons.find((b) => b.getAttribute("aria-selected") === "true");
    if (!indicator || !button) return;
    if (instant) indicator.classList.add("no-transition");
    indicator.style.width = `${button.offsetWidth}px`;
    indicator.style.transform = `translateX(${button.offsetLeft}px)`;
    if (instant) {
      void indicator.offsetWidth; // применить без перехода
      indicator.classList.remove("no-transition");
    }
  }

  document.addEventListener("tabchange", (event) => {
    const name = event.detail;
    placeIndicator(false);
    const prev = current;
    current = name;
    const make = PANEL_IN[mode()];
    const panel = document.getElementById(`tab-${name}`);
    if (!make || !panel || prev === name) return;
    const dir = order.indexOf(name) >= order.indexOf(prev) ? 1 : -1;
    const { frames, options } = make(dir);
    panel.animate(frames, options);
  });
  window.addEventListener("resize", () => placeIndicator(true));
  if (document.fonts) document.fonts.ready.then(() => placeIndicator(true));
  placeIndicator(true);

  // --- Сворачиваемые разделы (sections.js переключает класс collapsed) ---
  function animateSection(section, opening) {
    const body = section.querySelector(":scope > .section-body");
    const m = mode();
    if (!body || m === "none") return;
    if (!opening) section.classList.add("closing"); // тело видно, пока сворачивается
    const height = body.scrollHeight;
    const spring = m === "spring";
    const frames = [
      { height: "0px", opacity: 0, transform: spring ? "translateY(-8px)" : "none", marginTop: "0px" },
      { height: `${height}px`, opacity: 1, transform: "none", marginTop: "10px" },
    ];
    body.style.overflow = "hidden";
    const anim = body.animate(opening ? frames : frames.slice().reverse(), {
      duration: opening ? (spring ? 380 : 240) : 200,
      easing: opening ? (spring ? SPRING : EASE) : "ease-in",
    });
    const done = () => {
      body.style.overflow = "";
      section.classList.remove("closing");
    };
    anim.onfinish = done;
    anim.oncancel = done;
  }

  const sectionObserver = new MutationObserver((records) => {
    for (const record of records) {
      const section = record.target;
      const old = (record.oldValue || "").split(/\s+/);
      if (!old.includes("collapsible")) continue; // разметку раздела только что построил sections.js
      const was = old.includes("collapsed");
      const now = section.classList.contains("collapsed");
      if (was !== now && section.classList.contains("collapsible")) animateSection(section, !now);
    }
  });
  for (const section of document.querySelectorAll(".section")) {
    sectionObserver.observe(section, { attributes: true, attributeFilter: ["class"], attributeOldValue: true });
  }

  // --- Строки состояния: новое сообщение мягко проявляется ---
  const statusObserver = new MutationObserver((records) => {
    if (mode() === "none") return;
    const seen = new Set();
    for (const record of records) {
      const line = record.target.nodeType === 1 ? record.target : record.target.parentElement;
      if (!line || seen.has(line) || !line.textContent.trim()) continue;
      seen.add(line);
      line.animate(
        [{ opacity: 0, transform: "translateY(-3px)" }, { opacity: 1, transform: "none" }],
        { duration: mode() === "spring" ? 320 : 200, easing: mode() === "spring" ? SPRING : EASE }
      );
    }
  });
  for (const line of document.querySelectorAll(".status-line")) {
    statusObserver.observe(line, { childList: true, characterData: true, subtree: true });
  }

  // --- Выбор на вкладке «Оформление» ---
  const select = document.getElementById("ui-motion");
  if (select) {
    select.value = mode();
    select.addEventListener("change", () => {
      root.dataset.motion = select.value;
      try {
        localStorage.setItem(STORAGE_KEY, select.value);
      } catch (e) {
        // без хранилища выбор продержится до перезапуска
      }
      // Сразу показать, как это выглядит: раздел «Анимации» появляется заново
      const section = select.closest(".section");
      const make = PANEL_IN[select.value];
      if (section && make) section.animate(make(1).frames, make(1).options);
    });
  }
})();
