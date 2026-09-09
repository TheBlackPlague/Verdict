function copy_text(text) {

    var area = document.createElement("textarea");
    area.value = text;
    document.body.append(area);
    area.select();

    try {
        document.execCommand("copy");
        document.body.removeChild(area);
    }

    catch (err) {
        document.body.removeChild(area);
        console.error("Unable to copy to Clipboard");
    }
}

function copy_text_from_element(element_id, keep_url) {
    let text = document.getElementById(element_id).innerText;
    if (keep_url) text += "\n" + window.location.href;
    copy_text(text);
}

const workloadRequests = new Map();
const requestedSections = new Set();
const sectionControllers = new Set();

function section_busy(container) {
    const selection = document.getSelection();
    return container.contains(document.activeElement) || (selection && !selection.isCollapsed &&
        (container.contains(selection.anchorNode) || container.contains(selection.focusNode)));
}

function abort_sections() { sectionControllers.forEach(controller => controller.abort()); }
document.addEventListener('verdict:pause', event => { if (event.detail.paused) abort_sections(); });
document.addEventListener('visibilitychange', () => { if (document.hidden) abort_sections(); });
window.addEventListener('pagehide', abort_sections);
window.addEventListener('offline', abort_sections);

async function workload_request(url, asText = false) {
    const controller = new AbortController();
    sectionControllers.add(controller);
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
    const response = await fetch(url, {credentials: 'same-origin', cache: 'no-store', signal: controller.signal});
    if (!response.ok || response.redirected) throw new Error('Unable to load results');
    if (asText) {
        const text = await response.text();
        if (response.headers.get('content-type')?.includes('application/json')) {
            const error = JSON.parse(text).error;
            if (error) throw new Error(error);
        }
        return text;
    }
    const data = await response.json();
    if (data.error) throw new Error(data.error);
    return data;
    } finally {
        clearTimeout(timeout);
        sectionControllers.delete(controller);
    }
}

function section_request(id, task) {
    if (workloadRequests.has(id)) return workloadRequests.get(id);
    const region = document.getElementById(id);
    if (!region) return Promise.resolve();
    const request = task().then(() => {
        document.getElementById(id + '-error')?.remove();
        region.removeAttribute('aria-busy');
    }).catch(error => {
        if (error.name === 'AbortError' && window.VerdictLive?.isPaused()) return;
        let message = document.getElementById(id + '-error');
        if (!message) {
            message = document.createElement('p');
            message.id = id + '-error';
            message.className = 'warning-message';
            message.setAttribute('role', 'status');
            // Table bodies cannot contain paragraphs.
            const table = region.closest('table');
            (table ? table.parentElement : region).before(message);
        }
        message.textContent = 'Could not update this section. Displayed results may be out of date. Use Refresh statistics to retry.';
        region.removeAttribute('aria-busy');
    }).finally(() => {
        workloadRequests.delete(id);
        region.removeAttribute('aria-busy');
    });
    region.setAttribute('aria-busy', 'true');
    workloadRequests.set(id, request);
    return request;
}

function start_workload_updates(workload_id) {
    fetch_summary(workload_id);
    fetch_llr_history(workload_id);
    let lastRefresh = Date.now();
    document.addEventListener('verdict:updated', event => {
        if (!event.detail.manual && (window.VerdictLive?.isPaused() || Date.now() - lastRefresh < 30000)) return;
        lastRefresh = Date.now();
        fetch_summary(workload_id);
        fetch_llr_history(workload_id);
        if (requestedSections.has('results')) fetch_results(workload_id);
        if (requestedSections.has('digest')) fetch_spsa_digest(workload_id);
    });
}


