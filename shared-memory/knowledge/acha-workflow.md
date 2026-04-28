# 阿茶策划工作信息处理逻辑与工具坐标

来源：2026-04-26 孙懿与阿茶对齐

## 策划工作信息 6 步闭环

1. **运营矩阵全/够/准**：检查运营矩阵维度标签，提醒→确认。
2. **维度标签分配到版本**：脚本巡检→确认后执行分配。
3. **临近版本的维护流+排期流 Feature 是否已确认**：提醒→确认。
   - 以上 3 步完成 = "组版本"完成。
4. **策划工作均衡分配**（时间+人维度）= 保交付。
5. **策划前置设计**：在周计划手动添加。
6. **需求池、设计到落地**：阿茶不需要关心。

## OPS 维度标签版本分配规则

- `eligible` 判定：发版日 < 开始日才算 eligible（严格，不放宽）。
- 边界情况属于上月口径的，按老大指令不管。
- 数据位置：`operation_matrices` 表，`id="global"`，JSON 路径 `data.dimensionValues[]`。
- 已分配版本追踪：`metadata.sentToVersions[]`，空/缺失 = 未分配。

## OPS 巡检脚本

- 路径：`D:/hermes/acha/scripts/ops_inspector.py`
- 用法：`py ops_inspector.py --month N`，不传则查近三个月。
- 输出：详细报告 + 钉钉播报两种格式。
- 注意：中文内容写 UTF-8 文件避免 GBK 编码崩溃。

## 钉钉 Webhook 集成

- `version_digest_pmo` 机器人 keyword filter：消息标题或正文中必须包含 **"小秘书提醒"** 五个字，否则 errcode 310000。

## PmSystem 认证

- 后端地址：`http://192.168.20.160:8112/`
- Auth：Bearer `dev_token`（debug bypass）。
- Cookie auth 不工作。
