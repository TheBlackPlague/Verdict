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
    let lastRefresh = Date.now();
    document.addEventListener('verdict:updated', event => {
        if (!event.detail.manual && (window.VerdictLive?.isPaused() || Date.now() - lastRefresh < 30000)) return;
        lastRefresh = Date.now();
        fetch_summary(workload_id);
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
        header.appendChild(summary_cell('th', name));
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
