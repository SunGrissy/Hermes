from pathlib import Path

src = Path('D:/MyAgents/会议材料/驯化野生硅基伙伴_HTML_PPT.html')
dst = Path('D:/MyAgents/会议材料/驯化野生硅基伙伴_可编辑互动版.html')
text = src.read_text(encoding='utf-8')

extra_css = r'''
/* Editable interactive version */
body.edit-mode .editable {
  outline: 1px dashed rgba(32,199,174,.55);
  outline-offset: 3px;
  border-radius: 6px;
  cursor: text;
}
body.edit-mode .editable:hover {
  outline-color: rgba(214,173,97,.85);
  background: rgba(214,173,97,.055);
}
body.edit-mode .editable:focus {
  outline: 2px solid rgba(32,199,174,.95);
  background: rgba(32,199,174,.08);
  box-shadow: 0 0 0 4px rgba(32,199,174,.12);
}
body:not(.edit-mode) .editable { cursor: default; }
.edit-panel {
  position: fixed;
  top: 14px;
  right: 14px;
  z-index: 80;
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 258px;
  padding: 12px;
  background: rgba(5,8,18,.88);
  border: 1px solid rgba(255,255,255,.13);
  border-radius: 18px;
  backdrop-filter: blur(16px);
  box-shadow: 0 18px 50px rgba(0,0,0,.42);
  color: var(--text);
  font-size: 12px;
}
.edit-panel .row { display:flex; gap:8px; flex-wrap:wrap; }
.edit-panel button {
  flex: 1;
  min-width: 70px;
  border: 1px solid rgba(255,255,255,.13);
  background: rgba(255,255,255,.06);
  color: var(--text);
  border-radius: 999px;
  padding: 7px 10px;
  cursor: pointer;
  font-size: 12px;
}
.edit-panel button.primary { border-color: rgba(32,199,174,.45); color: var(--teal); background: rgba(32,199,174,.08); }
.edit-panel button.warn { border-color: rgba(255,95,125,.42); color: var(--rose); background: rgba(255,95,125,.07); }
.edit-panel button:hover { border-color: rgba(214,173,97,.62); color: var(--gold); }
.edit-status { color: var(--muted); line-height: 1.45; }
.edit-status strong { color: var(--teal); font-weight: 700; }
.edit-hint { color: var(--sub); line-height: 1.45; }
.toast {
  position: fixed;
  top: 18px;
  left: 50%;
  transform: translateX(-50%) translateY(-8px);
  z-index: 100;
  opacity: 0;
  transition: all .22s ease;
  background: rgba(5,8,18,.92);
  border: 1px solid rgba(32,199,174,.38);
  color: var(--text);
  border-radius: 999px;
  padding: 9px 16px;
  box-shadow: 0 12px 38px rgba(0,0,0,.4);
  pointer-events:none;
  font-size: 13px;
}
.toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }
@media print { .edit-panel,.toast{display:none!important} body.edit-mode .editable{outline:none!important;background:transparent!important;box-shadow:none!important} }
'''
text = text.replace('@media print{', extra_css + '\n@media print{', 1)

old_controls = '<div class="controls"><button onclick="prevSlide()">上一页</button><button onclick="nextSlide()">下一页</button><button onclick="window.print()">打印 PDF</button><button onclick="fitToWindow()">适配窗口</button></div>'
new_controls = r'''<div class="edit-panel" id="editPanel">
  <div class="edit-status"><strong>可编辑互动版</strong><br><span id="saveStatus">准备就绪</span></div>
  <div class="row"><button class="primary" onclick="toggleEditMode()" id="editModeBtn">关闭编辑</button><button onclick="manualSave()">手动保存</button></div>
  <div class="row"><button onclick="downloadCurrentHtml()">下载 HTML</button><button onclick="saveAsLocalFile()">另存文件</button></div>
  <div class="row"><button onclick="window.print()">打印 PDF</button><button class="warn" onclick="resetEdits()">重置修改</button></div>
  <div class="edit-hint">点页面文字即可修改；浏览器会自动保存。改完建议点“下载 HTML”留一份实体文件。</div>
</div>
<div class="toast" id="toast"></div>
<div class="controls"><button onclick="prevSlide()">上一页</button><button onclick="nextSlide()">下一页</button><button onclick="window.print()">打印 PDF</button><button onclick="fitToWindow()">适配窗口</button></div>'''
if old_controls not in text:
    raise SystemExit('controls marker not found')