function populate_results(results) {

    const container = document.getElementById('results-container');

    if (section_busy(container)) return;
    container.replaceChildren();

    results.forEach(result => {
        const tr = document.createElement('tr');

        // Highlight active rows
        if (result.active) tr.classList.add('active-highlight');

        // Collapse the trinomial won/lost/drawn into the pentanomial tuple and
        // its pair count, mirroring the aggregate summary tables above
        const penta = [result.LL, result.LD, result.DD, result.DW, result.WW];
        const pairs = penta.reduce((a, b) => a + b, 0);

        const machine = summary_cell('td', '');
        const link = document.createElement('a');
        link.href = `/machines/${result.machine__id}/`;
        link.textContent = result.machine__id;
        machine.appendChild(link);
        tr.appendChild(machine);
        tr.appendChild(summary_cell('td', result.machine__user__username));
        tr.appendChild(summary_cell('td', result.games.toLocaleString(), 'numeric'));
        tr.appendChild(summary_cell('td', `(${penta.join(', ')})`));
        tr.appendChild(summary_cell('td', pairs.toLocaleString(), 'numeric'));
        tr.appendChild(summary_cell('td', result.timeloss, 'numeric'));
        tr.appendChild(summary_cell('td', result.crashes, 'numeric'));

        container.appendChild(tr);
    });
}

function fetch_results(workload_id) {
    requestedSections.add('results');
    return section_request('results-container', async () => {
        const data = await workload_request(`/api/workload/${workload_id}/results/`);
        populate_results(data.results);
    });
}


function summary_cell(tag, text, class_name) {

    // Keys are free-form (cpu names, isa names), so set everything as text to
    // avoid injecting any markup a Machine might have reported
    const cell = document.createElement(tag);
    cell.textContent = text;
    if (class_name) cell.className = class_name;
    return cell;
}

function format_cpu_name(name) {

    // CPU names as reported by py-cpuinfo can be verbose and noisy.
    // Clean them up here so the table stays readable.

    // Drop the (R) registered-trademark marker.
    name = name.replace(/\(R\)/g, '');

    // "Intel Xeon" is redundant — Xeon already implies Intel, so drop Intel.
    if (/Intel/.test(name) && /Xeon/.test(name))
        name = name.replace(/Intel/g, '');

    // Likewise, "AMD EPYC" and "AMD Ryzen" are redundant — both imply AMD.
    if (/AMD/.test(name) && /EPYC|Ryzen/.test(name))
        name = name.replace(/AMD/g, '');

    // "Processor" and "CPU" add nothing in this context.
    name = name.replace(/Processor/g, '');
    name = name.replace(/CPU/g, '');

    // Core counts, ie "16-Core", are reported separately in the table.
    name = name.replace(/\d+-Core/gi, '');

    // The removals above can leave stray spacing; collapse runs of whitespace
    // to a single space and trim the ends.
    name = name.replace(/\s+/g, ' ').trim();

    return name;
}

function append_summary_section(table, label, rows, key_formatter) {

    // Older workloads don't have NPS tracking stats.
    const is_nps_available =  rows.some(row => row.dev_nps > 0);

    // A header row naming the grouping, then one tbody of data rows. All three
    // sections share the one table, so their columns line up automatically.
    const header = document.createElement('tr');
    header.className = 'table-header';
    header.appendChild(summary_cell('th', label));

    ['Penta', 'Elo', 'Pairs', '%'].forEach(name => {
        header.appendChild(summary_cell('th', name, name === 'Penta' ? '' : 'numeric'));
    });

    if (is_nps_available) {
        header.appendChild(summary_cell('th', 'KNPS'));
        header.appendChild(summary_cell('th', 'Scaled KNPS'));
    }

    table.appendChild(header);

    const tbody = document.createElement('tbody');

    rows.forEach(row => {
        const tr = document.createElement('tr');

        // The API hands us display-ready fields: the penta tuple as a string,
        // a point-estimate Elo, the pair count, and the % of the group total
        tr.appendChild(summary_cell('td', key_formatter ? key_formatter(row.key) : row.key));
        tr.appendChild(summary_cell('td', row.penta));
        tr.appendChild(summary_cell('td', row.elo,   'numeric'));
        tr.appendChild(summary_cell('td', row.pairs, 'numeric'));
        tr.appendChild(summary_cell('td', row.percent, 'numeric'));

        if (is_nps_available) {
            const format_nps = (nps) => (nps / 1000.0).toFixed(1);

            tr.appendChild(summary_cell('td', `${format_nps(row.dev_nps)} / ${format_nps(row.base_nps)}`));
            tr.appendChild(summary_cell('td', `${format_nps(row.dev_nps_scaled)} / ${format_nps(row.base_nps_scaled)}`));
        }

        tbody.appendChild(tr);
    });

    table.appendChild(tbody);
}

