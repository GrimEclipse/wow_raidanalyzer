/* Azeroth UI · 背景余烬：少量暖色火星缓慢上升（替代原星空粒子）。
 * 读取 body[data-cosmic-density] 兼容旧接口，数值越大越少；尊重 prefers-reduced-motion。 */
(() => {
  if (document.getElementById('cosmicCanvas')) return;
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const canvas = document.createElement('canvas');
  canvas.id = 'cosmicCanvas';
  canvas.setAttribute('aria-hidden', 'true');
  document.body.prepend(canvas);
  const ctx = canvas.getContext('2d');
  const densityAttr = Number(document.body.dataset.cosmicDensity) || 420;
  let w = 0, h = 0, dpr = 1, embers = [];

  const spawn = (initial) => ({
    x: Math.random() * w,
    y: initial ? Math.random() * h : h + 10,
    r: .6 + Math.random() * 1.6,
    vy: .12 + Math.random() * .35,
    sway: Math.random() * Math.PI * 2,
    swaySpeed: .004 + Math.random() * .01,
    life: .35 + Math.random() * .65,
    hue: 22 + Math.random() * 22,
  });

  function resize() {
    dpr = Math.min(devicePixelRatio || 1, 2);
    w = innerWidth; h = innerHeight;
    canvas.width = w * dpr; canvas.height = h * dpr;
    canvas.style.width = `${w}px`; canvas.style.height = `${h}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const count = Math.max(10, Math.min(46, Math.round((w * h) / (densityAttr * 90))));
    embers = Array.from({ length: count }, () => spawn(true));
  }

  function draw() {
    ctx.clearRect(0, 0, w, h);
    ctx.globalCompositeOperation = 'lighter';
    for (const e of embers) {
      if (!reduce) { e.y -= e.vy; e.sway += e.swaySpeed; e.x += Math.sin(e.sway) * .25; }
      const fade = Math.max(0, Math.min(1, e.y / h)) * e.life; // 越往上越暗
      if (e.y < -10 || fade <= .01) Object.assign(e, spawn(false));
      const g = ctx.createRadialGradient(e.x, e.y, 0, e.x, e.y, e.r * 5);
      g.addColorStop(0, `hsla(${e.hue},100%,70%,${.85 * fade})`);
      g.addColorStop(.35, `hsla(${e.hue},100%,50%,${.25 * fade})`);
      g.addColorStop(1, 'hsla(20,100%,40%,0)');
      ctx.fillStyle = g;
      ctx.beginPath(); ctx.arc(e.x, e.y, e.r * 5, 0, Math.PI * 2); ctx.fill();
    }
    ctx.globalCompositeOperation = 'source-over';
    if (!reduce && !document.hidden) requestAnimationFrame(draw);
  }

  resize();
  addEventListener('resize', resize, { passive: true });
  document.addEventListener('visibilitychange', () => { if (!document.hidden && !reduce) requestAnimationFrame(draw); });
  draw();
})();
