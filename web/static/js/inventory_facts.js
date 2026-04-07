/**
 * Inventory Facts Modal & CMDB Integration
 * Refactored into separate module for maintainability.
 */

let currentFactsHost = null;

async function viewFacts(hostname) {
    currentFactsHost = hostname;
    const modal = document.getElementById('factsModal');
    const title = document.getElementById('factsModalTitle');
    const browser = document.getElementById('facts-browser');
    const tabs = document.getElementById('factsTabs');
    
    title.textContent = `Facts: ${hostname}`;
    browser.style.display = 'block';
    tabs.style.display = 'none';
    document.getElementById('current-tab').classList.remove('active');
    document.getElementById('history-tab').classList.remove('active');
    
    document.getElementById('host-overview').innerHTML = '<div class="empty-state">Loading host facts...</div>';
    document.getElementById('collectionList').innerHTML = '';
    
    modal.classList.add('active');

    try {
        const response = await fetch(`/api/inventory/${encodeURIComponent(hostname)}/facts`);
        if (!response.ok) throw new Error(await response.text());
        const data = await response.json();
        
        // Render overview
        document.getElementById('host-overview').innerHTML = `
            <div style="font-size: 0.9em; color: var(--text-muted);">
                First seen: ${data.first_seen || 'N/A'}<br>
                Last updated: ${data.last_updated || 'N/A'}
            </div>
        `;
        
        // Render collections
        if (data.collections && data.collections.length > 0) {
            document.getElementById('collectionList').innerHTML = data.collections.map(coll => `
                <div class="cmdb-collection-badge" onclick="viewCollection('${hostname}', '${coll}')">
                    <span class="cmdb-collection-name">${coll}</span>
                    <span class="cmdb-collection-date">View Data &rarr;</span>
                </div>
            `).join('');
        } else {
            document.getElementById('collectionList').innerHTML = `
                <div class="empty-state" style="padding: 20px; text-align: center; background: var(--bg-tertiary); border-radius: 8px; margin-top: 10px;">
                    <p style="margin-bottom: 15px;">No facts collected for this host yet.</p>
                    <div style="display: flex; flex-direction: column; gap: 10px; align-items: center;">
                        <a href="/run/hardware-inventory?target=${encodeURIComponent(hostname)}" 
                           class="btn btn-primary btn-small" style="width: 200px;">
                           🚀 Run Hardware Inventory
                        </a>
                        <a href="/run/software-inventory?target=${encodeURIComponent(hostname)}" 
                           class="btn btn-secondary btn-small" style="width: 200px;">
                           🔍 Run Software Inventory
                        </a>
                        <small style="color: var(--text-muted); margin-top: 5px;">
                            These playbooks will populate the CMDB with detailed system data.
                        </small>
                    </div>
                </div>`;
        }
    } catch (e) {
        document.getElementById('host-overview').innerHTML = `<div class="error">Error loading host data: ${e.message}</div>`;
    }
}

async function viewCollection(host, collection) {
    const browser = document.getElementById('facts-browser');
    const tabs = document.getElementById('factsTabs');
    const content = document.getElementById('factsContent');
    const historyViewer = document.getElementById('historyViewer');
    
    document.getElementById('factsModalTitle').textContent = `${host} / ${collection}`;
    browser.style.display = 'none';
    tabs.style.display = 'flex';
    showFactsTab('current');
    
    content.textContent = 'Loading collection data...';
    historyViewer.innerHTML = 'Loading history...';

    try {
        // Fetch both current data and history in parallel
        const [dataRes, histRes] = await Promise.all([
            fetch(`/api/inventory/${encodeURIComponent(host)}/facts/${encodeURIComponent(collection)}`),
            fetch(`/api/inventory/${encodeURIComponent(host)}/facts/${encodeURIComponent(collection)}/history`)
        ]);

        if (!dataRes.ok) throw new Error(`Data error: ${dataRes.statusText}`);
        if (!histRes.ok) throw new Error(`History error: ${histRes.statusText}`);

        const data = await dataRes.json();
        const history = await histRes.json();

        // Render current data
        content.textContent = JSON.stringify(data.current || data, null, 2);

        // Render history
        if (!history || history.length === 0) {
            historyViewer.innerHTML = '<div class="empty-state">No history available</div>';
        } else {
            historyViewer.innerHTML = history.map((entry, idx) => `
                <div class="cmdb-history-item">
                    <div class="cmdb-history-timestamp">${new Date(entry.timestamp).toLocaleString()}</div>
                    <div style="color: var(--text-muted); font-size: 0.85em; margin-bottom: 8px;">Source: ${entry.source || 'N/A'}</div>
                    ${entry.diff_from_next ? renderDiff(entry.diff_from_next) : '<div class="text-muted">No changes recorded</div>'}
                </div>
            `).join('');
        }
    } catch (e) {
        content.textContent = 'Error: ' + e.message;
        historyViewer.innerHTML = 'Error: ' + e.message;
    }
}

function renderDiff(diff) {
    let html = '<div class="cmdb-diff-section">';
    const added = Object.keys(diff.added || {});
    const removed = Object.keys(diff.removed || {});
    const changed = Object.keys(diff.changed || {});

    const formatVal = (v) => {
        if (v === null) return 'null';
        if (typeof v === 'object') return JSON.stringify(v);
        return String(v);
    };

    if (added.length) {
        html += `<div class="cmdb-diff-category added"><div class="cmdb-diff-category-title">Added</div>`;
        added.forEach(k => html += `<div class="cmdb-diff-item"><span class="cmdb-diff-key">${k}</span><span class="cmdb-diff-new">${formatVal(diff.added[k])}</span></div>`);
        html += `</div>`;
    }
    if (removed.length) {
        html += `<div class="cmdb-diff-category removed"><div class="cmdb-diff-category-title">Removed</div>`;
        removed.forEach(k => html += `<div class="cmdb-diff-item"><span class="cmdb-diff-key">${k}</span><span class="cmdb-diff-old">${formatVal(diff.removed[k])}</span></div>`);
        html += `</div>`;
    }
    if (changed.length) {
        html += `<div class="cmdb-diff-category changed"><div class="cmdb-diff-category-title">Changed</div>`;
        changed.forEach(k => {
            const c = diff.changed[k];
            html += `<div class="cmdb-diff-item"><span class="cmdb-diff-key">${k}</span><span class="cmdb-diff-old">${formatVal(c.old)}</span> &rarr; <span class="cmdb-diff-new">${formatVal(c.new)}</span></div>`;
        });
        html += `</div>`;
    }
    return html + '</div>';
}

function showFactsTab(tabName) {
    document.querySelectorAll('.cmdb-tab-content').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.cmdb-tab-btn').forEach(b => b.classList.remove('active'));
    document.getElementById(tabName + '-tab').classList.add('active');
    
    const btns = document.querySelectorAll('.cmdb-tab-btn');
    if (tabName === 'current') btns[0].classList.add('active');
    else btns[1].classList.add('active');
}

function backToBrowser() {
    document.getElementById('factsModalTitle').textContent = `Facts: ${currentFactsHost}`;
    document.getElementById('facts-browser').style.display = 'block';
    document.getElementById('factsTabs').style.display = 'none';
    document.getElementById('current-tab').classList.remove('active');
    document.getElementById('history-tab').classList.remove('active');
}

function closeFactsModal() {
    document.getElementById('factsModal').classList.remove('active');
}
