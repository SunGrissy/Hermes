# Hermes Agent 与 Multica / 钉钉 / Cursor 协作流程（规划稿）

> **状态**：规划与流程约定；Hermes 为可选组件，落地以实际安装与内网合规评估为准。  
> **日期**：2026-04-19  
> **依据**：Multica 接入设计 `2026-04-18-multica-integration-design.md`（方案 A、钉钉桥、Issue 真相源）；会话结论与 [Hermes Agent 官网](https://hermes-agent.nousresearch.com)、[GitHub 仓库](https://github.com/NousResearch/hermes-agent) 公开能力描述。

---

## 1. 文档目的

说明在 **已接入 Multica（multica.ai）**、**钉钉 Stream 派单桥**（`tools/multica-dingtalk-bridge`）、**PC 端 Cursor + CLI 为主力、Cursor Cloud Agent 为备用** 的前提下，若引入 **Hermes Agent**，协作面与执行面如何分工、端到端流程如何运转，以及与 **Issue 拆单**（见 Multica spec **§7.1**）的衔接。

---

## 2. 能力定位（谁做什么）

| 组件 | 定位 | 不承担 |
|------|------|--------|
| **Multica（Issue）** | 队列与协作 **真相源**：状态、指派、评论时间线、多 Runtime 认领 | 不替代 pm-system 等业务系统数据；不存放密钥明文 |
| **钉钉 + 派单桥** | 碎片 **入站派单**（`#派单` → 本机 `multica issue create`）、可选 **出站强提醒** | 不作为代码/密钥真相源；不替代 Multica 写状态 |
| **PC Cursor + CLI** | **主力交付**：实现、自测、PR、与仓库 Skill/门禁一致 | 不必 7×24 承担全部定时巡检 |
| **Cursor Cloud Agent** | 本机不可用或需隔离时的 **备用 Runtime** | 不定义为默认主路径 |
| **Hermes Agent**（若引入） | 常驻 **网关 / 定时编排 / 子 Agent 沙箱执行**：NL cron、并行子任务、简报；可选读板摘要 | 不抢 Multica 的「关单权威」；**不默认**无授权自动批量建 Issue |
| **Git + WORK_LOG** | 工程交付与记录互链（关单摘要 + `Multica: #…`） | — |

**Hermes 公开能力摘要**（以官网为准）：多通道入口（Telegram、Discord、Slack 等）、持久记忆与 skills 复利、自然语言定时任务、隔离子 Agent 与多类执行后端（本地 / Docker / SSH 等）、浏览器与多模态相关工具链。

**与钉钉的关系**：Hermes **原生通道列表不含钉钉**。若要从钉钉驱动 Hermes，须 **自建桥**（验签、allowlist、与现有派单桥并列或合并），或保留 **钉钉 → Multica**、**Hermes → 其他已支持 IM / CLI** 的分工。

---

## 3. Issue 拆单与 Hermes 的边界

拆单原则以 Multica spec **§7.1** 为准，此处只固定与 Hermes 的接口：

- **拆不拆**：由 **任务复杂度 + 代码影响面** 决定；Owner 最终负责；执行中可补拆并 @Owner。
- **Hermes**：可提供 **拆单建议、验收清单、风险闸门**；若团队未显式打开策略，**不**自动在 Multica 上批量创建子 Issue，避免噪声与责任模糊。

---

## 4. 端到端泳道（日常工单）

**说明**：Cloud Agent 仅在降级路径出现；Hermes 为可选「编排卫星」。

```mermaid
sequenceDiagram
    autonumber
    box rgba(0,0,0,0.04) 触达与入队
        participant 人 as 制作人/伙伴
        participant 钉 as 钉钉(IM)
        participant 桥 as 派单桥(Stream)
    end
    box rgba(0,0,0,0.04) 队列真相源
        participant MC as Multica Cloud<br/>(Issue/评论/状态)
        participant MZ as 本机 multica<br/>CLI/Daemon
    end
    box rgba(0,0,0,0.04) 常驻编排(可选Hermes)
        participant HM as Hermes Gateway
    end
    box rgba(0,0,0,0.04) 交付
        participant CU as PC Cursor + CLI
        participant CC as Cursor Cloud Agent
        participant Git as Git/PR/WORK_LOG
    end

    人->>钉: #派单 + 标题/DoD
    钉->>桥: Stream 收消息
    桥->>MZ: multica issue create
    MZ->>MC: Issue 创建/更新

    Note over MC,MZ: 认领/指派到 Runtime

    MC->>MZ: 下发到本机
    MZ->>CU: 工作上下文

    opt Hermes 编排卫星
        HM->>MC: 只读:阻塞/标签视图
        HM->>人: 简报(钉钉或其它通道)
        HM->>CU: 验收清单/风险说明
    end

    loop 执行与同步
        CU->>Git: 分支/PR
        CU->>MC: 评论与 artifact
    end

    opt 子Agent降上下文成本
        CU->>HM: 委派子任务
        HM->>HM: 沙箱内脚本/检查
        HM-->>CU: 结构化结果
        CU->>MC: 汇总写入评论
    end

    alt 本机不可用
        MC->>CC: 备用 Runtime
        CC->>Git: PR/评论
        CC->>MC: 状态回写
    end

    人->>MC: 验收/关单
    MC->>钉: 可选出站通知
    人->>Git: WORK_LOG 互链 Issue
```

---

## 5. 端到端泳道（无人值守 / 定时）

适用于巡检、健康探针、周报素材、模板化「开单」等。

```mermaid
sequenceDiagram
    autonumber
    participant Cron as NL Cron/系统定时
    participant HM as Hermes Gateway
    participant SB as 执行后端<br/>(Docker/SSH/本地)
    participant MC as Multica
    participant MZ as multica CLI
    participant 钉 as 钉钉
    participant 人 as 队列Owner

    Cron->>HM: 触发计划任务
    HM->>SB: 沙箱内执行

    alt 需留痕为工单
        HM->>MZ: multica issue create(模板)
        MZ->>MC: 新建 Issue
        MC->>人: 板子上认领
    else 仅需通知
        HM->>钉: Webhook 摘要
    end

    opt 异常需决策
        HM->>MC: 评论@Owner + 证据
        HM->>钉: 强提醒
    end

    人->>MC: 认领后转入第4节主执行链
```

---

## 6. 技能与记忆（与仓库的衔接）

- **仓库正本**：`.cursor/skills/` 与 `.cursor/rules/` 仍为 **AgentX / Cursor 侧** 权威 Skill 与门禁文本；Multica spec 已明确 Multica **不替代** Skill 仓库。
- **Hermes** 若使用自带 skills / 记忆：团队需约定 **主库**（避免两套 drift），可选策略包括：仅 Hermes 存运行时缓存、重要流程回写 PR 到 `.cursor/skills`、或标明「Hermes 本地 skill 为实验」等。

---

## 7. 安全与合规（引入前必选项）

- **IM 控制面**：任何「对话即执行」必须有 **身份鉴权、命令 allowlist、危险操作二次确认、审计日志**。
- **数据驻留**：Multica 方案 A 下 Issue 正文可能出内网，与 Hermes 通道、模型调用叠加后须按 **Multica spec §3.1 / 方案 C 脱敏** 执行。
- **执行后端**：优先对不可信脚本使用 **Docker / SSH 隔离**，与主力开发机分离。

---

## 8. 参考链接

- Hermes 官网：<https://hermes-agent.nousresearch.com>  
- Hermes GitHub：<https://github.com/NousResearch/hermes-agent>  
- Multica：<https://multica.ai/app>  
- 本仓：`docs/superpowers/specs/2026-04-18-multica-integration-design.md`、`tools/multica-dingtalk-bridge/README.md`

---

## 9. 修订记录

| 日期 | 变更 |
|------|------|
| 2026-04-19 | 初版：定位表、拆单与 Hermes 边界、双泳道 Mermaid、技能与安全注意事项 |