text = text.replace(old_controls, new_controls, 1)

start = text.index('<script>')
end = text.index('</script>', start) + len('</script>')
new_script = r'''<script>
const STORAGE_KEY = 'silicon_partner_deck_editable_v1';
const PAGE_KEY = 'silicon_partner_deck_page_editable_v1';
let current = Number(localStorage.getItem(PAGE_KEY) || 0);
let editMode = localStorage.getItem('silicon_partner_edit_mode') !== 'off';
let saveTimer = null;
let fileHandle = null;

function getSlides(){ return [...document.querySelectorAll('.slide')]; }
function getDeck(){ return document.getElementById('deck'); }

function toast(message){
  const el = document.getElementById('toast');
  if(!el) return;
  el.textContent = message;
  el.classList.add('show');
  clearTimeout(el._timer);
  el._timer = setTimeout(()=>el.classList.remove('show'), 1800);
}
function setStatus(message){
  const el = document.getElementById('saveStatus');
  if(el) el.textContent = message;
}
function nowText(){
  const d = new Date();
  return d.toLocaleTimeString('zh-CN', {hour12:false});
}

function markEditable(){
  const selectors = [
    '.kicker','.slide-title','.slide-subtitle','.big-quote','.callout',
    '.card h3','.card p','.card .label','.card li','.stat','.stat-label',
    '.node .num','.node h3','.node p','.step h3','.step p','.circle',
    '.prompt','.cover .eyebrow','.cover h1','.cover .subtitle','.cover .meta',
    '.table th','.table td','.footer'
  ].join(',');
  document.querySelectorAll(selectors).forEach((el, idx)=>{
    if(el.closest('.controls') || el.closest('.edit-panel')) return;
    el.classList.add('editable');
    el.setAttribute('contenteditable', editMode ? 'true' : 'false');
    el.setAttribute('spellcheck','false');
    if(!el.dataset.editId) el.dataset.editId = 'e' + idx;
  });
}

function applyEditMode(){
  document.body.classList.toggle('edit-mode', editMode);
  document.querySelectorAll('.editable').forEach(el=>el.setAttribute('contenteditable', editMode ? 'true' : 'false'));
  const btn = document.getElementById('editModeBtn');
  if(btn) btn.textContent = editMode ? '关闭编辑' : '开启编辑';
  localStorage.setItem('silicon_partner_edit_mode', editMode ? 'on' : 'off');
}
function toggleEditMode(){ editMode = !editMode; applyEditMode(); toast(editMode ? '编辑模式已开启' : '编辑模式已关闭'); }

function cleanDeckClone(){
  const clone = getDeck().cloneNode(true);
  clone.querySelectorAll('[contenteditable]').forEach(el=>{
    el.removeAttribute('contenteditable');
    el.removeAttribute('spellcheck');
  });
  clone.querySelectorAll('.editable').forEach(el=>el.classList.remove('editable'));
  return clone.innerHTML;
}
function saveToLocalStorage(silent=false){
  const payload = {
    savedAt: new Date().toISOString(),
    deckHtml: getDeck().innerHTML
  };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
  setStatus('已自动保存 ' + nowText());
  if(!silent) toast('已保存到浏览器');
}
function scheduleSave(){
  setStatus('正在编辑，准备自动保存…');
  clearTimeout(saveTimer);
  saveTimer = setTimeout(()=>saveToLocalStorage(true), 450);
}
function manualSave(){ saveToLocalStorage(false); }

function restoreSaved(){
  const raw = localStorage.getItem(STORAGE_KEY);
  if(!raw) return false;
  try{
    const payload = JSON.parse(raw);
    if(payload && payload.deckHtml){
      getDeck().innerHTML = payload.deckHtml;
      setStatus('已恢复上次修改 ' + new Date(payload.savedAt).toLocaleString('zh-CN'));
      return true;
    }
  }catch(e){ console.warn('restore failed', e); }
  return false;
}

function resetEdits(){
  if(!confirm('确定要清空浏览器里保存的修改，恢复到这个 HTML 文件内置版本吗？')) return;
  localStorage.removeItem(STORAGE_KEY);
  toast('已清空修改，正在刷新');
  setTimeout(()=>location.reload(), 350);
}

function buildStandaloneHtml(){
  manualSave();
  const doc = document.documentElement.cloneNode(true);
  doc.querySelectorAll('.toast').forEach(el=>el.classList.remove('show'));
  doc.querySelectorAll('[contenteditable]').forEach(el=>el.removeAttribute('contenteditable'));
  doc.querySelectorAll('.editable').forEach(el=>el.classList.remove('editable'));
  doc.querySelectorAll('#saveStatus').forEach(el=>el.textContent='此文件已内嵌保存时的最新内容');
  doc.querySelectorAll('body').forEach(el=>el.classList.remove('edit-mode'));
  return '<!DOCTYPE html>\n' + doc.outerHTML;
}
function downloadCurrentHtml(){
  const html = buildStandaloneHtml();
  const blob = new Blob([html], {type:'text/html;charset=utf-8'});
  const a = document.createElement('a');
  const ts = new Date().toISOString().slice(0,19).replace(/[:T]/g,'-');
  a.href = URL.createObjectURL(blob);
  a.download = '驯化野生硅基伙伴_可编辑互动版_' + ts + '.html';
  document.body.appendChild(a);
  a.click();
  setTimeout(()=>{URL.revokeObjectURL(a.href); a.remove();}, 500);
  toast('已下载当前 HTML');
}
async function saveAsLocalFile(){
  const html = buildStandaloneHtml();
  if(!window.showSaveFilePicker){
    toast('当前浏览器不支持直接另存，已改为下载');
    downloadCurrentHtml();
    return;
  }
  try{
    fileHandle = await window.showSaveFilePicker({
      suggestedName: '驯化野生硅基伙伴_可编辑互动版.html',
      types: [{description:'HTML 文件', accept:{'text/html':['.html']}}]
    });
    const writable = await fileHandle.createWritable();
    await writable.write(html);
    await writable.close();
    toast('已保存到本地文件');
    setStatus('已保存到本地文件 ' + nowText());
  }catch(e){
    if(e && e.name === 'AbortError') return;
    console.error(e);
    toast('另存失败，建议用下载 HTML');
  }
}

function go(i){
  const slides = getSlides();
  current = Math.max(0, Math.min(slides.length-1, i));
  localStorage.setItem(PAGE_KEY, String(current));
  slides[current].scrollIntoView({behavior:'smooth', block:'center'});
}
function nextSlide(){ go(current+1); }
function prevSlide(){ go(current-1); }
function isEditingText(){
  const ae = document.activeElement;
  return ae && (ae.isContentEditable || ['INPUT','TEXTAREA'].includes(ae.tagName));
}
document.addEventListener('keydown', e=>{
  if((e.ctrlKey || e.metaKey) && e.key.toLowerCase()==='s'){
    e.preventDefault(); manualSave(); return;
  }
  if(isEditingText()) return;
  if(['ArrowRight','PageDown',' '].includes(e.key)){ e.preventDefault(); nextSlide(); }
  if(['ArrowLeft','PageUp'].includes(e.key)){ e.preventDefault(); prevSlide(); }
  if(e.key==='Home') go(0);
  if(e.key==='End') go(getSlides().length-1);
});

document.addEventListener('input', e=>{
  if(e.target && e.target.closest && e.target.closest('.editable')) scheduleSave();
});
document.addEventListener('paste', e=>{
  if(!(e.target && e.target.closest && e.target.closest('.editable'))) return;
  e.preventDefault();
  const text = (e.clipboardData || window.clipboardData).getData('text/plain');
  document.execCommand('insertText', false, text);
});

function fitToWindow(){
  const slides = getSlides();
  const scale = Math.min((window.innerWidth-24)/1280, (window.innerHeight-96)/720, 1);
  slides.forEach(s=>{
    s.style.transform = `scale(${scale})`;
    s.style.transformOrigin = 'top center';
    s.style.marginBottom = `${22-(720*(1-scale))}px`;
  });
}
window.addEventListener('load', ()=>{
  restoreSaved();
  markEditable();
  applyEditMode();
  fitToWindow();
  setTimeout(()=>go(current),80);
  if(!localStorage.getItem(STORAGE_KEY)) setStatus('准备就绪：点击文字即可修改');
});
window.addEventListener('resize', fitToWindow);
window.addEventListener('beforeunload', ()=>saveToLocalStorage(true));
</script>'''
text = text[:start] + new_script + text[end:]
text = text.replace('<title>驯化野生硅基伙伴｜HTML PPT</title>', '<title>驯化野生硅基伙伴｜可编辑互动版</title>')
dst.write_text(text, encoding='utf-8')
print(dst.as_posix())
print(dst.stat().st_size)
