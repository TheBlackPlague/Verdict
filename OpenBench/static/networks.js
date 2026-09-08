const Networks = JSON.parse(document.getElementById('json-networks').textContent);
let networkRows;
let currentSort = '';
let ascending = false;

function sort_networks(fields) {
    const table = document.getElementById('network-table');
    if (!networkRows) networkRows = Networks.map((network, index) => ({network, row: table.rows[index + 1]}));
    const key = fields.join(',');
    ascending = currentSort === key ? !ascending : false;
    currentSort = key;
    networkRows.sort((a, b) => {
        for (const field of fields) {
            const left = a.network[field], right = b.network[field];
            if (left === right) continue;
            const comparison = left > right ? 1 : -1;
            return ascending ? comparison : -comparison;
        }
        return 0;
    });
    const body = table.tBodies[0];
    networkRows.forEach(({row}) => body.appendChild(row));
    table.querySelectorAll('[data-sort]').forEach(header => {
        header.setAttribute('aria-sort', header.dataset.sort === fields[0] ? (ascending ? 'ascending' : 'descending') : 'none');
    });
}
