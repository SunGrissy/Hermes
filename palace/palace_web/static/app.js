/**
 * Palace Annotation System — Frontend v0.2
 */
const PalaceApp = (() => {
  const API = window.location.origin;
  const MARKS = {
    adopt:   { label: '采纳',   icon: '\ud83d\udd34', css: 'adopt' },
    discuss: { label: '待议',   icon: '\ud83d\udfe1', css: 'discuss' },
    known:   { label: '已知',   icon: '\ud83d\udfe2', css: 'known' },
    na:      { label: '不适用', icon: '\u26aa',       css: 'na' },
  };
  const VERDICT_TEXT = { pass: '通过', concern: '有风险', block: '未达标', error: '异常' };
  const SEV_LABELS = {
    P0: 'P0 阻断', P1: 'P1 必改', P2: 'P2 建议', P3: 'P3 信息',
    WARN: '预警', INFO: '提醒',
  };
  const ROLE_LABELS = {
    producer: '制作人', pld: '管线主策', pmo: '管线总管',
    ple: '管线体验', plt: '管线技术',
  };
  const WEIGHT_LABELS = { slow: '慢轨', fast: '快轨' };

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

  function isSubmitted() {
    return !!_annotations.submitted;
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
        container.innerHTML = '<div class="empty-state"><h3>暂无报告</h3><p>使用导入工具发布报告：py palace/palace_web/import_report.py &lt;json&gt;</p></div>';
        return;
      }
      container.innerHTML = reports.map(r => `
        <div class="report-card" onclick="location.href='/report/${esc(r.id)}'">
          <div class="rc-left">
            <div class="title">${esc(r.title)}</div>
            <div class="meta">
              <span class="badge badge-${r.overall_verdict || 'error'}">${VERDICT_TEXT[r.overall_verdict] || '?'}</span>
              ${r.submitted ? '<span class="badge badge-submitted">已提交</span>' : ''}
              <span>${r.annotation_count ? r.annotation_count + ' 条批注' : ''}</span>
            </div>
          </div>
          <div class="rc-right">
            <span class="rc-date">${r.created_at ? new Date(r.created_at).toLocaleString('zh-CN') : ''}</span>
          </div>
        </div>
      `).join('');
    } catch (e) {
      container.innerHTML = `<div class="empty-state"><h3>加载失败</h3><p>${esc(e.message)}</p></div>`;
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
      if (isSubmitted()) applyReadonly();
    } catch (e) {
      document.getElementById('report-content').innerHTML =
        `<div class="empty-state"><h3>加载失败</h3><p>${esc(e.message)}</p></div>`;
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

    html += `<h1 class="rpt-title">${esc(_reportData.title || _reportData.feature_title || '报告')}</h1>`;
    html += '<div class="rpt-meta">';
    if (_reportData.scenario_id) html += `<div class="meta-item"><span class="meta-label">场景：</span><span class="meta-value">${esc(_reportData.scenario_id)}</span></div>`;
    if (_reportData.pipeline_weight) html += `<div class="meta-item"><span class="meta-label">轨道：</span><span class="meta-value">${WEIGHT_LABELS[_reportData.pipeline_weight] || _reportData.pipeline_weight}</span></div>`;
    if (_reportData.document_layer) html += `<div class="meta-item"><span class="meta-label">文档层级：</span><span class="meta-value">${esc(_reportData.document_layer)}</span></div>`;
    if (_reportData.created_at) html += `<div class="meta-item"><span class="meta-label">创建时间：</span><span class="meta-value">${new Date(_reportData.created_at).toLocaleString('zh-CN')}</span></div>`;
    html += '</div>';

    const verdictLabels = {
      pass: '通过 \u2014 可进入下一阶段',
      concern: '有风险 \u2014 需关注风险项',
      block: '未达标 \u2014 需修改后重新提审',
      error: '异常',
    };
    html += `<div class="rpt-verdict ${ov}">${verdictLabels[ov] || ov} (${data.blocker_count || 0} 阻断, ${data.concern_count || 0} 风险)</div>`;

    if (layerOverview.length) {
      html += '<h3 class="section-heading">文档分层概览</h3>';
      html += '<table class="layer-table"><thead><tr><th>层级</th><th>占比</th><th>完成度</th><th>关键缺口</th></tr></thead><tbody>';
      layerOverview.forEach(lo => {
        html += `<tr><td>${esc(lo.layer)}</td><td>${esc(lo.ratio || '')}</td><td>${esc(lo.completeness || '')}</td><td>${esc(lo.key_gaps || '')}</td></tr>`;
      });
      html += '</tbody></table>';
    }

    if (issues.length) {
      html += `<h3 class="section-heading">审查发现 (${issues.length})</h3>`;
      issues.forEach(issue => {
        const sev = issue.severity || 'P2';
        const existingAnns = (_annotations.items) || {};
        const ann = existingAnns[issue.item_id] || {};
        const markCss = ann.mark ? `mark-${ann.mark}` : '';
        const markIcon = ann.mark ? MARKS[ann.mark]?.icon || '' : '';

        html += `<div class="issue-card ${markCss}" id="issue-${esc(issue.item_id)}" data-item-id="${esc(issue.item_id)}">`;
        html += '<div class="issue-header">';
        html += `<span class="anno-card-sev sev-${sev}">${sev}</span>`;
        html += `<span class="issue-title">${esc(issue.title)}</span>`;
        if (markIcon) html += `<span class="issue-mark-icon" title="${MARKS[ann.mark]?.label || ''}">${markIcon}</span>`;
        if (issue.layer) html += `<span class="issue-layer">${esc(issue.layer)}</span>`;
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
          html += `<div class="issue-action"><strong>目标：</strong>${esc(a.target_state || '')} | <strong>现状：</strong>${esc(a.current_status || '')} | <strong>达标要求：</strong>${esc(a.acceptance_criteria || '')}</div>`;
        }
        html += '</div>';
      });
    }

    if (crossLayer.length) {
      html += '<h3 class="section-heading">跨层观察</h3>';
      crossLayer.forEach(cl => {
        html += `<div class="cross-layer-item"><div class="cross-layer-cat">${esc(cl.category || '')}</div><div>${esc(cl.description || '')}</div>`;
        if (cl.suggestion) html += `<div style="margin-top:4px;color:var(--accent);">${esc(cl.suggestion)}</div>`;
        html += '</div>';
      });
    }

    el.innerHTML = html;

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

  // ---- Update mark indicator on left panel issue card ----
  function updateIssueCardMark(itemId, mark) {
    const card = document.getElementById(`issue-${itemId}`);
    if (!card) return;
    Object.keys(MARKS).forEach(m => card.classList.remove(`mark-${m}`));
    if (mark) card.classList.add(`mark-${mark}`);
    let iconEl = card.querySelector('.issue-mark-icon');
    if (mark) {
      if (!iconEl) {
        iconEl = document.createElement('span');
        iconEl.className = 'issue-mark-icon';
        card.querySelector('.issue-header').appendChild(iconEl);
      }
      iconEl.textContent = MARKS[mark]?.icon || '';
      iconEl.title = MARKS[mark]?.label || '';
    } else if (iconEl) {
      iconEl.remove();
    }
  }

  // ---- Render annotation sidebar (right panel) ----
  function renderAnnotationSidebar() {
    const data = _reportData.data || {};
    const issues = data.issues || [];
    const container = document.getElementById('anno-cards');
    const existingAnns = (_annotations.items) || {};
    const readonly = isSubmitted();

    if (!issues.length) {
      container.innerHTML = '<p style="padding:20px;color:var(--text-dim);">无审查发现需要批注。</p>';
      return;
    }

    container.innerHTML = issues.map(issue => {
      const itemId = issue.item_id;
      const sev = issue.severity || 'P2';
      const ann = existingAnns[itemId] || {};
      const selectedMark = ann.mark || '';
      const disabledAttr = readonly ? ' disabled' : '';
      const readonlyAttr = readonly ? ' readonly' : '';

      return `
        <div class="anno-card" data-item-id="${esc(itemId)}">
          <div class="anno-card-header">
            <div class="anno-card-title">${esc(issue.title)}</div>
            <span class="anno-card-sev sev-${sev}">${sev}</span>
          </div>
          <div class="anno-card-gap">${esc(issue.gap_description || '')}</div>
          <div class="mark-selector">
            ${Object.entries(MARKS).map(([k, v]) =>
              `<button class="mark-btn${selectedMark === k ? ' selected' : ''}" data-mark="${k}" data-item-id="${esc(itemId)}"${disabledAttr}>${v.icon} ${v.label}</button>`
            ).join('')}
          </div>
          <textarea class="anno-comment" data-item-id="${esc(itemId)}" placeholder="备注（可选）..."${readonlyAttr}>${esc(ann.comment || '')}</textarea>
          <div class="anno-save-indicator" id="save-${esc(itemId)}"></div>
        </div>
      `;
    }).join('');

    if (!readonly) {
      container.querySelectorAll('.mark-btn').forEach(btn => {
        btn.addEventListener('click', () => {
          const itemId = btn.dataset.itemId;
          const mark = btn.dataset.mark;
          const siblings = btn.parentElement.querySelectorAll('.mark-btn');
          siblings.forEach(s => s.classList.remove('selected'));
          btn.classList.add('selected');
          saveAnnotation(itemId, mark);
          updateIssueCardMark(itemId, mark);
        });
      });

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
    if (isSubmitted()) return;
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
      if (indicator) { indicator.textContent = '\u2713 \u5df2\u4fdd\u5b58'; setTimeout(() => indicator.textContent = '', 1500); }
      updateStats();
      updateSubmitButton();
    } catch (e) {
      if (indicator) indicator.textContent = '\u4fdd\u5b58\u5931\u8d25';
    }
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

    const labels = { adopt: '采纳', discuss: '待议', known: '已知', na: '不适用', unmarked: '未批' };
    el.innerHTML = Object.entries(counts).map(([k, v]) =>
      `<span class="stat"><span class="stat-dot ${k}"></span>${labels[k]} ${v}</span>`
    ).join('');
  }

  function updateSubmitButton() {
    const btn = document.getElementById('btn-submit');
    if (!btn) return;
    if (isSubmitted()) {
      btn.disabled = true;
      btn.textContent = '\u5df2\u63d0\u4ea4';
      const statusEl = document.getElementById('submit-status');
      if (statusEl) {
        const by = _annotations.submitted_by;
        const who = by ? (ROLE_LABELS[by.role] || by.role) + (by.name ? ` ${by.name}` : '') : '';
        const when = _annotations.submitted_at ? new Date(_annotations.submitted_at).toLocaleString('zh-CN') : '';
        statusEl.textContent = `${who} \u4e8e ${when} \u63d0\u4ea4`;
      }
      return;
    }
    const hasAny = Object.keys(_annotations.items || {}).length > 0;
    btn.disabled = !hasAny;
  }

  function applyReadonly() {
    document.querySelectorAll('.mark-btn').forEach(b => b.disabled = true);
    document.querySelectorAll('.anno-comment').forEach(t => t.readOnly = true);
    const picker = document.querySelector('.annotator-picker');
    if (picker) picker.style.opacity = '0.5';
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
      _annotations.submitted_by = { role, name };
      overlay?.classList.add('hidden');
      updateSubmitButton();
      applyReadonly();
      if (statusEl) {
        statusEl.textContent = resp.dingtalk_sent
          ? '\u2713 \u5df2\u63d0\u4ea4\uff0c\u9489\u9489\u901a\u77e5\u5df2\u53d1\u9001'
          : '\u2713 \u5df2\u63d0\u4ea4';
      }
    } catch (e) {
      if (statusEl) statusEl.textContent = `\u63d0\u4ea4\u5931\u8d25\uff1a${e.message}`;
    }
  }

  return { initIndex, initReport };
})();
