(() => {
  const $ = (s, r = document) => r.querySelector(s), $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const root = document.documentElement, main = $('#main');
  const escH = v => String(v).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const hasRepo = names => names.every(f => typeof window[f] === 'function');
  const anchored = CSS.supports('anchor-name: --a');

  const edge = () => {
    root.toggleAttribute('data-scrolled', scrollY > 2);
    const cols = $('.cols');
    if (cols && getComputedStyle(cols).display !== 'none') {
      const top = parseFloat(getComputedStyle(cols).top);
      root.toggleAttribute('data-pinned', scrollY > 2 && cols.getBoundingClientRect().top <= top + .5);
    } else root.removeAttribute('data-pinned');
  };
  addEventListener('scroll', edge, { passive: true }); addEventListener('resize', edge); edge();
  document.addEventListener('verdict:updated', edge);

  function segSync(seg, instant) {
    if (!seg) return;
    let on = seg.querySelector('[aria-pressed="true"], [aria-selected="true"], label:has(:checked), a[aria-current]');
    if (on && !on.offsetWidth && seg.querySelector('.nav-more')) on = seg.querySelector('.nav-more');
    let thumb = seg.querySelector('.seg-thumb');
    if (!thumb) { thumb = document.createElement('span'); thumb.className = 'seg-thumb'; thumb.setAttribute('aria-hidden', 'true'); seg.prepend(thumb); }
    if (!on || !on.offsetWidth) return;
    if (instant) thumb.style.transition = 'none';
    thumb.style.setProperty('--x', on.offsetLeft + 'px'); thumb.style.setProperty('--w', on.offsetWidth + 'px');
    if (instant) { thumb.offsetWidth; thumb.style.transition = ''; }
    seg.dataset.ready = '';
  }
  const segAll = instant => $$('.seg').forEach(s => segSync(s, instant));
  segAll(true); document.fonts.ready.then(() => segAll(true));
  addEventListener('resize', () => segAll(true));

  function setFilter(f, push) {
    if (!main) return;
    if (f === 'all') delete main.dataset.filterOn; else main.dataset.filterOn = f;
    $$('.seg [data-filter]').forEach(x => x.setAttribute('aria-pressed', String(x.dataset.filter === f)));
    segAll();
    if (push) { const u = new URL(location.href); if (f === 'all') u.searchParams.delete('show'); else u.searchParams.set('show', f); history.replaceState(null, '', u); }
  }
  const show = new URL(location.href).searchParams.get('show');
  if (show && $('[data-filter]') && ['active', 'pending', 'finished'].includes(show)) setFilter(show);
  document.addEventListener('click', e => {
    const b = e.target.closest('.seg > button'); if (!b || b.hasAttribute('popovertarget')) return;
    const seg = b.parentElement, attr = b.hasAttribute('aria-selected') ? 'aria-selected' : 'aria-pressed';
    seg.querySelectorAll(':scope > button').forEach(x => x.setAttribute(attr, String(x === b)));
    segSync(seg);
    if (b.dataset.filter) setFilter(b.dataset.filter, true);
    if (b.getAttribute('role') === 'tab') $$('[role="tabpanel"]', seg.closest('section')).forEach(p => { p.hidden = p.id !== b.getAttribute('aria-controls'); });
  });

  document.addEventListener('verdict:pause', e => root.classList.toggle('live-paused', e.detail.paused));
  const liveSrc = $('#live-status');
  const mirror = () => $$('[data-live-mirror]').forEach(m => { m.textContent = liveSrc.textContent; m.closest('.live-state').title = liveSrc.title || ''; });
  if (liveSrc) { new MutationObserver(mirror).observe(liveSrc, { childList: true, characterData: true, subtree: true, attributes: true }); mirror(); }

  const sInput = $('#bar-search'), pop = $('#search-pop'), sForm = sInput?.closest('form');
  if (sForm) sForm.addEventListener('click', e => { if (e.target === sForm || e.target.closest('svg')) sInput.focus(); });
  function applySearch() {
    const list = $('[data-tests]'); if (!list || !sInput) return { q: '', rows: [] };
    const q = sInput.value.trim().toLowerCase(), rows = $$('.trow', list);
    rows.forEach(r => { r.hidden = !!q && !r.textContent.toLowerCase().includes(q); });
    $$('.tgroup', list).forEach(g => { g.hidden = !!q && !g.querySelector('.trow:not([hidden])'); });
    $$('.tsub', list).forEach(t => { let n = t.nextElementSibling, any = false; while (n && !n.matches('.tsub')) { if (!n.hidden) any = true; n = n.nextElementSibling; } t.hidden = !!q && !any; });
    return { q, rows };
  }
  document.addEventListener('verdict:updated', applySearch);
  if (sInput && pop) {
    const popOpen = () => pop.matches(':popover-open');
    const mark = (text, q) => { const i = text.toLowerCase().indexOf(q); return i < 0 ? escH(text) : escH(text.slice(0, i)) + '<mark>' + escH(text.slice(i, i + q.length)) + '</mark>' + escH(text.slice(i + q.length)); };
    const option = (r, q) => { const a = r.querySelector('.t-name'), meta = [...r.querySelector('.t-meta').children].map(c => c.textContent.trim()).join(' · ');
      return `<a role="option" href="${escH(a.getAttribute('href'))}">${r.querySelector('.st').outerHTML}<span class="pop-name"><span>${mark(a.textContent, q)}</span><small>${escH(meta)}</small></span></a>`; };
    const run = () => {
      const { q, rows } = applySearch();
      const hits = q ? rows.filter(r => r.querySelector('.t-name').textContent.toLowerCase().includes(q)).slice(0, 4) : [];
      if (!hits.length) { if (popOpen()) pop.hidePopover(); return; }
      pop.innerHTML = `<div role="group" aria-labelledby="search-pop-label"><p class="pop-label" id="search-pop-label">Tests</p>` + hits.map(r => option(r, q)).join('') + '</div>';
      if (!popOpen()) pop.showPopover();
    };
    sInput.addEventListener('input', run);
    sInput.addEventListener('keydown', e => { if (e.key === 'Escape') { sInput.value = ''; run(); } if (e.key === 'ArrowDown' && popOpen()) { e.preventDefault(); pop.querySelector('a')?.focus(); } });
    pop.addEventListener('keydown', e => { const items = $$('a', pop), i = items.indexOf(document.activeElement);
      if (e.key === 'ArrowDown') { e.preventDefault(); items[Math.min(items.length - 1, i + 1)]?.focus(); }
      if (e.key === 'ArrowUp') { e.preventDefault(); (i <= 0 ? sInput : items[i - 1]).focus(); }
      if (e.key === 'Escape') { pop.hidePopover(); sInput.focus(); } });
    document.addEventListener('pointerdown', e => { if (popOpen() && !pop.contains(e.target) && !e.target.closest('.search')) pop.hidePopover(); });
    if (!anchored) pop.addEventListener('toggle', e => { if (e.newState !== 'open') return; const r = sInput.closest('.search').getBoundingClientRect(); pop.style.top = (r.bottom + 8) + 'px'; pop.style.left = r.left + 'px'; });
  }

  document.addEventListener('keydown', e => {
    if (e.metaKey || e.ctrlKey || e.altKey || e.target.closest('input, textarea, select, [contenteditable]')) return;
    if (e.key === '/') { const s = $('.search input'); if (s && s.offsetParent && !s.closest('[inert]')) { e.preventDefault(); s.focus(); } }
  });
  const menuItems = m => $$('[role="menuitem"]', m).filter(x => x.offsetParent && x.getAttribute('aria-disabled') !== 'true');
  document.addEventListener('keydown', e => {
    const m = e.target.closest?.('.menu[role="menu"]'); if (!m || !['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)) return;
    const it = menuItems(m), i = it.indexOf(document.activeElement); if (!it.length) return; e.preventDefault();
    const nx = e.key === 'Home' ? 0 : e.key === 'End' ? it.length - 1 : (i + (e.key === 'ArrowDown' ? 1 : -1) + it.length) % it.length;
    it[nx].focus();
  });
  const placeMenu = m => {
    const btn = $$(`[popovertarget="${m.id}"]`).find(b => b.offsetParent); if (!btn) return;
    const r = btn.getBoundingClientRect(), fromLeft = btn.matches('.tb-account, .nav-more');
    Object.assign(m.style, { top: (r.bottom + 8) + 'px', bottom: '', left: fromLeft ? r.left + 'px' : '', right: fromLeft ? '' : (innerWidth - r.right) + 'px' });
  };
  document.addEventListener('toggle', e => {
    const m = e.target; if (e.newState !== 'open' || !m.matches?.('.menu')) return;
    if (!anchored && m.id !== 'search-pop') placeMenu(m);
    if (m.matches('[role="menu"]')) requestAnimationFrame(() => { const first = menuItems(m)[0]; if (!first && !m.hasAttribute('tabindex')) m.tabIndex = -1; (first || m).focus({ preventScroll: true }); });
  }, true);

  document.addEventListener('click', e => {
    const b = e.target.closest('[data-copy]'); if (!b || !hasRepo(['copy_text_from_element'])) return;
    window.copy_text_from_element(b.dataset.copy, true); b.dataset.done = ''; setTimeout(() => delete b.dataset.done, 1400);
  });

  if (hasRepo(['start_workload_updates', 'section_request', 'workload_request', 'section_busy', 'format_cpu_name', 'llr_display_points'])) {
    const sg = v => (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(2);
    const n = v => Math.round(v).toLocaleString('en-US');
    const pct = v => +v.toFixed(2) + '%';
    const busy = el => window.section_busy(el);
    const pentaRow = p => { const top = Math.max(...p) || 1, label = `(${p.join(', ')})`;
      return `<div class="penta-row"><div class="c-penta sm" role="img" aria-label="${label}" title="${label}">${p.map((v, i) => `<i class="p${i}" style="height:${Math.max(8, v / top * 100).toFixed(1)}%"></i>`).join('')}</div><span class="num dim">${label}</span></div>`; };
    const cs = getComputedStyle(root), C = k => cs.getPropertyValue(k).trim();

    window.render_llr_history = function (data) {
      const host = document.getElementById('llr-history-chart'); if (!host || busy(host)) return;
      const pts = window.llr_display_points((data.points || []).filter(p => Number.isFinite(p.games) && Number.isFinite(p.llr))).map(p => [p.games, p.llr]);
      if (!pts.length) return;
      const caption = document.getElementById('llr-history-caption'), readout = document.getElementById('llr-history-readout');
      caption.textContent = data.partial ? `Recorded from game ${data.startGames.toLocaleString()}` : 'Recorded results';
      const lo = data.lowerBound, hi = data.upperBound;
      const PASS = C('--pass'), FAIL = C('--fail'), INK = C('--ink'), PR = `rgb(${C('--pass-rgb')})`, FR = `rgb(${C('--fail-rgb')})`;
      const fmtG = g => g >= 1e6 ? (g / 1e6).toFixed(1).replace(/\.0$/, '') + 'M' : g >= 1000 ? (g / 1000).toFixed(g % 1000 ? 1 : 0).replace(/\.0$/, '') + 'k' : String(g);
      const W = host.clientWidth, H = host.clientHeight, narrow = W < 500, m = { l: narrow ? 44 : 50, r: narrow ? 38 : 50, t: 12, b: 26 };
      const gx = Math.max(1, pts[pts.length - 1][0]), vals = pts.map(p => p[1]), vMin = Math.min(lo, ...vals), vMax = Math.max(hi, ...vals);
      const pad = (vMax - vMin) * .06, y0 = vMin - pad, y1 = vMax + pad;
      const X = g => m.l + g / gx * (W - m.l - m.r), Y = v => m.t + (y1 - v) / (y1 - y0) * (H - m.t - m.b), z = Y(0);
      const line = pts.map(([g, v], i) => (i ? 'L' : 'M') + X(g).toFixed(1) + ' ' + Y(v).toFixed(1)).join('');
      const area = pts.length > 1 ? `M${X(pts[0][0])} ${z}` + pts.map(([g, v]) => `L${X(g).toFixed(1)} ${Y(v).toFixed(1)}`).join('') + `L${X(gx)} ${z}Z` : '';
      const ticks = [], most = narrow ? 3 : 6, count = s => Math.ceil(gx * .97 / s) - 1;
      let step = 1000; for (let k = 0; count(step) > most; k++) step = [1, 2, 5][(k + 1) % 3] * 1000 * 10 ** Math.floor((k + 1) / 3);
      for (let g = step; g < gx * .97; g += step) ticks.push(g);
      const grid = [], gridStep = y1 - y0 > 14 ? 2 : 1;
      for (let v = Math.ceil(y0 / gridStep) * gridStep; v <= y1; v += gridStep) if (v && Math.abs(v - hi) > .4 && Math.abs(v - lo) > .4) grid.push(v);
      const lastP = pts[pts.length - 1], endC = lastP[1] > 0 ? PASS : lastP[1] < 0 ? FAIL : INK;
      const zo = ((z - Y(hi)) / (Y(lo) - Y(hi))).toFixed(3);
      host.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" role="img" tabindex="0" aria-describedby="llr-history-readout" aria-label="LLR history, ${pts[0][0].toLocaleString()} to ${lastP[0].toLocaleString()} games. Current LLR ${lastP[1].toFixed(2)}. Lower bound ${lo.toFixed(2)}, upper bound ${hi.toFixed(2)}. Use arrow keys to inspect recorded points.">
        <defs>
          <linearGradient id="ch-area" gradientUnits="userSpaceOnUse" x1="0" y1="${Y(hi)}" x2="0" y2="${Y(lo)}"><stop offset="0" stop-color="${PR}" stop-opacity=".28"/><stop offset="${zo}" stop-color="${PR}" stop-opacity="0"/><stop offset="${zo}" stop-color="${FR}" stop-opacity="0"/><stop offset="1" stop-color="${FR}" stop-opacity=".3"/></linearGradient>
          <linearGradient id="ch-line" gradientUnits="userSpaceOnUse" x1="0" y1="${Y(hi)}" x2="0" y2="${Y(lo)}"><stop offset="0" stop-color="${PASS}"/><stop offset="${zo}" stop-color="#ececf0"/><stop offset="1" stop-color="${FAIL}"/></linearGradient>
        </defs>
        <rect x="${m.l}" y="${m.t}" width="${W - m.l - m.r}" height="${Math.max(0, Y(hi) - m.t)}" fill="${PR}" fill-opacity=".06"/>
        <rect x="${m.l}" y="${Y(lo)}" width="${W - m.l - m.r}" height="${Math.max(0, H - m.b - Y(lo))}" fill="${FR}" fill-opacity=".07"/>
        ${grid.map(v => `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(v)}" y2="${Y(v)}" stroke="rgb(255 255 255 / .06)"/><text x="${m.l - 9}" y="${Y(v) + 4}" text-anchor="end">${sg(v).replace('.00', '')}</text>`).join('')}
        ${ticks.map(g => `<line x1="${X(g)}" x2="${X(g)}" y1="${m.t}" y2="${H - m.b}" stroke="rgb(255 255 255 / .05)"/><text x="${X(g)}" y="${H - 7}" text-anchor="middle">${fmtG(g)}</text>`).join('')}
        <line x1="${m.l}" x2="${W - m.r}" y1="${z}" y2="${z}" stroke="rgb(255 255 255 / .3)"/>
        <line x1="${m.l}" x2="${W - m.r}" y1="${Y(hi)}" y2="${Y(hi)}" stroke="${PASS}" stroke-opacity=".75" stroke-dasharray="4 4"/>
        <line x1="${m.l}" x2="${W - m.r}" y1="${Y(lo)}" y2="${Y(lo)}" stroke="${FAIL}" stroke-opacity=".75" stroke-dasharray="4 4"/>
        <text x="${m.l - 9}" y="${Y(hi) + 4}" text-anchor="end" fill="${PASS}">${sg(hi)}</text>
        <text x="${m.l - 9}" y="${z + 4}" text-anchor="end">0</text>
        <text x="${m.l - 9}" y="${Y(lo) + 4}" text-anchor="end" fill="${FAIL}">${sg(lo)}</text>
        <text x="${W - m.r + 8}" y="${Y(hi) + 4}" fill="${PASS}">pass</text>
        <text x="${W - m.r + 8}" y="${Y(lo) + 4}" fill="${FAIL}">fail</text>
        ${area ? `<path d="${area}" fill="url(#ch-area)"/>` : ''}
        <path d="${line}" fill="none" stroke="url(#ch-line)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
        <circle cx="${X(lastP[0])}" cy="${Y(lastP[1])}" r="8" fill="${endC}" fill-opacity=".2"/>
        <circle cx="${X(lastP[0])}" cy="${Y(lastP[1])}" r="4" fill="${endC}" stroke="#232326" stroke-width="1.5"/>
        <g class="hover" opacity="0"><line y1="${m.t}" y2="${H - m.b}" stroke="rgb(255 255 255 / .4)"/><circle r="4" fill="#fff"/></g>
      </svg>`;
      const svg = host.firstElementChild, hov = svg.querySelector('.hover'), [hovLine, hovDot] = hov.children;
      let sel = pts.length - 1;
      const describe = (i, show = true, announce = false) => {
        readout.setAttribute('aria-live', announce ? 'polite' : 'off');
        sel = Math.max(0, Math.min(pts.length - 1, i)); const [g, v] = pts[sel];
        hov.setAttribute('opacity', show ? '1' : '0');
        hovLine.setAttribute('x1', X(g)); hovLine.setAttribute('x2', X(g)); hovDot.setAttribute('cx', X(g)); hovDot.setAttribute('cy', Y(v));
        readout.textContent = `${g.toLocaleString()} games · LLR ${v.toFixed(3)}` +
          (pts.length === 1 ? (data.finished ? ' · Earlier history was not recorded.' : ' · Waiting for the next recorded result.') : ' · Hover or use ← → to inspect.');
      };
      svg.addEventListener('pointermove', e => { const r = svg.getBoundingClientRect(), g = ((e.clientX - r.left) * W / r.width - m.l) / (W - m.l - m.r) * gx;
        let best = 0; pts.forEach((p, i) => { if (Math.abs(p[0] - g) < Math.abs(pts[best][0] - g)) best = i; }); describe(best); });
      svg.addEventListener('pointerleave', () => { if (document.activeElement !== svg) describe(pts.length - 1, false); });
      svg.addEventListener('focus', () => describe(sel, true, true));
      svg.addEventListener('blur', () => describe(pts.length - 1, false));
      svg.addEventListener('keydown', e => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return; e.preventDefault();
        describe(e.key === 'Home' ? 0 : e.key === 'End' ? pts.length - 1 : sel + (e.key === 'ArrowLeft' ? -1 : 1), true, true);
      });
      describe(pts.length - 1, false);
    };

    const ELO_SPAN = 12, eloAt = v => Math.max(0, Math.min(100, (v + ELO_SPAN) / (2 * ELO_SPAN) * 100));
    const knps = v => (v / 1000).toFixed(1);
    window.fetch_summary = function (workload_id) {
      return window.section_request('summary-container', async () => {
        const data = await window.workload_request(`/api/workload/${workload_id}/summary/`);
        const box = document.getElementById('summary-container'); if (busy(box)) return;
        const on = $('[data-sum][aria-selected="true"]')?.dataset.sum || 'user';
        const panel = (rows, label, key, fmt = s => s) => { const nps = rows.some(r => r.dev_nps > 0); return `<div class="sum-panel" id="sum-${key}" role="tabpanel"${key === on ? '' : ' hidden'}>
          <table class="dtable">
            <thead><tr><th scope="col">${label}</th><th scope="col" class="w-share">%</th><th scope="col" class="r">Pairs</th><th scope="col">Elo</th><th scope="col">Penta</th>${nps ? '<th scope="col" class="r">KNPS</th><th scope="col" class="r">Scaled KNPS</th>' : ''}</tr></thead>
            <tbody>${rows.map(r => {
              const [e, c] = String(r.elo).split('±').map(parseFloat), p = String(r.penta).replace(/[()]/g, '').split(',').map(Number);
              return `
              <tr><th scope="row">${escH(fmt(r.key))}</th>
                <td><div class="share"><i style="width:${+r.percent}%"></i></div><span class="num share-n">${escH(r.percent)}%</span></td>
                <td class="r num">${n(r.pairs)}</td>
                <td><div class="elo-inline"><span class="num">${sg(e)} <span class="dim">± ${c.toFixed(2)}</span></span><div class="ci"><i class="zero"></i><i class="bar" style="--lo:${pct(eloAt(e - c))};--hi:${pct(eloAt(e + c))}"></i><i class="dot" style="left:${pct(eloAt(e))}"></i></div></div></td>
                <td>${pentaRow(p)}</td>${nps ? `
                <td class="r num">${knps(r.dev_nps)} / ${knps(r.base_nps)}</td><td class="r num">${knps(r.dev_nps_scaled)} / ${knps(r.base_nps_scaled)}</td>` : ''}</tr>`;
            }).join('')}
            </tbody>
          </table>
        </div>`; };
        box.innerHTML = panel(data.summary.user || [], 'User', 'user') + panel(data.summary.cpu_name || [], 'CPU', 'cpu', window.format_cpu_name) + panel(data.summary.isa_name || [], 'ISA', 'isa');
      });
    };

    window.populate_results = function (res) {
      const body = document.getElementById('results-container'); if (!body || busy(body)) return;
      body.innerHTML = [...res].sort((a, b) => b.games - a.games).map(m => { const p = [m.LL, m.LD, m.DD, m.DW, m.WW];
        return `
            <tr${m.active ? ' class="active-highlight"' : ''}><th scope="row"><a href="/machines/${+m.machine__id}/" class="mach-id"><span class="num">${+m.machine__id}</span></a></th><td>${escH(m.machine__user__username)}</td><td class="r num">${n(m.games)}</td>
              <td class="hide-sm">${pentaRow(p)}</td>
              <td class="r num hide-sm">${n(p.reduce((a, b) => a + b, 0))}</td><td class="r num${m.timeloss ? ' warn' : ' dim'}">${m.timeloss}</td><td class="r num dim">${m.crashes}</td></tr>`; }).join('');
    };
  }

  const presetHost = $('#test-mode-buttons'), form = $('form.sheet-form');
  if (presetHost && form && window.engines && hasRepo(['apply_preset', 'create_preset_buttons', 'change_engine', 'set_test_type'])) {
    const RE = /^(\S+)(?: ([^\[].*?))?(?: \[((?:SMP )?(\d+)T)\])?$/;
    const goalName = g => g || 'Standard';
    const PRESETS = { TUNE: 'tune_presets', DATAGEN: 'datagen_presets' };
    const presetsOf = (eng, type) => window.engines[eng][PRESETS[type] || 'test_presets'] || {};
    const segHTML = (name, label, items, on) => `<div class="frow"><span class="flabel" id="pl-${name}">${label}</span><div class="fctl"><div class="seg seg-content seg-fill" role="radiogroup" aria-labelledby="pl-${name}">${items.map(([v, l]) => `<label><input type="radio" form="sheet-ui" name="${name}" value="${escH(v)}"${v === on ? ' checked' : ''}><span>${escH(l)}</span></label>`).join('')}</div></div></div>`;
    let ownCall = false, markApplied = null;
    const repoApply = window.apply_preset;
    window.apply_preset = function (key) { const r = repoApply.apply(this, arguments); if (!ownCall && markApplied) markApplied(key); return r; };
    const applyOwn = (key, type) => { ownCall = true; try { window.apply_preset(key, type); } finally { ownCall = false; } };
    const drawPresets = (keys, type) => {
      if (!keys.length) { presetHost.innerHTML = ''; return; }
      const parsed = keys.map(k => { const mm = k.match(RE); return mm && { key: k, tc: mm[1], goal: mm[2] || '', thr: +(mm[4] || 1), sfx: mm[3] || '' }; });
      const uniq = f => [...new Set(parsed.map(f))];
      const grid = parsed.every(Boolean) && (() => { const t = uniq(p => p.tc), g = uniq(p => p.goal), nn = uniq(p => p.thr);
        return t.length * g.length * nn.length === keys.length && t.length > 1 ? { t, g, n: nn.sort((a, b) => a - b) } : null; })();
      if (!grid) {
        presetHost.innerHTML = `<div class="chips" role="group" aria-labelledby="s-preset">${keys.map(k => `<button type="button" class="chip-btn" aria-pressed="false" data-key="${escH(k)}">${escH(k)}</button>`).join('')}</div>`;
        const chips = $$('[data-key]', presetHost), press = k => chips.forEach(x => x.setAttribute('aria-pressed', String(x.dataset.key === k)));
        chips.forEach(b => b.onclick = () => { press(b.dataset.key); applyOwn(b.dataset.key, type); after(); });
        markApplied = k => { if (keys.includes(k)) press(k); };
        return;
      }
      const find = (tc, goal, thr) => parsed.find(p => p.tc === tc && p.goal === goal && p.thr === thr)?.key;
      const thrName = k => k === 1 ? '1 thread' : parsed.find(p => p.thr === k)?.sfx || `${k}T`;
      const draw = (tc, goal, thr) => {
        presetHost.innerHTML =
          segHTML('p_tc', 'Time control', grid.t.map(x => [x, x]), tc) +
          (grid.g.length > 1 ? segHTML('p_goal', 'Goal', grid.g.map(g => [g, goalName(g)]), goal) : '') +
          (grid.n.length > 1 ? segHTML('p_smp', 'Threads', grid.n.map(k => [String(k), thrName(k)]), thr === null ? null : String(thr)) : '');
        $$('.seg', presetHost).forEach(x => segSync(x, true));
      };
      draw(null, null, null);
      markApplied = k => { const q = parsed.find(x => x.key === k); if (q) { draw(q.tc, q.goal, q.thr); after(); } };
      presetHost.onchange = () => {
        const v = k => presetHost.querySelector(`[name="${k}"]:checked`)?.value;
        const tc = v('p_tc') ?? grid.t[0], goal = v('p_goal') ?? grid.g[0], thr = +(v('p_smp') ?? grid.n[0]);
        const focused = document.activeElement?.name;
        draw(tc, goal, thr);
        if (focused) presetHost.querySelector(`[name="${focused}"]:checked`)?.focus({ preventScroll: true });
        const key = find(tc, goal, thr); if (key) { applyOwn(key, type); after(); }
      };
    };
    window.create_preset_buttons = function (eng, type) {
      markApplied = null; presetHost.onchange = null;
      drawPresets(Object.keys(presetsOf(eng, type)).filter(k => k !== 'default'), type);
      setTimeout(after);
    };

    const presetSec = presetHost.closest('.fsec');
    function syncProxies(fromUI) {
      for (const id of ['test_mode', 'upload_pgns']) {
        const s = document.getElementById(id), radios = $$(`[name="${id}_ui"]`); if (!s || !radios.length) continue;
        if (fromUI) { const r = radios.find(x => x.checked); if (r && s.value !== r.value) { s.value = r.value; s.dispatchEvent(new Event('change')); } }
        else radios.forEach(r => { r.checked = r.value === s.value; });
        segSync(radios[0].closest('.seg'));
      }
      const tm = $('#test_mode'); if (tm) form.dataset.mode = tm.value;
    }
    const after = () => { syncProxies(); if (presetSec) presetSec.hidden = !presetHost.children.length && !presetSec.querySelector('.presets > .frow'); };
    $$('[name="test_mode_ui"], [name="upload_pgns_ui"]').forEach(r => r.addEventListener('change', () => syncProxies(true)));
    form.addEventListener('change', e => { if (e.target.id === 'test_mode') syncProxies(); });
    form.addEventListener('toggle', e => { if (e.target.matches('details') && e.target.open) $$('.seg', e.target).forEach(x => segSync(x, true)); }, true);

    const sheetEl = form.closest('.sheet');
    sheetEl.addEventListener('scroll', e => { if (e.target.matches?.('.sheet-body')) sheetEl.toggleAttribute('data-scrolled', e.target.scrollTop > 2); }, true);

    const snap = () => [...new FormData(form)].filter(([k]) => k !== 'csrfmiddlewaretoken').map(([k, v]) => k + '=' + v).join('&');
    let base = null;
    document.addEventListener('DOMContentLoaded', () => setTimeout(() => { base = snap(); }));
    document.addEventListener('keydown', e => {
      if (e.key !== 'Escape' || e.defaultPrevented || base === null || document.querySelector(':popover-open') || snap() !== base) return;
      const cancel = $('.sheet-foot .btn[href]'); if (cancel) location.href = cancel.href;
    });
  }
})();
