// Сворачиваемые разделы вкладки «Настройки»: на первом экране остаётся только нужное,
// остальное раскрывается по клику. Выбор запоминается в браузере.
// Разметка не меняется: скрипт сам оборачивает заголовок раздела в строку с кнопкой.
(() => {
  "use strict";

  const STORAGE_KEY = "sections";
  const OPEN_BY_DEFAULT = new Set(["words-section", "model-section", "obs-section"]);
  const container = document.getElementById("tab-settings");
  if (!container) return;

  let saved = {};
  try {
    saved = JSON.parse(localStorage.getItem(STORAGE_KEY)) || {};
  } catch (e) {
    saved = {};
  }

  function remember() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(saved));
    } catch (e) {
      // без хранилища просто не запомним
    }
  }

  function setOpen(section, open, store) {
    if (!section || !section.classList.contains("collapsible")) return;
    section.classList.toggle("collapsed", !open);
    const button = section.querySelector(":scope > .section-head > .section-toggle");
    if (button) button.setAttribute("aria-expanded", String(open));
    if (store && section.id) {
      saved[section.id] = open;
      remember();
    }
  }

  function enhance(section) {
    if (section.classList.contains("collapsible")) return;
    const title = section.querySelector(":scope > .section-title");
    if (!title || section.querySelector(":scope > .section-head")) return;
    const head = document.createElement("div");
    head.className = "section-head";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "section-toggle";
    const body = document.createElement("div");
    body.className = "section-body";
    section.classList.add("collapsible");
    // Всё, что идёт после заголовка, уходит в тело раздела, которое сворачивается целиком.
    while (title.nextSibling) body.append(title.nextSibling);
    title.replaceWith(head);
    head.append(button, title);
    section.append(body);
    if (section.id) body.id = `${section.id}-body`;
    if (section.id) button.setAttribute("aria-controls", body.id);
    const open = section.id in saved ? saved[section.id] : OPEN_BY_DEFAULT.has(section.id);
    // Раздел без id (о программе) остаётся раскрытым.
    setOpen(section, section.id ? open : true, false);
    const toggle = (event) => {
      event.preventDefault();
      setOpen(section, section.classList.contains("collapsed"), true);
    };
    button.addEventListener("click", toggle);
    // Заголовок — часть кнопки для мыши; <label for> иначе перекинул бы фокус в поле.
    title.addEventListener("click", toggle);
  }

  for (const section of container.querySelectorAll(":scope > .section")) enhance(section);
  window.setSectionOpen = (node, open) => {
    const section = node.closest ? node.closest(".section") : null;
    if (section) setOpen(section, open, false);
  };
})();
