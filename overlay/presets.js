// Пресеты оформления оверлея.
//
// Общий список для оверлея и страницы управления (можно подключить
// /overlay/presets.js и построить по нему выбор стиля).
// Шрифт, обводка и тени описаны в style.css (селектор [data-preset="<id>"]),
// анимации прибавления — в overlay.js (таблица INCREMENT_ANIMATIONS).
// color — цвет цифр по умолчанию; параметр ?color= в адресе его перекрывает.
// sound — стандартный звук пресета (имя из STANDARD в sound.js); без него — звон.
// У личных оформлений sound — адрес файла из набора.
window.OVERLAY_PRESETS = [
  {
    id: "swearcounter",
    title: "Цензура",
    description: "Фирменный: красная плашка как значок программы, при каждом мате вылетает «#!@%».",
    color: "#ffffff",
  },
  {
    id: "classic",
    title: "Классика",
    description: "Жирные белые цифры с обводкой, подпрыгивание и вспышка.",
    color: "#ffffff",
  },
  {
    id: "impact",
    title: "Мем",
    description: "Шрифт Impact как в мемах, число трясётся при каждом мате.",
    color: "#ffffff",
  },
  {
    id: "neon",
    title: "Неон",
    description: "Голубая неоновая вывеска с розовым свечением и мерцанием.",
    color: "#3ef4ff",
  },
  {
    id: "retro",
    title: "Ретро",
    description: "Моноширинный шрифт и пошаговая анимация, как в старых играх.",
    color: "#ffe14d",
  },
  {
    id: "minimal",
    title: "Минимализм",
    description: "Аккуратный тонкий шрифт без обводки, мягкое появление.",
    color: "#ffffff",
  },
  {
    id: "explosion",
    title: "Взрыв",
    description: "Огненные цифры, резкое увеличение и разлетающиеся искры.",
    color: "#ffb21f",
  },
];

// --- Личные оформления (папка presets/ рядом с программой, см. docs/PRESETS.md) ---
// Оверлей подключает /overlay/custom-presets.js: сервер вызывает там registerCustomPresets
// со списком установленных наборов. У набора свои style.css и animation.js, а
// animation.js регистрирует анимацию прибавления через registerOverlayAnimation.

// id пресета → function (delta, api); ищется раньше встроенных анимаций (overlay.js)
window.OVERLAY_ANIMATIONS = window.OVERLAY_ANIMATIONS || {};

window.registerOverlayAnimation = function registerOverlayAnimation(id, animate) {
  if (typeof id === "string" && typeof animate === "function") window.OVERLAY_ANIMATIONS[id] = animate;
};

// presets — [{id, title, description, color, owner, animation, sound, style, script}]
window.registerCustomPresets = function registerCustomPresets(presets) {
  for (const preset of presets || []) {
    if (window.OVERLAY_PRESETS.some((p) => p.id === preset.id)) continue;
    window.OVERLAY_PRESETS.push(preset);
    if (preset.style) {
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = preset.style;
      // Свой шрифт или размер цифр: пересчитать подгонку под окно (overlay.js слушает resize)
      link.onload = () => window.dispatchEvent(new Event("resize"));
      document.head.appendChild(link);
    }
    if (preset.script) {
      const script = document.createElement("script");
      script.src = preset.script;
      script.async = false; // наборы регистрируются в порядке списка
      document.head.appendChild(script);
    }
  }
};
