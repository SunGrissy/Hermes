---
name: pm-data-sync
description: Architecture guide for PmSystem's data synchronization and conflict merge system. Use when working on pm-system data loading, saving, conflict resolution, import/export, or any sync-related logic in data-manager.js.
---

# PmSystem 数据同步架构

pm-system 的数据同步模块位于 `data-manager.js`，负责本地 ↔ 服务器的数据同步、三方合并、冲突处理和数据导入。

## 核心数据流

```
app.init()
  └─ DataManager.loadData(app)
       ├─ [本地模式] loadDataFromLocalStorage(app)
       ├─ [API模式] fetch /api/data → 对比本地/服务器
       │    ├─ 无差异 → 使用服务器数据
       │    ├─ 仅本地变化 → 使用本地 + saveToBackend
       │    └─ 双端变化 → _doConflictMerge
       └─ [失败兜底] loadDataFromLocalStorage(app)

app.saveData()
  └─ DataManager.saveData(app)
       ├─ localStorage 写入 (gamedev-pm-data-v6, pm-system-data)
       ├─ saveToBackend → POST /api/data（带 `baseRevision: app._knownServerRevision`）
       └─ _markSynced → _saveSyncBase

**整包乐观锁 `dataRevision`**

- `GET /api/data` 与 `GET /api/data/meta` 响应含 `dataRevision`（整数，单调递增，存于 SQLite `AppConfig.dataRevision`）。
- 前端 `app._knownServerRevision` 在 load / 保存成功 / 心跳 meta 更新时与服务器对齐。
- `POST /api/data` 若带 `baseRevision` 且 **小于** 服务器当前 revision → **409**，正文含 `serverRevision`、`serverLastSaved`；前端 `saveToBackend` 会拉取服务器整包并走 `_doConflictMerge`。
- 未带 `baseRevision`（旧客户端）时服务端降级为 Last-Write-Wins 并打 WARN 日志。

[心跳] _startSyncHeartbeat (每15秒)
  └─ fetch /api/data/meta → 比较 lastSaved **与 dataRevision**
       └─ _fetchRemoteAndShowBanner
            ├─ 无冲突 → 自动合并 + Toast
            └─ 有冲突 → 设 pm-pending-conflict + 显示 Banner
```

## 三方合并

### `_smartMerge(localData, serverData)` → `{ merged, conflictItems, autoMergedCount }`

- **base**：从 `localStorage('pm-sync-base')` 读取上次同步快照
- **逻辑**：对维度值和版本逐 id 比较 local/server/base
  - base 存在 → `_threeWayMergeItem` 字段级合并
  - 可自动解决 → 写入 merged
  - 不可自动解决 → push 到 conflictItems
- **merged** 以 server 为基准，仅替换可自动合并的部分
- **conflictItems** 每项包含 `_conflictFields`（冲突字段列表）和 `_autoMerged`（已自动解决的字段）

### `_doConflictMerge(localData, serverData, app)`

1. 调用 `_smartMerge` 得到合并结果
2. 无冲突 → 直接应用 smartMerged
3. 有冲突 →
   - 设置 `pm-pending-conflict = '1'`
   - `_buildConflictItems` 生成展示用对比数据
   - 用 `conflictItems` 的 id 筛出需弹窗的 `dialogItems`
   - 注入 `_conflictFields` / `_autoMerged` 到 dialogItems
   - 判断当前页面是否与冲突相关（`_getRelevantConflictCats`）
     - 不相关 → 显示 Banner，暂不弹窗
     - 相关 → `_showConflictDialog` 弹窗让用户选择
4. 应用用户选择：
   - 选"服务器" → smartMerged 已包含，无需额外操作
   - 选"本地" + 有 `_conflictFields` → 仅替换冲突字段（字段级）
   - 选"本地" + 无 `_conflictFields` → 整条替换（fallback）
5. `_applyDataToApp` → `_cacheToLocal` → `saveToBackend`

### 冲突项数据结构

```javascript
{
  id: string,          // 维度/版本 id 或 '_teams'
  cat: 'dimension' | 'version' | 'other',
  label: string,       // 显示名称
  choice: 'local' | 'server',
  _ll: string[],       // 本地差异描述行
  _sl: string[],       // 服务器差异描述行
  _local: object,      // 本地原始对象
  _server: object,     // 服务器原始对象
  _localOnly: boolean, // 仅本地存在
  _serverOnly: boolean,// 仅服务器存在
  _conflictFields: string[],  // 冲突字段名（由 _smartMerge 注入）
  _autoMerged: object         // 已自动解决的字段值（由 _smartMerge 注入）
}
```

## 同步基线

| localStorage Key | 用途 |
|------------------|------|
| `pm-sync-base` | 上次同步的完整数据快照，三方合并的 base |
| `pm-sync-meta` | `{ lastSyncLocalSavedAt, lastSyncServerSavedAt, updatedAt }`，判断变化 |
| `pm-pending-conflict` | 值为 '1' 表示有未解决冲突 |
| `gamedev-pm-data-v6` | 本地数据主存储 |
| `pm-system-data` | 本地数据副本 |

**更新时机**：`_markSynced` 时调用 `_saveSyncBase`

## 差异比较

`_normForCmp(obj)` 规范化对象后 JSON.stringify 比较。规范化：
- 删除 `metadata.locked`、空值、空数组
- 删除 `weekIds`（空时）、`features`（空时）
- 删除 `locked:false`、`description` 等噪音字段

## 数据导入（两阶段）

### 阶段一：`importJSON(inputElement, appInstance)`

1. `FileReader.readAsText` 解析 JSON
2. 兼容 `data.data` / `data.payload` 等备份结构
3. `normalizeArray` 处理 versions/teams/users
4. 构建 beforeState / afterState 预览
5. 显示 `importPreviewModal`，用户确认后调用阶段二

### 阶段二：`_executeImport(appRef, payload, importedVersions, importedTeams, importedUsers)`

1. 写入 versions/teams/users/operationMatrix
2. 处理 researchProjects/performanceRecords/taskTemplates 等
3. 写入 localStorage（releaseChecklistConfig/publishedPlans/robotConfigs）
4. 重置视图状态，初始化 OperationsManager/VersionManager
5. `saveData()` → 关闭弹窗 → render → Toast

## 修改注意事项

- 改合并逻辑时必须同时考虑 `_smartMerge` 和 `_doConflictMerge` 两处
- `_buildConflictItems` 的返回仅用于展示，不包含三方上下文
- 三方上下文（`_conflictFields` / `_autoMerged`）在 `_doConflictMerge` 中从 smartConflictMap 注入
- 死代码 `_applyConflictChoices` / `_mergeByChoices` 未使用，勿调用
- 延迟冲突处理（`_conflictPending`）会在切换 phase 时触发检查
