---
name: html-slide-deck
description: 用 HTML/CSS 生成演示文稿级别的幻灯片，深色主题，支持浏览器直接打印为 PDF。包含完整组件库（数据卡片、高亮框、双栏、步骤列表、表格等）。Use when the user asks to create slides, presentations, decks, 演示文稿, 汇报材料, PPT, or wants to turn documents/notes into visual presentation format.
---

# HTML 演示文稿生成

把文字素材变成可交付的演示文稿，不需要 PowerPoint。浏览器打开即演示，Ctrl+P 即 PDF。

## 何时使用

- 用户要做汇报/分享/述职，需要视觉化呈现
- 用户提供了原始素材（会议记录、工作日志、文档），需要转化为幻灯片
- 用户说"做个 PPT"、"做个演示"、"帮我做幻灯片"

## 模板来源

CSS 样式系统已**完整内嵌在本 SKILL.md** 的「色彩系统」和各组件代码示例中，无需读取外部文件。

如工作区内存在历史幻灯片 HTML 文件（如 `会议材料/` 下的 `.html`），可读取其 `<style>` 块作为补充参考，但不强制依赖。生成新演示时，以本文件的组件速查为准重新构建 CSS。

## 幻灯片基本结构

```html
<div class="slide">
  <div class="slide-title">页面标题</div>
  <div class="slide-subtitle">章节标记 · 副标题说明</div>
  <div class="slide-body">
    <!-- 内容区 -->
  </div>
  <div class="page-num">1 / N</div>
</div>
```

特殊页面类型：
- **封面**：`<div class="slide cover">` — 居中布局，标题加大
- **章节页**：`<div class="slide section-break">` — 左对齐，标题 42px

## 组件速查

### 1. 数据卡片（data-card）— 用于关键数字、概念对比

```html
<div class="data-grid cols-3">
  <div class="data-card">
    <div class="label">标签</div>
    <div class="value">79</div>
    <div class="desc">说明文字</div>
  </div>
  <!-- 更多卡片 -->
</div>
```

- `cols-2` / `cols-3` / `cols-4` 控制列数
- 可加 `style="border-left:3px solid var(--accent-gold)"` 做左侧色条
- 可加 `style="border-top:3px solid var(--accent-blue)"` 做顶部色条
- 可加 `style="text-align:center"` 居中展示数字

### 2. 高亮框（highlight-box）— 用于核心观点、总结

```html
<div class="highlight-box">
  核心观点。<strong>加粗强调。</strong>
</div>
```

- 左侧默认金色边条，可用 `style="border-left-color:var(--accent-rose)"` 换色
- 适合放在页面底部做收束

### 3. 双栏布局（two-col）— 用于对比、分类

```html
<div class="two-col">
  <div>
    <div class="col-title">左栏标题</div>
    <ul class="bullet-list"><li>内容</li></ul>
  </div>
  <div>
    <div class="col-title">右栏标题</div>
    <ul class="bullet-list"><li>内容</li></ul>
  </div>
</div>
```

### 4. 步骤列表（steps-list）— 用于流程、递进

```html
<ol class="steps-list">
  <li><strong>步骤标题</strong>　详细说明</li>
  <li><strong>步骤标题</strong>　详细说明</li>
</ol>
```

自动生成圆形编号，金色边框。

### 5. 表格（clean table）— 用于多维度信息

```html
<table class="clean">
  <tr><th>列1</th><th>列2</th><th>列3</th></tr>
  <tr><td>内容</td><td>内容</td><td>内容</td></tr>
</table>
```

- 第一列自动加粗
- 用 `style="width:Npx"` 控制列宽，中间列留 auto 自适应

### 6. 标签（tag）— 用于分类标记

```html
<span class="tag tag-gold">标签</span>
<span class="tag tag-blue">标签</span>
<span class="tag tag-teal">标签</span>
<span class="tag tag-rose">标签</span>
```

### 7. 关键论点（key-point）— 用于引导句

```html
<div class="key-point">
  一段引导性文字，<strong>加粗是金色。</strong>
</div>
```

### 8. 项目列表（bullet-list）— 用于简洁列举

```html
<ul class="bullet-list">
  <li><strong style="color:var(--text-primary);">重点</strong>：说明</li>
  <li>普通条目</li>
</ul>
```

每项前自动带金色破折号。

## 色彩系统

| 变量 | 色值 | 语义 |
|------|------|------|
| `--accent-gold` | #d4a857 | 主强调、标题、核心数字 |
| `--accent-amber` | #f59e0b | 次强调、警示 |
| `--accent-blue` | #3b82f6 | 信息、技术、第一阶段 |
| `--accent-teal` | #14b8a6 | 正面、完成、硅基 |
| `--accent-rose` | #f43f5e | 负面、风险、紧急 |
| `--accent-violet` | #8b5cf6 | 特殊、概率性、创意 |
| `--text-primary` | #e8e6e3 | 主文字 |
| `--text-secondary` | #9ca3af | 次要文字 |
| `--text-muted` | #6b7280 | 辅助说明、脚注 |

## 信息密度原则

1. **一页一个核心观点** — 超过两个独立概念必须拆页
2. **highlight-box 不超过 3 行** — 超过就该拆成卡片
3. **表格不超过 6 行** — 超过就拆页或改用卡片
4. **文字大小层级**：标题 36px → 副标题 16px → 正文 17px → 说明 15px → 脚注 14px → 微注 12px

## 生成流程

1. **理解素材**：读完用户提供的所有原始材料
2. **提炼结构**：按叙事逻辑拆成 N 页，每页一个核心观点
3. **选组件**：根据内容类型选择合适的组件（数字用卡片、对比用双栏、流程用步骤列表）
4. **写骨架**：先用 Write 创建包含 CSS + 所有 slide 占位的文件
5. **逐页填充**：用 StrReplace 逐页替换占位内容
6. **页码同步**：确保所有 `page-num` 连续且总数正确

## 打印为 PDF

模板已内置 `@media print` 配置：
- 页面尺寸 1280×720px
- 自动分页
- 颜色保真（`print-color-adjust: exact`）

用户只需：浏览器打开 → Ctrl+P → 目标选"另存为 PDF" → 边距选"无" → 打印
