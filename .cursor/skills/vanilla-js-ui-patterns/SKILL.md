---
name: vanilla-js-ui-patterns
description: UI component patterns for MyAgents projects using vanilla JS + HTML/CSS (no React/Vue). Covers modals, toasts, tables, buttons, and badges. Use when building or modifying frontend UI in pm-system, performeval, or any MyAgents project that uses native HTML/JS.
---

# Vanilla JS UI Patterns

MyAgents 项目群使用原生 JS + HTML/CSS 构建前端，不使用 React/Vue。本 Skill 定义项目中已有的 UI 组件模式，确保新增 UI 与现有风格一致。

## CSS 变量（设计 token）

```css
--primary: #667eea;
--primary-dark: #5a67d8;
--border: #e2e8f0;
--bg-hover: #f8fafc;
--text-primary: #1e293b;
--text-secondary: #64748b;
```

## 1. 模态弹窗

### 标准结构（使用 ModalManager）

```html
<div id="xxxModal" class="modal">
  <div class="modal-content">
    <div class="modal-header">
      <h3>标题</h3>
      <span class="close" onclick="window.ModalManager.close('xxxModal')">&times;</span>
    </div>
    <div class="modal-body">...</div>
    <div class="modal-footer">
      <button class="btn btn-secondary" onclick="ModalManager.close('xxxModal')">取消</button>
      <button class="btn btn-primary" onclick="...">保存</button>
    </div>
  </div>
</div>
```

### 关键样式值

| 属性 | 默认值 | 大弹窗(.modal-xl) |
|------|--------|-------------------|
| max-width | 500px | 1200px |
| width | 90% | 95% |
| border-radius | 12px | 12px |
| z-index | 1000 | 1000 |
| 遮罩背景 | rgba(0,0,0,0.5) + backdrop-filter:blur(4px) | 同 |

### 内联弹窗（不依赖 ModalManager）

data-manager.js 等模块使用内联 HTML 创建临时弹窗：

```javascript
const html = `<div style="position:fixed;inset:0;background:rgba(0,0,0,.45);display:flex;align-items:center;justify-content:center;z-index:10000;">
  <div style="background:#fff;border-radius:12px;max-width:480px;width:92%;box-shadow:0 8px 32px rgba(0,0,0,.25);">
    <div style="padding:18px 22px 14px;">...</div>
    <div style="padding:0 22px 16px;">...</div>
    <div style="padding:14px 22px;border-top:1px solid #f1f5f9;display:flex;justify-content:flex-end;gap:8px;">...</div>
  </div>
</div>`;
document.body.insertAdjacentHTML('beforeend', html);
```

### 关闭方式

- 关闭按钮 `&times;`（右上角）
- Footer 取消按钮
- ESC 键（ModalManager 内建）
- 遮罩点击（部分弹窗支持）

## 2. Toast 通知

使用 `ui/toast.js` 的 `Toast` 类。

```javascript
Toast.show('操作成功', 'success');
Toast.show('出错了', 'error');
Toast.show('请注意', 'warning');
Toast.show('提示信息', 'info');
```

### 配色方案

| 类型 | 背景 | 边框 | 文字 |
|------|------|------|------|
| success | #d1fae5 | #10b981 | #065f46 |
| warning | #fef3c7 | #f59e0b | #92400e |
| error | #fee2e2 | #ef4444 | #991b1b |
| info | #dbeafe | #3b82f6 | #1e40af |

### 行为

- 位置：右上角 `top:16px; right:16px; z-index:99999`
- 入场动画：`translateX(120%)` → `translateX(0)`，300ms ease
- 默认 3000ms 后自动消失，`duration:0` 常驻

## 3. 数据表格

### 表头

```css
th {
    background: #f8fafc;
    padding: 10px 15px;
    color: #64748b;
    font-weight: 600;
    border-bottom: 1px solid #e2e8f0;
}
```

### 斑马纹

内联方式：`background: li % 2 === 1 ? '#fafbfc' : ''`

### 固定表头

```css
th { position: sticky; top: 0; z-index: 10; }
```

### 溢出处理

外层容器加 `overflow-x: auto; overflow-y: auto`。无 `@media` 响应式，依赖滚动。

## 4. 按钮

### 基础

```css
.btn { padding: 0.5rem 1rem; border-radius: 6px; font-size: 0.875rem; font-weight: 500; }
```

### 变体

| 类名 | 背景 | 文字 | Hover |
|------|------|------|-------|
| btn-primary | #667eea | white | #5a67d8 |
| btn-secondary | white | text-primary | border→primary |
| btn-danger | #ef4444 | white | #dc2626 |
| btn-ghost | transparent | - | #f1f5f9 |
| btn-sm | - | - | padding:0.25rem 0.5rem; font-size:0.75rem |

### 内联按钮（弹窗内）

```css
padding: 7px 18px; border: none; border-radius: 6px; font-size: 13px; cursor: pointer;
```

## 5. Badge / Pill / Tag

### 通用 Badge

```css
.badge { padding: 0.25rem 0.75rem; border-radius: 999px; font-size: 0.75rem; font-weight: 600; }
```

### 语义色

| 语义 | 背景 | 文字 |
|------|------|------|
| 成功/高 | #d1fae5 | #065f46 |
| 警告/中 | #fef3c7 | #92400e |
| 危险/P0 | #fee2e2 | #991b1b |
| 信息/P2 | #dbeafe | #1e40af |

### Pill 标签（紧凑内联）

```html
<span style="display:inline-flex;align-items:center;gap:3px;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;color:${color};background:${bg};">
  ${label} ${count}
</span>
```

### Dimension Tag（带动态颜色）

```html
<span style="background-color:${color}20;color:${textColor};border:1px solid ${color};font-size:11px;padding:4px 6px;border-radius:4px;">
```

## 规则

- 优先使用项目已有的 CSS 类（`.btn-primary`、`.badge`、`.modal`）
- 内联样式仅用于 JS 动态生成的临时元素（弹窗、Toast）
- 颜色遵循上述配色方案，不要引入新的颜色系统
- 不使用任何 CSS 框架（Tailwind、Bootstrap 等）
- 不使用任何 JS 框架（React、Vue、jQuery 等）
