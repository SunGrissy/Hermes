# 开机 / 登录编排（四棒）

## 根因说明（为什么之前满满、小马起不来）

- `DingTalk-Daemon`、`PM-Bootstrap` 若在 **系统开机（ONSTART）** 阶段跑，常见身份是 **SYSTEM**。
- `OpenClaw\gateway.cmd` / `OpenClaw2\gateway.cmd` 使用 **`C:\Users\TU\AppData\Roaming\npm\...`** 下的 `openclaw`，SYSTEM **往往读不到或起不来**。
- `boot-phase2-manman.ps1` 若等不到 `18789 /health` 会直接 **抛错退出**，满满也不会起。

因此：**钉钉仍可 ONSTART；满满 + 小马 + PM 改为用户登录后 ONLOGON 一条链**（`boot-postlogon-chain.ps1`）。

## 注册（管理员）

- 双击（管理员）：`register-startup-chain.cmd`
- 或管理员 PowerShell：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "D:\MyAgents\tools\startup-orchestration\register-startup-chain.ps1"
```

## 日志

每次登录链跑完会在 `logs\postlogon-chain-*.log` 留一份 Transcript。

## 任务一览（注册后）

| 任务名 | 触发 | 说明 |
|--------|------|------|
| DingTalk-Daemon | ONSTART +15s | 链首 |
| Legion-PostLogon-Bootstrap | ONLOGON +1min | 18789 + 满满 + 18790 + PM(quick_start 1/2/3/5) |
| OpenClaw Gateway | 已禁用 | 避免与链内 18789 重复 |
