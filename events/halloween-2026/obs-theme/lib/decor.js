// EVENT: halloween-2026 — ВРЕМЕННО. Вся папка events/halloween-2026/obs-theme удаляется после 1 ноября 2026.
//
// Векторные украшения без картинок: паутина, тыква, летучая мышь. Всё рисуется кодом,
// поэтому никаких чужих файлов и лицензий.
(function () {
  "use strict";

  // Паутина в углу: лучи из угла и провисающие нити между ними.
  // corner: "tl" | "tr" | "bl" | "br". Возвращает строку <svg>.
  function cobweb(size, corner, seed) {
    let r = seed || 7;
    const rnd = () => ((r = (r * 9301 + 49297) % 233280) / 233280);
    const rays = 7, rings = 7;
    const angles = [];
    for (let i = 0; i < rays; i++) angles.push((Math.PI / 2) * (i / (rays - 1)) + (rnd() - 0.5) * 0.08);
    const len = angles.map(() => size * (0.92 + rnd() * 0.1));
    let d = "";
    angles.forEach((a, i) => { d += `M0 0L${Math.cos(a) * len[i]} ${Math.sin(a) * len[i]}`; });
    for (let k = 1; k <= rings; k++) {
      const base = (size * k) / (rings + 0.6);
      for (let i = 0; i < rays - 1; i++) {
        const r1 = base * (0.95 + rnd() * 0.1), r2 = base * (0.95 + rnd() * 0.1);
        const a1 = angles[i], a2 = angles[i + 1];
        const x1 = Math.cos(a1) * r1, y1 = Math.sin(a1) * r1;
        const x2 = Math.cos(a2) * r2, y2 = Math.sin(a2) * r2;
        const am = (a1 + a2) / 2, sag = base * 0.82;
        d += `M${x1.toFixed(1)} ${y1.toFixed(1)}Q${(Math.cos(am) * sag).toFixed(1)} ${(Math.sin(am) * sag).toFixed(1)} ${x2.toFixed(1)} ${y2.toFixed(1)}`;
      }
    }
    const flip = { tl: "", tr: `translate(${size} 0) scale(-1 1)`, bl: `translate(0 ${size}) scale(1 -1)`, br: `translate(${size} ${size}) scale(-1 -1)` }[corner || "tl"];
    return `<svg class="hw-web" viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" aria-hidden="true">
      <g transform="${flip}" fill="none" stroke-linecap="round">
        <path d="${d}" stroke="rgba(0,0,0,0.45)" stroke-width="3"/>
        <path d="${d}" stroke="rgba(235,235,255,0.78)" stroke-width="1.2"/>
      </g></svg>`;
  }

  // Тыква-фонарь. Лицо светится, свет внутри мерцает (класс .hw-flicker в CSS страницы).
  function pumpkin(size) {
    return `<svg class="hw-pumpkin" viewBox="0 0 200 190" width="${size}" height="${size * 0.95}" aria-hidden="true">
      <defs>
        <radialGradient id="pk" cx="45%" cy="40%" r="65%">
          <stop offset="0" stop-color="#ffb24a"/><stop offset="0.55" stop-color="#f26a0c"/><stop offset="1" stop-color="#8a2c00"/>
        </radialGradient>
        <radialGradient id="pkLight" cx="50%" cy="55%" r="55%">
          <stop offset="0" stop-color="#fff6b0"/><stop offset="0.5" stop-color="#ffd23a"/><stop offset="1" stop-color="#ff8a00"/>
        </radialGradient>
      </defs>
      <path d="M96 30 C94 14 102 4 116 0 L120 8 C110 12 106 20 108 32 Z" fill="#4f6b1f"/>
      <ellipse cx="60" cy="110" rx="52" ry="70" fill="url(#pk)"/>
      <ellipse cx="140" cy="110" rx="52" ry="70" fill="url(#pk)"/>
      <ellipse cx="100" cy="108" rx="48" ry="76" fill="url(#pk)"/>
      <path d="M80 40 Q72 108 82 180 M120 40 Q128 108 118 180" stroke="rgba(90,25,0,0.45)" stroke-width="3" fill="none"/>
      <g class="hw-flicker" fill="url(#pkLight)">
        <path d="M48 88 L74 70 L80 100 Z"/>
        <path d="M152 88 L126 70 L120 100 Z"/>
        <path d="M92 108 L100 92 L108 108 Z"/>
        <path d="M40 124 Q100 170 160 124 L148 128 L140 140 L128 132 L116 146 L100 136 L84 146 L72 132 L60 140 L52 128 Z"/>
      </g>
    </svg>`;
  }

  // Летучая мышь: крылья машут через CSS (.hw-bat .wing).
  function bat(size) {
    return `<svg class="hw-bat" viewBox="-60 -24 120 48" width="${size}" height="${size * 0.4}" aria-hidden="true">
      <g fill="#07040a">
        <path class="wing wl" d="M-6 -2 C-18 -18 -40 -20 -58 -8 C-48 -6 -44 0 -46 6 C-38 0 -30 2 -28 8 C-22 2 -14 4 -10 8 Z"/>
        <path class="wing wr" d="M6 -2 C18 -18 40 -20 58 -8 C48 -6 44 0 46 6 C38 0 30 2 28 8 C22 2 14 4 10 8 Z"/>
        <ellipse cx="0" cy="2" rx="8" ry="10"/>
        <path d="M-6 -6 L-5 -14 L-1 -8 Z M6 -6 L5 -14 L1 -8 Z"/>
      </g>
      <circle cx="-3" cy="-2" r="1.3" fill="#ff3b2b"/><circle cx="3" cy="-2" r="1.3" fill="#ff3b2b"/>
    </svg>`;
  }

  // Маленький паук для украшений (рамка, алерты), вид сверху, головой вниз.
  function tinySpider(size) {
    const legs = [[-1, 1], [1, 1]].map(([sx]) => [
      `M${sx * 5} -6 Q${sx * 16} -16 ${sx * 20} -4`,
      `M${sx * 6} -2 Q${sx * 20} -6 ${sx * 24} 6`,
      `M${sx * 6} 2 Q${sx * 18} 6 ${sx * 20} 16`,
      `M${sx * 5} 5 Q${sx * 13} 14 ${sx * 12} 24`,
    ].join("")).join("");
    return `<svg class="hw-tiny-spider" viewBox="-28 -30 56 60" width="${size}" height="${size * 1.07}" aria-hidden="true">
      <g class="legs" fill="none" stroke="#0a0709" stroke-width="2.6" stroke-linecap="round"><path d="${legs}"/></g>
      <ellipse cx="0" cy="-9" rx="10" ry="12" fill="#0a0709"/>
      <path d="M0 -15 L-3 -9 L0 -3 L3 -9 Z" fill="#ff5a0a"/>
      <circle cx="0" cy="6" r="7" fill="#120b10"/>
      <circle cx="-2.4" cy="9" r="1.4" fill="#ff2b2b"/><circle cx="2.4" cy="9" r="1.4" fill="#ff2b2b"/>
    </svg>`;
  }

  window.HWDecor = { cobweb, pumpkin, bat, tinySpider };
})();
