// EVENT: halloween-2026 — ВРЕМЕННО. Вся папка events/halloween-2026/obs-theme удаляется после 1 ноября 2026.
//
// Пауки на canvas, вид сверху. Ноги переставляются как у настоящего паука:
// ступня стоит на месте, пока тело не уйдёт от неё дальше шага, потом переносится вперёд.
// Ноги ходят двумя четвёрками по очереди (L1 R2 L3 R4 / R1 L2 R3 L4).
(function () {
  "use strict";

  const TAU = Math.PI * 2;
  const rand = (a, b) => a + Math.random() * (b - a);
  const lerp = (a, b, t) => a + (b - a) * t;

  // Тело в своих координатах: x вперёд, y вбок. Размеры для масштаба 1.
  const FEMUR = 26;
  const HIPS = [[9, 5], [5, 7], [0, 7], [-4, 6]];
  const REST_ANGLES = [36, 72, 116, 152].map((a) => (a * Math.PI) / 180);
  const REST_DIST = 47;
  const GROUP = [[0, 1, 0, 1], [1, 0, 1, 0]]; // [сторона][нога] → четвёрка

  class Spider {
    constructor(opts) {
      this.s = opts.scale || 1;
      this.x = opts.x; this.y = opts.y;
      this.h = opts.heading || 0;
      this.speed = 0;
      this.maxSpeed = (opts.speed || 520) * Math.sqrt(this.s);
      this.path = opts.path || [];
      this.mode = opts.mode || "run";
      this.dead = false;
      this.t = 0;
      this.burst = 0; // время до следующей смены «бежит / замер»
      this.running = true;
      this.color = opts.color || "#0a0709";
      this.mark = opts.mark || "#ff5a0a";
      this.drop = opts.drop || null;
      this.legs = [];
      for (let side = 0; side < 2; side++) {
        for (let i = 0; i < 4; i++) {
          const rest = this.restWorld(side, i);
          this.legs.push({ side, i, group: GROUP[side][i], foot: rest, from: rest, to: rest, step: -1 });
        }
      }
    }

    local(lx, ly) {
      const c = Math.cos(this.h), s = Math.sin(this.h);
      return { x: this.x + (lx * c - ly * s) * this.s, y: this.y + (lx * s + ly * c) * this.s };
    }
    hip(side, i) { const [hx, hy] = HIPS[i]; return this.local(hx, side ? hy : -hy); }
    restWorld(side, i, lead = 0) {
      const [hx, hy] = HIPS[i];
      const a = REST_ANGLES[i] * (side ? 1 : -1);
      return this.local(hx + Math.cos(a) * REST_DIST + lead, (side ? hy : -hy) + Math.sin(a) * REST_DIST);
    }

    update(dt, W, H) {
      this.t += dt;
      if (this.drop) return this.updateDrop(dt);

      // Перебежками: паук срывается с места, замирает и бежит дальше.
      this.burst -= dt;
      if (this.burst <= 0) {
        this.running = this.mode === "big" || !this.running || Math.random() < 0.35;
        this.burst = this.running ? rand(0.5, 1.4) : rand(0.12, 0.5);
      }
      const target = this.path[0];
      if (!target) { this.dead = true; return; }
      const dx = target.x - this.x, dy = target.y - this.y;
      const dist = Math.hypot(dx, dy);
      if (dist < 40 * this.s) { this.path.shift(); }
      let want = Math.atan2(dy, dx) - this.h;
      want = ((want + Math.PI) % TAU + TAU) % TAU - Math.PI;
      const turn = 4.5 * dt;
      this.h += Math.max(-turn, Math.min(turn, want)) + Math.sin(this.t * 9) * 0.004;
      const goal = this.running ? this.maxSpeed : 0;
      this.speed = lerp(this.speed, goal, Math.min(1, dt * (this.running ? 6 : 14)));
      this.x += Math.cos(this.h) * this.speed * dt;
      this.y += Math.sin(this.h) * this.speed * dt;
      this.updateLegs(dt);

      // Ушёл за край и пути больше нет — убираем.
      const m = 140 * this.s;
      if (!this.path.length && (this.x < -m || this.x > W + m || this.y < -m || this.y > H + m)) this.dead = true;
    }

    updateLegs(dt) {
      const stride = 18, lead = stride * 0.8;
      // Длительность шага подбираем под скорость: за два шага (обе четвёрки) тело проходит stride + lead.
      const v = Math.max(1, this.speed / this.s);
      const stepTime = Math.min(0.14, Math.max(0.035, (0.9 * stride) / v));
      const busy = [false, false];
      for (const l of this.legs) if (l.step >= 0) busy[l.group] = true;
      for (const l of this.legs) {
        if (l.step >= 0) {
          l.step += dt / stepTime;
          const k = Math.min(1, l.step);
          const e = k * k * (3 - 2 * k);
          // Цель шага едет вместе с телом, чтобы нога не отставала на бегу.
          l.to = this.restWorld(l.side, l.i, l.lead);
          l.foot = { x: lerp(l.from.x, l.to.x, e), y: lerp(l.from.y, l.to.y, e) };
          if (k >= 1) l.step = -1;
          continue;
        }
        const rest = this.restWorld(l.side, l.i);
        const off = Math.hypot(l.foot.x - rest.x, l.foot.y - rest.y) / this.s;
        // Вторая четвёрка ждёт, пока первая опустит ноги: так походка не разваливается.
        // Но если нога совсем отстала (резкий разворот), шагает сразу.
        if ((off > stride && !busy[1 - l.group]) || off > stride * 1.7) {
          l.from = l.foot;
          l.lead = this.speed > 5 ? lead : 0;
          l.step = 0;
          busy[l.group] = true;
        }
      }
    }

    // Спуск на паутине: опускается, шевелит лапами, уползает обратно вверх.
    updateDrop(dt) {
      const d = this.drop;
      d.t += dt;
      const down = 1.6, hold = d.hold, up = 0.9;
      let k;
      if (d.t < down) { const u = d.t / down; k = 1 - Math.pow(1 - u, 3) * Math.cos(u * 9) * (1 - u); }
      else if (d.t < down + hold) k = 1 + Math.sin((d.t - down) * 2.4) * 0.03;
      else if (d.t < down + hold + up) { const u = (d.t - down - hold) / up; k = 1 - u * u; }
      else { this.dead = true; return; }
      this.x = d.x + Math.sin(this.t * 1.7) * 6 * this.s;
      this.y = lerp(-60 * this.s, d.y, k);
      this.h = Math.PI / 2 + Math.sin(this.t * 1.7) * 0.05;
      for (const l of this.legs) {
        const rest = this.restWorld(l.side, l.i);
        const w = Math.sin(this.t * 11 + l.i * 1.3 + l.side * 2) * 5 * this.s;
        l.foot = { x: rest.x + w, y: rest.y + w * 0.6 };
        l.step = -1;
      }
    }

    draw(g) {
      const s = this.s;
      if (this.drop) {
        g.strokeStyle = "rgba(240,240,255,0.55)";
        g.lineWidth = Math.max(1, s * 0.8);
        g.beginPath(); g.moveTo(this.drop.x, -10); g.lineTo(this.x, this.y - 18 * s); g.stroke();
      }

      // Тень под пауком: видно и на тёмной игре, и на светлой. Градиент вместо filter: blur —
      // blur на каждом пауке заметно грузит CEF, когда пауков стая.
      g.save();
      const sh = this.local(-6, 0);
      g.translate(sh.x + 6 * s, sh.y + 8 * s);
      g.rotate(this.h);
      g.scale(1, 0.78);
      const sg = g.createRadialGradient(0, 0, 0, 0, 0, 40 * s);
      sg.addColorStop(0, "rgba(0,0,0,0.38)"); sg.addColorStop(1, "rgba(0,0,0,0)");
      g.fillStyle = sg;
      g.beginPath(); g.arc(0, 0, 40 * s, 0, TAU); g.fill();
      g.restore();

      for (const l of this.legs) this.drawLeg(g, l);

      // Брюшко с оранжевыми «песочными часами», головогрудь, глаза.
      g.save();
      g.translate(this.x, this.y);
      g.rotate(this.h);
      g.scale(s, s);
      const breathe = 1 + Math.sin(this.t * 3) * 0.02;
      const ab = g.createRadialGradient(-24, -6, 2, -22, 0, 22);
      ab.addColorStop(0, "#3a2a33"); ab.addColorStop(0.5, "#140c11"); ab.addColorStop(1, this.color);
      g.fillStyle = ab;
      g.beginPath(); g.ellipse(-22, 0, 21 * breathe, 16 * breathe, 0, 0, TAU); g.fill();
      g.strokeStyle = "rgba(255,255,255,0.10)"; g.lineWidth = 1.2; g.stroke();
      g.fillStyle = this.mark;
      g.shadowColor = this.mark; g.shadowBlur = 8;
      g.beginPath();
      g.moveTo(-31, -3.4); g.lineTo(-22.5, 0); g.lineTo(-31, 3.4); g.closePath();
      g.moveTo(-14, -3.4); g.lineTo(-21.5, 0); g.lineTo(-14, 3.4); g.closePath();
      g.fill();
      g.shadowBlur = 0;
      const ce = g.createRadialGradient(6, -3, 1, 6, 0, 12);
      ce.addColorStop(0, "#2e2228"); ce.addColorStop(1, this.color);
      g.fillStyle = ce;
      g.beginPath(); g.ellipse(5, 0, 12, 10, 0, 0, TAU); g.fill();
      g.strokeStyle = "rgba(255,255,255,0.10)"; g.stroke();
      // Хелицеры
      g.fillStyle = this.color;
      g.beginPath(); g.ellipse(17, -3, 4, 2.4, 0.3, 0, TAU); g.ellipse(17, 3, 4, 2.4, -0.3, 0, TAU); g.fill();
      // Глаза
      g.fillStyle = "#ff2b2b"; g.shadowColor = "#ff1a1a"; g.shadowBlur = 10;
      g.beginPath();
      for (const [ex, ey, r] of [[13, -3.2, 1.9], [13, 3.2, 1.9], [10.5, -5.5, 1.2], [10.5, 5.5, 1.2]]) {
        g.moveTo(ex + r, ey); g.arc(ex, ey, r, 0, TAU);
      }
      g.fill();
      g.restore();
    }

    drawLeg(g, l) {
      const s = this.s;
      const hip = this.hip(l.side, l.i);
      const f = l.foot;
      // Колено: от бедра в сторону ступни, но с уводом вбок от тела — ноги выгибаются
      // дугой наружу и не перекрещиваются. Голень просто тянется от колена к ступне.
      const L1 = FEMUR * s;
      const fd = Math.hypot(f.x - hip.x, f.y - hip.y) || 1;
      const out = l.side ? 1 : -1;
      const ox = -Math.sin(this.h) * out, oy = Math.cos(this.h) * out;
      let kdx = (f.x - hip.x) / fd + ox * 0.65, kdy = (f.y - hip.y) / fd + oy * 0.65;
      const kd = Math.hypot(kdx, kdy) || 1;
      const reach = Math.min(L1, fd * 0.62);
      const kx = hip.x + (kdx / kd) * reach, ky = hip.y + (kdy / kd) * reach;
      const lift = l.step >= 0 ? Math.sin(Math.min(1, l.step) * Math.PI) : 0;
      g.lineCap = "round"; g.lineJoin = "round";
      g.strokeStyle = "rgba(255,255,255,0.10)";
      g.lineWidth = (4.6 + lift * 1.4) * s;
      g.beginPath(); g.moveTo(hip.x, hip.y); g.lineTo(kx, ky); g.lineTo(f.x, f.y); g.stroke();
      g.strokeStyle = this.color;
      g.lineWidth = (3.4 + lift * 1.4) * s;
      g.beginPath(); g.moveTo(hip.x, hip.y); g.lineTo(kx, ky); g.stroke();
      g.lineWidth = (2.3 + lift) * s;
      g.beginPath(); g.moveTo(kx, ky); g.lineTo(f.x, f.y); g.stroke();
      g.fillStyle = "#24161c";
      g.beginPath(); g.arc(kx, ky, 2.2 * s, 0, TAU); g.fill();
    }
  }

  // --- Сцена: canvas во весь источник и сценарии появления ---
  function Swarm(canvas) {
    const g = canvas.getContext("2d");
    let W = 0, H = 0, list = [], last = 0, running = false;
    const MAX = 40;

    function resize() {
      const dpr = window.devicePixelRatio || 1;
      W = canvas.clientWidth; H = canvas.clientHeight;
      canvas.width = W * dpr; canvas.height = H * dpr;
      g.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    window.addEventListener("resize", resize);
    resize();

    function frame(now) {
      const dt = Math.min(0.05, (now - last) / 1000 || 0);
      last = now;
      g.clearRect(0, 0, W, H);
      for (const sp of list) sp.update(dt, W, H);
      list = list.filter((sp) => !sp.dead);
      for (const sp of list) sp.draw(g);
      if (list.length) requestAnimationFrame(frame); else { running = false; g.clearRect(0, 0, W, H); }
    }
    function add(sp) {
      if (list.length >= MAX) return;
      list.push(sp);
      if (!running) { running = true; last = performance.now(); requestAnimationFrame(frame); }
    }

    // Путь через экран: старт за одним краем, пара точек внутри, выход за противоположным.
    function crossPath(scale, from) {
      const m = 120 * scale;
      const edge = from || ["left", "right", "top", "bottom"][Math.floor(Math.random() * 4)];
      const pts = {
        left: [{ x: -m, y: rand(0.15, 0.85) * H }, { x: W + m, y: rand(0.15, 0.85) * H }],
        right: [{ x: W + m, y: rand(0.15, 0.85) * H }, { x: -m, y: rand(0.15, 0.85) * H }],
        top: [{ x: rand(0.15, 0.85) * W, y: -m }, { x: rand(0.15, 0.85) * W, y: H + m }],
        bottom: [{ x: rand(0.15, 0.85) * W, y: H + m }, { x: rand(0.15, 0.85) * W, y: -m }],
      }[edge];
      const [a, b] = pts;
      const mid = [];
      const n = 2 + Math.floor(Math.random() * 2);
      for (let i = 1; i <= n; i++) {
        const t = i / (n + 1);
        mid.push({ x: lerp(a.x, b.x, t) + rand(-0.15, 0.15) * W, y: lerp(a.y, b.y, t) + rand(-0.18, 0.18) * H });
      }
      return { start: a, path: mid.concat([b]), heading: Math.atan2(b.y - a.y, b.x - a.x), edge };
    }

    function run(o = {}) {
      const scale = o.scale || rand(0.9, 1.3);
      const p = crossPath(scale, o.from);
      add(new Spider({ x: p.start.x, y: p.start.y, heading: p.heading, path: p.path, scale, speed: o.speed }));
    }
    function swarm(o = {}) {
      const n = Math.min(MAX, o.count || 10);
      const edge = o.from || ["left", "right", "top", "bottom"][Math.floor(Math.random() * 4)];
      for (let i = 0; i < n; i++) {
        setTimeout(() => run({ scale: rand(0.45, 0.95), from: edge, speed: rand(420, 640) }), i * rand(60, 180));
      }
    }
    function drop(o = {}) {
      const scale = o.scale || 1.7;
      const x = o.x != null ? o.x * W : rand(0.15, 0.85) * W;
      const y = o.y != null ? o.y * H : rand(0.25, 0.45) * H;
      add(new Spider({ x, y: -60, scale, drop: { x, y, t: 0, hold: o.hold || 2.6 } }));
    }
    function big(o = {}) {
      const scale = o.scale || Math.min(W, H) / 170;
      const fromLeft = Math.random() < 0.5;
      const m = 140 * scale;
      const a = { x: fromLeft ? -m : W + m, y: rand(0.55, 0.9) * H };
      const b = { x: fromLeft ? W + m : -m, y: rand(0.1, 0.45) * H };
      const mid = { x: W / 2 + rand(-0.1, 0.1) * W, y: H / 2 + rand(-0.1, 0.1) * H };
      add(new Spider({ x: a.x, y: a.y, heading: Math.atan2(mid.y - a.y, mid.x - a.x), path: [mid, b],
                       scale, mode: "big", speed: o.speed || 260 }));
    }

    return { run, swarm, drop, big, count: () => list.length };
  }

  window.HWSpider = { Spider, Swarm };
})();
