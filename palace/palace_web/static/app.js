/**
 * Palace Annotation System — Frontend v0.1
 */
const PalaceApp = (() => {
  const API = window.location.origin;
  const MARKS = {
    adopt:   { label: 'Adopt',   icon: '\ud83d\udd34' },
    discuss: { label: 'Discuss', icon: '\ud83d\udfe1' },
    known:   { label: 'Known',   icon: '\ud83d\udfe2' },
    na:      { label: 'N/A',     icon: '\u26aa' },
  };
  const VERDICT_TEXT = { pass: 'Pass', concern: 'Concern', block: 'Block', error: 'Error' };
  const SEV_LABELS = { P0: 'P0 Blocker', P1: 'P1 Must Fix', P2: 'P2 Suggestion', P3: 'P3 Nice-to-have', INFO: 'Info', WARN: 'Warning' };

  let _reportId = null;
  let _reportData = null;
  let _annotations = {};
  let _saveTimers = {};

  // ---- Helpers ----
  async function api(path, opts = {}) {
    const resp = await fetch(API + path, {
      headers: { 'Content-Type': 'application/json' },
      ...opts,
    });
    if (!resp.ok) throw new Error(`API ${resp.status}`);
    return resp.json();
  }

  function esc(s) {
    const d = document.createElement('div');
    d.textContent = s || '';
    return d.innerHTML;
  }

  function getAnnotator() {
    const role = document.getElementById('annotator-role')?.value || 'producer';
    const name = document.getElementById('annotator-name')?.value || '';
    return { role, name };
  }

  function persistAnnotator() {
    const { role, name } = getAnnotator();
    localStorage.setItem('palace_anno_role', role);
    localStorage.setItem('palace_anno_name', name);
  }

  function restoreAnnotator() {
    const r = localStorage.getItem('palace_anno_role');
    const n = localStorage.getItem('palace_anno_name');
    if (r) { const el = document.getElementById('annotator-role'); if (el) el.value = r; }
    if (n) { const el = document.getElementById('annotator-name'); if (el) el.value = n; }
  }

  // ---- Version tracker ----
  async function updateVersion() {
    try {
      const v = await api('/api/version');
      const el = document.getElementById('version-info');
      if (el) el.textContent = `v${v.app_version} \u00b7 ${v.last_update || ''}`;
      document.title = `Palace [v${v.app_version}]`;
    } catch { /* ignore */ }
  }

  // ============================================================
  // INDEX PAGE
  // ============================================================
  async function initIndex() {
    updateVersion();
    const container = document.getElementById('report-list');
    try {
      const reports = await api('/api/reports');
      if (!reports.length) {
        container.innerHTML = '<div class="empty-state"><h3>No reports yet</h3><p>Use CLI to publish a report: py palace/run.py --publish</p></div>';
        return;
      }
      container.innerHTML = reports.map(r => `
        <div class="report-card" onclick="location.href='/report/${esc(r.id)}'">
          <div class="title">${esc(r.title)}</div>
          <div class="meta">
            <span class="badge badge-${r.overall_verdict || 'error'}">${VERDICT_TEXT[r.overall_verdict] || '?'}</span>
            ${r.submitted ? '<span class="badge badge-submitted">Submitted</span>' : ''}
            <span>${r.annotation_count ? r.annotation_count + ' annotations' : ''}</span>
            <span>${r.created_at ? new Date(r.created_at).toLocaleString('zh-CN') : ''}</span>
          </div>
        </div>
      `).join('');
    } catch (e) {
      container.innerHTML = `<div class="empty-state"><h3>Failed to load reports</h3><p>${esc(e.message)}</p></div>`;
    }
  }

  // ============================================================
  // REPORT PAGE
  // ============================================================
  async function initReport() {
    updateVersion();
    restoreAnnotator();

    const roleEl = document.getElementById('annotator-role');
    const nameEl = document.getElementById('annotator-name');
    if (roleEl) roleEl.addEventListener('change', persistAnnotator);
    if (nameEl) nameEl.addEventListener('input', persistAnnotator);

    _reportId = window.location.pathname.split('/report/')[1];
    if (!_reportId) return;

    try {
      const resp = await api(`/api/reports/${_reportId}`);
      _reportData = resp.report;
      _annotations = resp.annotations || {};
      renderReport();
      renderAnnotationSidebar();
      updateStats();
      updateSubmitButton();
      bindSubmitFlow();
    } catch (e) {
      document.getElementById('report-content').innerHTML =
        `<div class="empty-state"><h3>Failed to load report</h3><p>${esc(e.message)}</p></div>`;
    }
  }

  // ---- Render report content (left panel) ----
  function renderReport() {
    const data = _reportData.data || {};
    const el = document.getElementById('report-content');
    const issues = data.issues || [];
    const layerOverview = data.layer_overview || [];
    const crossLayer = data.cross_layer || [];
    const ov = data.overall_verdict || 'error';

    let html = '';

    // Title + meta
    html += `<h1 class="rpt-title">${esc(_reportData.title || _reportData.feature_title || 'Report')}</h1>`;
    html += '<div class="rpt-meta">';
    if (_reportData.scenario_id) html += `<div class="meta-item"><span class="meta-label">Scenario:</span><span class="meta-value">${esc(_reportData.scenario_id)}</span></div>`;
    if (_reportData.pipeline_weight) html += `<div class="meta-item"><span class="meta-label">Track:</span><span class="meta-value">${_reportData.pipeline_weight === 'slow' ? 'Slow' : 'Fast'}</span></div>`;
    if (_reportData.document_layer) html += `<div class="meta-item"><span class="meta-label">Layer:</span><span class="meta-value">${esc(_reportData.document_layer)}</span></div>`;
    if (_reportData.created_at) html += `<div class="meta-item"><span class="meta-label">Created:</span><span class="meta-value">${new Date(_reportData.created_at).toLocaleString('zh-CN')}</span></div>`;
    html += '</div>';

    // Overall verdict
    const verdictLabels = { pass: 'Pass - Ready for next stage', concern: 'Concern - Risks need attention', block: 'Block - Must fix before proceeding', error: 'Error' };
    html += `<div class="rpt-verdict ${ov}">${verdictLabels[ov] || ov} (${data.blocker_count || 0} blockers, ${data.concern_count || 0} concerns)</div>`;

    // Layer overview table
    if (layerOverview.length) {
      html += '<h3 class="section-heading">Document Layer Overview</h3>';
      html += '<table class="layer-table"><thead><tr><th>Layer</th><th>Ratio</th><th>Completeness</th><th>Gaps</th></tr></thead><tbody>';
      layerOverview.forEach(lo => {
        html += `<tr><td>${esc(lo.layer)}</td><td>${esc(lo.ratio || '')}</td><td>${esc(lo.completeness || '')}</td><td>${esc(lo.key_gaps || '')}</td></tr>`;
      });
      html += '</tbody></table>';
    }

    // Issues
    if (issues.length) {
      html += `<h3 class="section-heading">Issues (${issues.length})</h3>`;
      issues.forEach(issue => {
        const sev = issue.severity || 'P2';
        html += `<div class="issue-card" id="issue-${esc(issue.item_id)}" data-item-id="${esc(issue.item_id)}">`;
        html += '<div class="issue-header">';
        html += `<span class="anno-card-sev sev-${sev}">${sev}</span>`;
        html += `<span class="issue-title">${esc(issue.title)}</span>`;
        html += `<span class="issue-layer">${esc(issue.layer || '')}</span>`;
        html += '</div>';
        if (issue.gap_description) html += `<div class="issue-gap">${esc(issue.gap_description)}</div>`;
        if (issue.role_comments && issue.role_comments.length) {
          html += '<div class="issue-comments">';
          issue.role_comments.forEach(rc => {
            html += `<div class="issue-comment"><span class="comment-perspective">${esc(rc.perspective || '')}</span><span class="comment-text">${esc(rc.comment || '')}</span></div>`;
          });
          html += '</div>';
        }
        if (issue.action) {
          const a = issue.action;
          html += `<div class="issue-action"><strong>Target:</strong> ${esc(a.target_state || '')} | <strong>Status:</strong> ${esc(a.current_status || '')} | <strong>Criteria:</strong> ${esc(a.acceptance_criteria || '')}</div>`;
        }
        html += '</div>';
      });
    }

    // Cross layer observations
    if (crossLayer.length) {
      html += '<h3 class="section-heading">Cross-Layer Observations</h3>';
      crossLayer.forEach(cl => {
        html += `<div class="cross-layer-item"><div class="cross-layer-cat">${esc(cl.category || '')}</div><div>${esc(cl.description || '')}</div>`;
        if (cl.suggestion) html += `<div style="margin-top:4px;color:var(--accent);">${esc(cl.suggestion)}</div>`;
        html += '</div>';
      });
    }

    el.innerHTML = html;

    // Click issue card -> scroll sidebar
    el.querySelectorAll('.issue-card').forEach(card => {
      card.addEventListener('click', () => {
        const itemId = card.dataset.itemId;
        const annoCard = document.querySelector(`.anno-card[data-item-id="${itemId}"]`);
        if (annoCard) {
          annoCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
          annoCard.classList.add('active');
          setTimeout(() => annoCard.classList.remove('active'), 1500);
        }
      });
    });
  }

  // ---- Render annotation sidebar (right panel) ----
  function renderAnnotationSidebar() {
    const data = _reportData.data || {};
    const issues = data.issues || [];
    const container = document.getElementById('anno-cards');
    const existingAnns = (_annotations.items) || {};

    if (!issues.length) {
      container.innerHTML = '<p style="padding:20px;color:var(--text-dim);">No issues to annotate.</p>';
      return;
    }

    container.innerHTML = issues.map(issue => {
      const itemId = issue.item_id;
      const sev = issue.severity || 'P2';
      const ann = existingAnns[itemId] || {};
      const selectedMark = ann.mark || '';

      return `
        <div class="anno-card" data-item-id="${esc(itemId)}">
          <div class="anno-card-header">
            <div class="anno-card-title">${esc(issue.title)}</div>
            <span class="anno-card-sev sev-${sev}">${sev}</span>
          </div>
          <div class="anno-card-gap">${esc(issue.gap_description || '')}</div>
          <div class="mark-selector">
            ${Object.entries(MARKS).map(([k, v]) =>
              `<button class="mark-btn${selectedMark === k ? ' selected' : ''}" data-mark="${k}" data-item-id="${esc(itemId)}">${v.icon} ${v.label}</button>`
            ).join('')}
          </div>
          <textarea class="anno-comment" data-item-id="${esc(itemId)}" placeholder="Comment (optional)...">${esc(ann.comment || '')}</textarea>
          <div class="anno-save-indicator" id="save-${esc(itemId)}"></div>
        </div>
      `;
    }).join('');

    // Bind mark buttons
    container.querySelectorAll('.mark-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const itemId = btn.dataset.itemId;
        const mark = btn.dataset.mark;
        const siblings = btn.parentElement.querySelectorAll('.mark-btn');
        siblings.forEach(s => s.classList.remove('selected'));
        btn.classList.add('selected');
        saveAnnotation(itemId, mark);
        highlightIssueCard(itemId, mark);
      });
    });

    // Bind comment auto-save (debounced)
    container.querySelectorAll('.anno-comment').forEach(ta => {
      ta.addEventListener('input', () => {
        const itemId = ta.dataset.itemId;
        clearTimeout(_saveTimers[itemId]);
        _saveTimers[itemId] = setTimeout(() => {
          const mark = getCurrentMark(itemId);
          if (mark) saveAnnotation(itemId, mark, ta.value);
        }, 800);
      });
    });
  }

  function getCurrentMark(itemId) {
    const sel = document.querySelector(`.mark-btn.selected[data-item-id="${itemId}"]`);
    return sel ? sel.dataset.mark : '';
  }

  function getComment(itemId) {
    const ta = document.querySelector(`.anno-comment[data-item-id="${itemId}"]`);
    return ta ? ta.value : '';
  }

  async function saveAnnotation(itemId, mark, comment) {
    if (comment === undefined) comment = getComment(itemId);
    const { role, name } = getAnnotator();
    const indicator = document.getElementById(`save-${itemId}`);
    try {
      await api(`/api/annotations/${_reportId}/${itemId}`, {
        method: 'PUT',
        body: JSON.stringify({
          mark,
          comment,
          annotator_role: role,
          annotator_name: name,
        }),
      });
      if (!_annotations.items) _annotations.items = {};
      _annotations.items[itemId] = { mark, comment };
      if (indicator) { indicator.textContent = 'Saved'; setTimeout(() => indicator.textContent = '', 1500); }
      updateStats();
      updateSubmitButton();
    } catch (e) {
      if (indicator) indicator.textContent = 'Save failed';
    }
  }

  function highlightIssueCard(itemId, mark) {
    const card = document.getElementById(`issue-${itemId}`);
    if (!card) return;
    card.classList.add('highlighted');
    setTimeout(() => card.classList.remove('highlighted'), 1200);
  }

  // ---- Stats + submit ----
  function updateStats() {
    const el = document.getElementById('anno-stats');
    if (!el) return;
    const items = (_annotations.items) || {};
    const counts = { adopt: 0, discuss: 0, known: 0, na: 0, unmarked: 0 };
    const totalIssues = (_reportData?.data?.issues || []).length;
    Object.values(items).forEach(a => {
      if (counts[a.mark] !== undefined) counts[a.mark]++;
    });
    counts.unmarked = Math.max(0, totalIssues - Object.keys(items).length);

    el.innerHTML = Object.entries(counts).map(([k, v]) =>
      `<span class="stat"><span class="stat-dot ${k}"></span>${v}</span>`
    ).join('');
  }

  function updateSubmitButton() {
    const btn = document.getElementById('btn-submit');
    if (!btn) return;
    const submitted = _annotations.submitted;
    if (submitted) {
      btn.disabled = true;
      btn.textContent = 'Already Submitted';
      const statusEl = document.getElementById('submit-status');
      if (statusEl) statusEl.textContent = `Submitted at ${_annotations.submitted_at || ''}`;
      return;
    }
    const hasAny = Object.keys(_annotations.items || {}).length > 0;
    btn.disabled = !hasAny;
  }

  function bindSubmitFlow() {
    const btn = document.getElementById('btn-submit');
    const overlay = document.getElementById('modal-overlay');
    const cancelBtn = document.getElementById('btn-cancel-submit');
    const confirmBtn = document.getElementById('btn-confirm-submit');

    if (btn) btn.addEventListener('click', () => overlay?.classList.remove('hidden'));
    if (cancelBtn) cancelBtn.addEventListener('click', () => overlay?.classList.add('hidden'));
    if (confirmBtn) confirmBtn.addEventListener('click', doSubmit);
  }

  async function doSubmit() {
    const overlay = document.getElementById('modal-overlay');
    const statusEl = document.getElementById('submit-status');
    const webhook = document.getElementById('dingtalk-webhook')?.value || '';
    const { role, name } = getAnnotator();

    try {
      const resp = await api(`/api/annotations/${_reportId}/submit`, {
        method: 'POST',
        body: JSON.stringify({
          annotator_role: role,
          annotator_name: name,
          dingtalk_webhook: webhook,
        }),
      });
      _annotations.submitted = true;
      _annotations.submitted_at = new Date().toISOString();
      overlay?.classList.add('hidden');
      updateSubmitButton();
      if (statusEl) statusEl.textContent = resp.dingtalk_sent ? 'Submitted + DingTalk sent' : 'Submitted';
    } catch (e) {
      if (statusEl) statusEl.textContent = `Submit failed: ${e.message}`;
    }
  }

  return { initIndex, initReport };
})();
