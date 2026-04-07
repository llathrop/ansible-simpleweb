/**
 * Inventory Facts Modal & CMDB Integration
 * Refactored into separate module for maintainability.
 */

let currentFactsHost = null;
let currentCollection = null;
let historyLoaded = false;

function escapeHtml(unsafe) {
    if (unsafe === undefined || unsafe === null) return '';
    return unsafe.toString()
         .replace(/&/g, "&amp;")
         .replace(/</g, "&lt;")
         .replace(/>/g, "&gt;")
         .replace(/"/g, "&quot;")
         .replace(/'/g, "&#39;");
}

function setViewState(state) {
    const browser = document.getElementById('facts-browser');
    const tabs = document.getElementById('factsTabs');
    const contentTabs = document.querySelectorAll('.cmdb-tab-content');
    const tabBtns = document.querySelectorAll('.cmdb-tab-btn');

    // Reset visibility
    browser.style.display = 'none';
    tabs.style.display = 'none';
    contentTabs.forEach(t => t.classList.remove('active'));
    tabBtns.forEach(b => b.classList.remove('active'));

    if (state === 'browser') {
        browser.style.display = 'block';
        currentCollection = null;
    } else if (state === 'tabs') {
        tabs.style.display = 'flex';
    } else if (state === 'closed') {
        currentFactsHost = null;
        currentCollection = null;
    }
}

async function viewFacts(hostname) {
    currentFactsHost = hostname;
    const modal = document.getElementById('factsModal');
    const title = document.getElementById('factsModalTitle');
    
    title.textContent = `Facts: ${hostname}`;
    setViewState('browser');
    
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
                First seen: ${escapeHtml(data.first_seen) || 'N/A'}<br>
                Last updated: ${escapeHtml(data.last_updated) || 'N/A'}
            </div>
        `;
        
        // Render collections
        if (data.collections && data.collections.length > 0) {
            document.getElementById('collectionList').innerHTML = data.collections.map(coll => {
                const escapedHost = JSON.stringify(hostname).replace(/"/g, '&quot;');
                const escapedColl = JSON.stringify(coll).replace(/"/g, '&quot;');
                return `
                    <div class="cmdb-collection-badge" onclick="viewCollection(${escapedHost}, ${escapedColl})">
                        <span class="cmdb-collection-name">${escapeHtml(coll)}</span>
                        <span class="cmdb-collection-date">View Data &rarr;</span>
                    </div>
                `;
            }).join('');
        } else {
            document.getElementById('collectionList').innerHTML = `
                <div class="empty-state" style="padding: 20px; text-align: center; background: var(--bg-tertiary); border-radius: 8px; margin-top: 10px;">
                    <p style="margin-bottom: 15px;">No facts collected for this host yet. Run any playbook to populate the CMDB.</p>
                    <div style="display: flex; flex-direction: column; gap: 10px; align-items: center;">
                        <a href="/playbooks?target=${encodeURIComponent(hostname)}" 
                           class="btn btn-primary btn-small" style="width: 200px;">
                           🚀 Run Playbook
                        </a>
                    </div>
                </div>`;
        }
    } catch (e) {
        document.getElementById('host-overview').innerHTML = `<div class="error">Error loading host data: ${escapeHtml(e.message)}</div>`;
    }
}

async function viewCollection(host, collection) {
    currentCollection = collection;
    historyLoaded = false;
    
    const content = document.getElementById('factsContent');
    const historyViewer = document.getElementById('historyViewer');
    
    document.getElementById('factsModalTitle').textContent = `${host} / ${collection}`;
    setViewState('tabs');
    showFactsTab('current');
    
    content.textContent = 'Loading collection data...';
    historyViewer.innerHTML = '<div class="empty-state">Click "History" tab to load...</div>';

    try {
        // ONLY fetch current data by default (Efficiency/SD Card)
        const response = await fetch(`/api/inventory/${encodeURIComponent(host)}/facts/${encodeURIComponent(collection)}`);
        if (!response.ok) throw new Error(`Data error: ${response.statusText}`);
        const data = await response.json();

        // Render current data
        content.textContent = JSON.stringify(data.current || data, null, 2);
    } catch (e) {
        content.innerHTML = `<div class="error">Data error: ${escapeHtml(e.message)}</div>`;
    }
}

async function loadHistory() {
    if (historyLoaded) return;
    
    const historyViewer = document.getElementById('historyViewer');
    historyViewer.innerHTML = 'Loading history...';

    try {
        const response = await fetch(`/api/inventory/${encodeURIComponent(currentFactsHost)}/facts/${encodeURIComponent(currentCollection)}/history`);
        if (!response.ok) throw new Error(`History error: ${response.statusText}`);
        const history = await response.json();

        // Render history with XSS protection
        if (!history || history.length === 0) {
            historyViewer.innerHTML = '<div class="empty-state">No history available</div>';
        } else {
            historyViewer.innerHTML = history.map((entry, idx) => `
                <div class="cmdb-history-item">
                    <div class="cmdb-history-timestamp">${escapeHtml(new Date(entry.timestamp).toLocaleString())}</div>
                    <div style="color: var(--text-muted); font-size: 0.85em; margin-bottom: 8px;">Source: ${escapeHtml(entry.source || 'N/A')}</div>
                    ${entry.diff_from_next ? renderDiff(entry.diff_from_next) : '<div class="text-muted">No changes recorded</div>'}
                </div>
            `).join('');
        }
        historyLoaded = true;
    } catch (e) {
        historyViewer.innerHTML = `<div class="error">Error loading history: ${escapeHtml(e.message)}</div>`;
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
        added.forEach(k => html += `<div class="cmdb-diff-item"><span class="cmdb-diff-key">${escapeHtml(k)}</span><span class="cmdb-diff-new">${escapeHtml(formatVal(diff.added[k]))}</span></div>`);
        html += `</div>`;
    }
    if (removed.length) {
        html += `<div class="cmdb-diff-category removed"><div class="cmdb-diff-category-title">Removed</div>`;
        removed.forEach(k => html += `<div class="cmdb-diff-item"><span class="cmdb-diff-key">${escapeHtml(k)}</span><span class="cmdb-diff-old">${escapeHtml(formatVal(diff.removed[k]))}</span></div>`);
        html += `</div>`;
    }
    if (changed.length) {
        html += `<div class="cmdb-diff-category changed"><div class="cmdb-diff-category-title">Changed</div>`;
        changed.forEach(k => {
            const c = diff.changed[k];
            html += `<div class="cmdb-diff-item"><span class="cmdb-diff-key">${escapeHtml(k)}</span><span class="cmdb-diff-old">${escapeHtml(formatVal(c.old))}</span> &rarr; <span class="cmdb-diff-new">${escapeHtml(formatVal(c.new))}</span></div>`;
        });
        html += `</div>`;
    }
    return html + '</div>';
}

function showFactsTab(tabName) {
    document.querySelectorAll('.cmdb-tab-content').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.cmdb-tab-btn').forEach(b => b.classList.remove('active'));
    
    const contentTab = document.getElementById(tabName + '-tab');
    if (contentTab) contentTab.classList.add('active');
    
    const activeBtn = document.getElementById('tab-btn-' + tabName);
    if (activeBtn) activeBtn.classList.add('active');

    if (tabName === 'history') {
        loadHistory(); // Lazy-loading for history
    }
}

function backToBrowser() {
    document.getElementById('factsModalTitle').textContent = `Facts: ${currentFactsHost}`;
    setViewState('browser');
}

function closeFactsModal() {
    document.getElementById('factsModal').classList.remove('active');
    setViewState('closed');
}