function fetch_summary(workload_id) {
    return section_request('summary-container', async () => {
        const data = await workload_request(`/api/workload/${workload_id}/summary/`);
        const container = document.getElementById('summary-container');
        const table = document.createElement('table');
        table.className = 'stripes wrappable summary-table';
        append_summary_section(table, 'User', data.summary.user);
        append_summary_section(table, 'CPU', data.summary.cpu_name, format_cpu_name);
        append_summary_section(table, 'ISA', data.summary.isa_name);
        const scroll = container.scrollLeft;
        // Avoid replacing a table while someone selects numbers to copy.
        if (section_busy(container)) return;
        container.replaceChildren(table);
        container.scrollLeft = scroll;
    });
}


async function copy_spsa_value(workload_id, kind) {
    try {
        copy_text(await workload_request(`/api/spsa/${workload_id}/${kind}/`, true));
    } catch (error) {
        alert('Unable to copy SPSA values. Please try again.');
    }
}

function copy_spsa_inputs(workload_id) { return copy_spsa_value(workload_id, 'inputs'); }
function copy_spsa_outputs(workload_id) { return copy_spsa_value(workload_id, 'outputs'); }

function fetch_spsa_digest(workload_id) {
    requestedSections.add('digest');
    return section_request('spsa-digest-body-container', async () => {
        const text = await workload_request(`/api/spsa/${workload_id}/digest/`, true);
        const lines = text.trim().split('\n');
        const tbody = document.getElementById('spsa-digest-body-container');
        const fragment = document.createDocumentFragment();
        for (const line of lines.slice(1)) {
            const tr = document.createElement('tr');
            line.split(',').forEach(value => tr.appendChild(summary_cell('td', value)));
            fragment.appendChild(tr);
        }
        if (section_busy(tbody)) return;
        tbody.replaceChildren(fragment);
        tbody.style.display = '';
        document.getElementById('spsa-digest-button-container').style.display = 'none';
    });
}

function llr_history_path(points, x, y) {
    if (!points.length) return '';
    const slopes = points.slice(1).map((point, index) => {
        const previous = points[index];
        return point.games > previous.games ? (point.llr - previous.llr) / (point.games - previous.games) : 0;
    });
    const tangents = points.map((point, index) => {
        if (index === 0) return slopes[0] || 0;
        if (index === points.length - 1) return slopes[index - 1];
        const before = slopes[index - 1], after = slopes[index];
        if (before * after <= 0) return 0;
        const previousWidth = point.games - points[index - 1].games;
        const nextWidth = points[index + 1].games - point.games;
        const mean = (before * nextWidth + after * previousWidth) / (previousWidth + nextWidth);
        return Math.sign(before) * Math.min(Math.abs(mean), 2 * Math.abs(before), 2 * Math.abs(after));
    });
    const path = [`M${x(points[0].games)},${y(points[0].llr)}`];
    for (let index = 1; index < points.length; index++) {
        const previous = points[index - 1], point = points[index];
        const step = (point.games - previous.games) / 3;
        if (step <= 0) {
            path.push(`L${x(point.games)},${y(point.llr)}`);
            continue;
        }
        path.push(`C${x(previous.games + step)},${y(previous.llr + step * tangents[index - 1])} ` +
            `${x(point.games - step)},${y(point.llr - step * tangents[index])} ` +
            `${x(point.games)},${y(point.llr)}`);
    }
    return path.join(' ');
}

