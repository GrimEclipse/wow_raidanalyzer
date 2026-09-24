(() => {
  const canvas = document.createElement('canvas');
  canvas.id = 'cosmicCanvas';
  canvas.setAttribute('aria-hidden', 'true');
  document.body.prepend(canvas);
  const context = canvas.getContext('2d', {alpha: true});
  if (!context) return;

  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
  let width = 0;
  let height = 0;
  let ratio = 1;
  let flecks = [];
  let lastFrame = 0;

  function resize() {
    width = innerWidth;
    height = innerHeight;
    ratio = Math.min(devicePixelRatio || 1, 1.6);
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    const count = Math.min(85, Math.max(24, Math.round(width * height / 18000)));
    flecks = Array.from({length: count}, () => ({
      x: Math.random() * width,
      y: Math.random() * height,
      size: .35 + Math.random() * .8,
      opacity: .13 + Math.random() * .23,
      phase: Math.random() * Math.PI * 2,
      speed: .00015 + Math.random() * .00028,
    }));
    if (reducedMotion) draw(performance.now());
  }

  function draw(time) {
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, width, height);
    for (const fleck of flecks) {
      const drift = reducedMotion ? 0 : Math.sin(time * fleck.speed + fleck.phase) * 3;
      const shimmer = reducedMotion ? 1 : .8 + Math.sin(time * fleck.speed * 1.4 + fleck.phase) * .2;
      context.beginPath();
      context.arc(fleck.x + drift, fleck.y, fleck.size, 0, Math.PI * 2);
      context.fillStyle = `rgba(188, 218, 245, ${fleck.opacity * shimmer})`;
      context.fill();
    }
    if (!reducedMotion) requestAnimationFrame(frame);
  }

  function frame(time) {
    if (time - lastFrame < 45) {
      requestAnimationFrame(frame);
      return;
    }
    lastFrame = time;
    draw(time);
  }

  addEventListener('resize', resize, {passive: true});
  resize();
  if (!reducedMotion) requestAnimationFrame(frame);
})();
