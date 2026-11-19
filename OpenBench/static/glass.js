(() => {
  const root = document.documentElement;
  const chromium = !!window.chrome || (navigator.userAgentData?.brands ?? []).some(b => /Chromium/.test(b.brand)) || /HeadlessChrome|Chrome\//.test(navigator.userAgent);
  const calm = matchMedia('(prefers-reduced-transparency: reduce), (prefers-contrast: more)');
  if (!chromium || !CSS.supports('backdrop-filter', 'blur(1px)')) return;

  const NS = 'http://www.w3.org/2000/svg';
  const defs = document.createElementNS(NS, 'svg');
  const attrs = (el, values) => { for (const [k, v] of Object.entries(values)) el.setAttribute(k, v); };
  attrs(defs, { 'aria-hidden': 'true', width: '0', height: '0' });
  defs.style.cssText = 'position:absolute;width:0;height:0;overflow:hidden';
  document.body.appendChild(defs);
  const cache = new Map(); let uid = 0, sweeping = 0;

  function drawMap(w, h, r, bezel, exp) {
    const c = document.createElement('canvas'); c.width = w; c.height = h;
    const ctx = c.getContext('2d'), img = ctx.createImageData(w, h), d = img.data;
    const hw = w / 2, hh = h / 2; r = Math.min(r, hw, hh); bezel = Math.min(bezel, hw, hh);
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      const px = x + 0.5 - hw, py = y + 0.5 - hh, qx = Math.abs(px) - (hw - r), qy = Math.abs(py) - (hh - r);
      let dist, nx, ny;
      if (qx > 0 && qy > 0) { const l = Math.hypot(qx, qy) || 1; dist = r - l; nx = qx / l; ny = qy / l; }
      else if (qx > qy) { dist = r - qx; nx = 1; ny = 0; } else { dist = r - qy; nx = 0; ny = 1; }
      const i = (y * w + x) * 4;
      if (dist < 0 || dist >= bezel) { d[i] = 128; d[i + 1] = 128; d[i + 2] = 0; d[i + 3] = 255; continue; }
      const t = dist / bezel, s = Math.pow(1 - t, exp);
      d[i] = 128 - Math.sign(px) * nx * s * 127; d[i + 1] = 128 - Math.sign(py) * ny * s * 127;
      d[i + 2] = 255 * Math.min(1, (1 - t) * 1.6); d[i + 3] = 255;
    }
    ctx.putImageData(img, 0, 0); return c.toDataURL('image/png');
  }

  function acquire(w, h, r, o) {
    const key = [w, h, r, ...Object.values(o)].join('/');
    const had = cache.get(key); if (had) { had.users++; return key; }
    const id = 'lg-' + (++uid), f = document.createElementNS(NS, 'filter');
    attrs(f, { id, filterUnits: 'userSpaceOnUse', primitiveUnits: 'userSpaceOnUse', x: 0, y: 0, width: w, height: h, 'color-interpolation-filters': 'sRGB' });
    f.innerHTML =
      `<feImage href="${drawMap(w, h, r, o.bezel, o.exp)}" x="0" y="0" width="${w}" height="${h}" preserveAspectRatio="none" result="map"/>` +
      `<feDisplacementMap in="SourceGraphic" in2="map" scale="${o.scale}" xChannelSelector="R" yChannelSelector="G" result="bent"/>` +
      `<feGaussianBlur in="bent" stdDeviation="${o.frost}" edgeMode="duplicate" result="frost"/>` +
      `<feGaussianBlur in="bent" stdDeviation="${o.clear}" edgeMode="duplicate" result="clear"/>` +
      `<feColorMatrix in="map" type="matrix" values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 ${o.rim} 0 0" result="rim"/>` +
      `<feComposite in="clear" in2="rim" operator="in" result="edge"/>` +
      `<feMerge result="glass"><feMergeNode in="frost"/><feMergeNode in="edge"/></feMerge>` +
      `<feColorMatrix in="glass" type="saturate" values="${o.sat}" result="sat"/>` +
      `<feComponentTransfer in="sat"><feFuncR type="linear" slope="1.06"/><feFuncG type="linear" slope="1.06"/><feFuncB type="linear" slope="1.06"/></feComponentTransfer>`;
    defs.appendChild(f); cache.set(key, { id, node: f, users: 1 }); return key;
  }
  function release(el) {
    const f = el.__lensKey && cache.get(el.__lensKey); el.__lensKey = null;
    if (f && --f.users <= 0 && !sweeping) sweeping = setTimeout(() => {
      sweeping = 0; cache.forEach((x, k) => { if (x.users <= 0) { x.node.remove(); cache.delete(k); } });
    });
  }

  const headerIsContent = matchMedia('(min-width: 701px)');
  const plain = el => headerIsContent.matches && !!el.closest('#toolbar');
  const LENS = { bezel: 14, scale: 14, exp: 1.5, frost: 9, clear: 0.6, sat: 1.7, rim: 0.9 };
  function apply(el) {
    if (calm.matches || plain(el)) { el.style.removeProperty('--lens'); el.__lens = null; release(el); return; }
    const b = el.getBoundingClientRect(), w = Math.round(b.width), h = Math.round(b.height);
    if (w < 8 || h < 8) return;
    const r = parseFloat(getComputedStyle(el).borderTopLeftRadius) || 0;
    const o = {}; for (const [k, v] of Object.entries(LENS)) o[k] = +(el.getAttribute('data-lens-' + k) ?? v);
    const sig = [w, h, r].join('x'); if (el.__lens === sig) return; el.__lens = sig;
    const key = acquire(w, h, Math.round(r), o); release(el); el.__lensKey = key;
    el.style.setProperty('--lens', `url(#${cache.get(key).id})`);
  }

  const pending = new Set(); let timer = 0;
  const ro = new ResizeObserver(es => {
    for (const e of es) { const big = e.target.offsetHeight > 300; if (big && e.target.__lens) pending.add(e.target); else apply(e.target); }
    if (pending.size) { clearTimeout(timer); timer = setTimeout(() => { pending.forEach(apply); pending.clear(); }, 160); }
  });
  const lensesIn = node => (node.matches?.('[data-lens]') ? [node] : []).concat([...node.querySelectorAll('[data-lens]')]);
  const watch = el => { ro.observe(el); apply(el); };
  const reapply = el => { el.__lens = null; apply(el); };
  root.classList.add('lg-lens');
  lensesIn(document).forEach(watch);
  document.addEventListener('toggle', e => { if (e.newState === 'open' && e.target.matches?.('[data-lens]')) reapply(e.target); }, true);
  const forget = el => { ro.unobserve(el); if (!el.isConnected) { release(el); el.__lens = null; } };
  new MutationObserver(ms => {
    for (const m of ms) {
      m.removedNodes.forEach(n => { if (n.nodeType === 1) lensesIn(n).forEach(forget); });
      m.addedNodes.forEach(n => { if (n.nodeType === 1 && !n.closest('svg')) lensesIn(n).forEach(watch); });
    }
  }).observe(document.body, { childList: true, subtree: true });
  for (const query of [calm, headerIsContent]) query.addEventListener('change', () => lensesIn(document).forEach(reapply));
})();