// Axes and presentation adapted from Silverrzz’s Mattbench LLR graph (GPL-3.0).
// https://github.com/nocturn9x/OpenBench · https://github.com/Silverrzz
function llr_display_points(points) {
    if (points.length < 3) return points;
    const first = points[0], last = points[points.length - 1];
    const interval = 32 * Math.max(1, Math.ceil((last.games - first.games) / (64 * 32)));
    const displayed = [first];
    for (const point of points.slice(1, -1)) {
        if (point.games - displayed[displayed.length - 1].games >= interval) displayed.push(point);
    }
    displayed.push(last);
    return displayed;
}

function render_llr_history(data) {
    const container = document.getElementById('llr-history-chart');
    if (!container || section_busy(container)) return;
    const points = llr_display_points(data.points.filter(point => Number.isFinite(point.games) && Number.isFinite(point.llr)));
    if (!points.length) return;
    const caption = document.getElementById('llr-history-caption');
    caption.textContent = data.partial ? `Recorded from game ${data.startGames.toLocaleString()}` : 'Recorded results';
    const readout = document.getElementById('llr-history-readout');
    const ns = 'http://www.w3.org/2000/svg';
    const width = Math.max(320, container.clientWidth - 10), height = 180;
    const left = 44, right = width - 16, top = 18, bottom = height - 29;
    const first = points[0], last = points[points.length - 1];
    const xStart = first.games, xEnd = Math.max(first.games + 1, last.games);
    const extreme = Math.max(1, Math.abs(data.lowerBound), Math.abs(data.upperBound), ...points.map(point => Math.abs(point.llr)));
    const limit = Math.ceil(extreme * 1.15 * 10) / 10;
    const yMin = -limit, yMax = limit;
    const x = games => left + (games - xStart) / (xEnd - xStart) * (right - left);
    const y = llr => bottom - (llr - yMin) / (yMax - yMin) * (bottom - top);
    function element(tag, attributes = {}, text = null) {
        const node = document.createElementNS(ns, tag);
        for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
        if (text !== null) node.textContent = text;
        return node;
    }
    const svg = element('svg', {viewBox: `0 0 ${width} ${height}`, class: 'llr-chart', role: 'img', tabindex: '0',
        'aria-label': `LLR history, ${first.games.toLocaleString()} to ${last.games.toLocaleString()} games. Current LLR ${last.llr.toFixed(2)}. Lower bound ${data.lowerBound.toFixed(2)}, upper bound ${data.upperBound.toFixed(2)}. Use arrow keys to inspect recorded points.`,
        'aria-describedby': 'llr-history-readout'});
    const defs = element('defs');
    const zeroOffset = data.upperBound / (data.upperBound - data.lowerBound);
    const strokeId = `${container.id}-stroke`;
    const gradient = element('linearGradient', {id:strokeId, gradientUnits:'userSpaceOnUse',
        x1:0, x2:0, y1:y(data.upperBound), y2:y(data.lowerBound)});
    for (const [offset, color] of [[0, 'success'], [zeroOffset, 'accent'], [1, 'danger']]) {
        gradient.append(element('stop', {offset, 'stop-color':`var(--${color})`}));
    }
    defs.append(gradient);
    svg.append(defs);
    const compact = new Intl.NumberFormat(undefined, {notation:'compact', maximumFractionDigits:1});
    for (const value of [-limit, 0, limit]) {
        svg.append(element('line', {x1:left, x2:right, y1:y(value), y2:y(value), class:value === 0 ? 'llr-zero' : 'llr-grid'}));
        svg.append(element('text', {x:left - 9, y:y(value), 'text-anchor':'end', 'dominant-baseline':'middle'},
            Math.abs(value) >= 100 ? compact.format(value) : value.toFixed(1)));
    }
    const ticks = Math.min(last.games - first.games, width < 480 ? 2 : 4);
    for (let index = 0; index <= ticks; index++) {
        const games = ticks ? Math.round(xStart + (last.games - xStart) * index / ticks) : xStart;
        svg.append(element('line', {x1:x(games), x2:x(games), y1:top, y2:bottom, class:'llr-grid'}));
        svg.append(element('text', {x:x(games), y:height - 8,
            'text-anchor':index === 0 ? 'start' : index === ticks ? 'end' : 'middle'},
            games >= 10000 ? compact.format(games) : games.toLocaleString()));
    }
    for (const [value, name] of [[data.lowerBound, 'lower'], [data.upperBound, 'upper']]) {
        svg.append(element('line', {x1:left, x2:right, y1:y(value), y2:y(value), class:`llr-bound llr-${name}`}));
    }
    const path = llr_history_path(points, x, y);
    svg.append(element('path', {d:`${path} L${x(last.games)},${y(0)} L${x(first.games)},${y(0)} Z`,
        fill:`url(#${strokeId})`, class:'llr-area', 'pointer-events':'none'}));
    svg.append(element('path', {d:path, class:'llr-line', style:`stroke:url(#${strokeId})`}));
    svg.append(element('circle', {cx:x(last.games), cy:y(last.llr), r:4, class:'llr-dot', style:`fill:url(#${strokeId})`}));
    const cursor = element('line', {x1:x(last.games), x2:x(last.games), y1:top, y2:bottom, class:'llr-cursor', visibility:'hidden'});
    const dot = element('circle', {cx:x(last.games), cy:y(last.llr), r:4, class:'llr-dot', visibility:'hidden', style:`fill:url(#${strokeId})`});
    svg.append(cursor, dot);
    let selected = points.length - 1;
    function describe(index, show = true, announce = false) {
        readout.setAttribute('aria-live', announce ? 'polite' : 'off');
        selected = index;
        const point = points[index];
        cursor.setAttribute('x1', x(point.games)); cursor.setAttribute('x2', x(point.games));
        dot.setAttribute('cx', x(point.games)); dot.setAttribute('cy', y(point.llr));
        cursor.setAttribute('visibility', show ? 'visible' : 'hidden'); dot.setAttribute('visibility', show ? 'visible' : 'hidden');
        readout.textContent = `${point.games.toLocaleString()} games · LLR ${point.llr.toFixed(3)}` +
            (points.length === 1 ? (data.finished ? ' · Earlier history was not recorded.' : ' · Waiting for the next recorded result.') : ' · Hover or use ← → to inspect.');
    }
    svg.addEventListener('pointermove', event => {
        const rect = svg.getBoundingClientRect();
        const games = xStart + ((event.clientX - rect.left) * width / rect.width - left) / (right - left) * (xEnd - xStart);
        let nearest = 0;
        for (let i = 1; i < points.length; i++) if (Math.abs(points[i].games - games) < Math.abs(points[nearest].games - games)) nearest = i;
        describe(nearest);
    });
    svg.addEventListener('pointerleave', () => { if (document.activeElement !== svg) describe(points.length - 1, false); });
    svg.addEventListener('focus', () => describe(selected, true, true));
    svg.addEventListener('blur', () => describe(points.length - 1, false));
    svg.addEventListener('keydown', event => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        describe(event.key === 'Home' ? 0 : event.key === 'End' ? points.length - 1 :
            Math.max(0, Math.min(points.length - 1, selected + (event.key === 'ArrowLeft' ? -1 : 1))), true, true);
    });
    container.replaceChildren(svg);
    describe(points.length - 1, false);
}

let llrHistoryData;
function fetch_llr_history(workload_id) {
    if (!document.getElementById('llr-history-chart')) return;
    return section_request('llr-history-chart', async () => {
        llrHistoryData = await workload_request(`/api/workload/${workload_id}/llr/`);
        render_llr_history(llrHistoryData);
    });
}
let llrResizeTimer;
window.addEventListener('resize', () => {
    clearTimeout(llrResizeTimer);
    llrResizeTimer = setTimeout(() => { if (llrHistoryData) render_llr_history(llrHistoryData); }, 150);
});
