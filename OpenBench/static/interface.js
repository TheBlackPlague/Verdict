(() => {
    'use strict';

    function formatDates(root) {
        root.querySelectorAll('.timestamp, .datestamp').forEach(node => {
            if (node.dataset.formatted) return;
            const seconds = Number(node.textContent.trim());
            if (!Number.isFinite(seconds)) return;
            const date = new Date(seconds * 1000);
            if (Number.isNaN(date.getTime())) return;
            const options = node.classList.contains('datestamp')
                ? {month: 'short', day: '2-digit'}
                : {year: 'numeric', month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit'};
            node.textContent = date.toLocaleString(undefined, options);
            node.title = date.toLocaleString();
            node.dataset.formatted = 'true';
        });
    }

    function enhance(root) {
        formatDates(root);
        root.querySelectorAll('table').forEach(table => {
            if (!table.parentElement.classList.contains('table-scroll')) {
                const wrapper = document.createElement('div');
                wrapper.className = 'table-scroll';
                table.before(wrapper);
                wrapper.append(table);
            }
        });
        root.querySelectorAll('a[onclick]:not([href])').forEach(link => {
            link.setAttribute('role', 'button');
            link.tabIndex = 0;
        });
    }

    const state = {paused: false, unavailable: false};
    window.VerdictLive = {isPaused: () => state.paused || state.unavailable || document.hidden || !navigator.onLine};

    document.addEventListener('DOMContentLoaded', () => {
        enhance(document);
        const path = location.pathname.replace(/^\/+|\/+$/g, '') || 'index';
        document.querySelectorAll('[data-nav]').forEach(link => {
            const key = link.dataset.nav;
            if (path === key || (['index', 'greens', 'machines', 'networks', 'events', 'errors'].includes(key) && path.startsWith(key + '/'))) {
                link.setAttribute('aria-current', 'page');
            }
        });

        const sidebar = document.getElementById('sidebar');
        const toggle = document.getElementById('sidebar-toggle');
        const backdrop = document.getElementById('sidebar-backdrop');
        const mobile = matchMedia('(max-width: 800px)');
        function setSidebar(open) {
            document.body.classList.toggle('sidebar-open', open);
            toggle.setAttribute('aria-expanded', String(open));
            toggle.setAttribute('aria-label', open ? 'Close navigation' : 'Open navigation');
            backdrop.hidden = !open;
            sidebar.inert = mobile.matches && !open;
            document.getElementById('main-content').inert = mobile.matches && open;
            document.getElementById('content-header').inert = mobile.matches && open;
            if (open) sidebar.querySelector('a').focus();
        }
        setSidebar(false);
        toggle.addEventListener('click', () => setSidebar(!document.body.classList.contains('sidebar-open')));
        backdrop.addEventListener('click', () => { setSidebar(false); toggle.focus(); });
        document.getElementById('sidebar-close').addEventListener('click', () => { setSidebar(false); toggle.focus(); });
        mobile.addEventListener('change', () => setSidebar(false));
        document.addEventListener('keydown', event => {
            if (event.key === 'Escape' && document.body.classList.contains('sidebar-open')) {
                setSidebar(false); toggle.focus();
            }
            if (event.key === 'Tab' && document.body.classList.contains('sidebar-open')) {
                const links = [...sidebar.querySelectorAll('a[href],button:not([disabled])')].filter(node => node.getClientRects().length);
                const first = links[0], last = links[links.length - 1];
                if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
                else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
            }
            if ((event.key === 'Enter' || event.key === ' ') && event.target.matches('a[role="button"]')) {
                event.preventDefault(); event.target.click();
            }
        });

        const config = document.getElementById('live-regions');
        if (!config) return;
        const allowedRegions = new Set(JSON.parse(config.textContent));
        const status = document.getElementById('live-status');
        const pause = document.getElementById('live-toggle');
        const refresh = document.getElementById('live-refresh');
        let timer, controller, failures = 0, etag = null, lastUpdated = new Date();
        const previousHTML = new Map();

        function showStatus(text, mode = '') {
            status.textContent = text;
            status.dataset.state = mode;
            status.title = 'Last checked ' + lastUpdated.toLocaleTimeString();
        }
        function schedule() {
            clearTimeout(timer);
            if (!window.VerdictLive.isPaused()) timer = setTimeout(() => update(), Math.min(60000, 10000 * 2 ** failures));
        }
        function regionBusy(target) {
            const selection = document.getSelection();
            return target.contains(document.activeElement) || (selection && !selection.isCollapsed &&
                (target.contains(selection.anchorNode) || target.contains(selection.focusNode)));
        }
        async function update(manual = false) {
            clearTimeout(timer);
            if (controller || state.unavailable || document.hidden || (!manual && state.paused)) return;
            if (!navigator.onLine) { showStatus('Offline', 'error'); return; }
            controller = new AbortController();
            const timeout = setTimeout(() => controller?.abort(), 15000);
            refresh.disabled = true;
            try {
                const headers = {'X-Verdict-Live': '1', 'Accept': 'application/json'};
                if (etag) headers['If-None-Match'] = etag;
                const response = await fetch(location.pathname + location.search, {
                    credentials: 'same-origin', cache: 'no-store', headers, signal: controller.signal,
                });
                if (response.status === 401 || response.status === 403 || response.redirected) {
                    state.unavailable = true;
                    showStatus('Reload required', 'error');
                    status.title = 'Access changed. Reload this page to continue.';
                    return;
                }
                if (response.status !== 304) {
                    if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new Error('Unable to refresh');
                    const data = await response.json();
                    if (data.error || !data.regions) throw new Error(data.error || 'Invalid response');
                    let skipped = false;
                    for (const [id, html] of Object.entries(data.regions)) {
                        if (!allowedRegions.has(id) || typeof html !== 'string') continue;
                        const target = document.getElementById(id);
                        if (!target || previousHTML.get(id) === html) continue;
                        if (regionBusy(target)) { skipped = true; continue; }
                        const scroll = [...target.querySelectorAll('.table-scroll')].map(node => node.scrollLeft);
                        // These fragments come only from whitelisted, auto-escaped Django templates.
                        target.innerHTML = html;
                        enhance(target);
                        target.querySelectorAll('.table-scroll').forEach((node, i) => { node.scrollLeft = scroll[i] || 0; });
                        previousHTML.set(id, html);
                    }
                    // Refetch skipped regions when the user stops interacting with them.
                    etag = skipped ? null : response.headers.get('ETag');
                }
                failures = 0;
                lastUpdated = new Date();
                showStatus(state.paused ? 'Paused' : 'Live updates', state.paused ? 'paused' : '');
                document.dispatchEvent(new CustomEvent('verdict:updated', {detail: {manual}}));
            } catch (error) {
                if (!state.paused && !document.hidden) { failures++; showStatus(navigator.onLine ? 'Retrying…' : 'Offline', 'error'); }
            } finally {
                clearTimeout(timeout);
                controller = null;
                refresh.disabled = false;
                schedule();
            }
        }
        pause.addEventListener('click', () => {
            state.paused = !state.paused;
            pause.setAttribute('aria-pressed', String(state.paused));
            pause.setAttribute('aria-label', state.paused ? 'Resume live updates' : 'Pause live updates');
            pause.title = pause.getAttribute('aria-label');
            pause.firstElementChild.className = 'fa-solid ' + (state.paused ? 'fa-play' : 'fa-pause');
            clearTimeout(timer);
            document.dispatchEvent(new CustomEvent('verdict:pause', {detail: {paused: state.paused}}));
            if (state.paused) { controller?.abort(); showStatus('Paused', 'paused'); }
            else update();
        });
        refresh.addEventListener('click', () => update(true));
        document.addEventListener('visibilitychange', () => {
            clearTimeout(timer);
            if (document.hidden) controller?.abort();
            else if (!state.paused) update();
        });
        window.addEventListener('offline', () => { clearTimeout(timer); controller?.abort(); showStatus('Offline', 'error'); });
        window.addEventListener('online', () => { if (!state.paused) update(); else showStatus('Paused', 'paused'); });
        window.addEventListener('pagehide', () => { clearTimeout(timer); controller?.abort(); });
        window.addEventListener('pageshow', event => { if (event.persisted) schedule(); });
        schedule();
    });

    document.addEventListener('submit', event => {
        if (event.defaultPrevented) return;
        const form = event.target;
        if (form.dataset.submitting) { event.preventDefault(); return; }
        form.dataset.submitting = 'true';
    });
    window.addEventListener('pageshow', () => {
        document.querySelectorAll('form[data-submitting]').forEach(form => { delete form.dataset.submitting; });
    });
})();
