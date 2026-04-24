#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
动态记忆汇聚脚本
每日凌晨 2:00 执行，汇集 Hermes 和 OpenClaw 的记忆，生成报告
"""

import os
import sys
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

# 配置
SHARED_MEMORY_DIR = Path("D:/MyAgents/shared-memory")
HUB_DIR = SHARED_MEMORY_DIR / "hub"
KNOWLEDGE_DIR = SHARED_MEMORY_DIR / "knowledge"
PENDING_DIR = SHARED_MEMORY_DIR / "pending-upgrade"

HERMES_MEMORY_DIR = Path("D:/hermes/memories")
OPENCLAW_MEMORY_DB = Path("D:/OpenClaw/memory/main.sqlite")

# 确保目录存在
for d in [HUB_DIR, KNOWLEDGE_DIR, PENDING_DIR]:
    d.mkdir(parents=True, exist_ok=True)


def read_hermes_memories():
    """读取 Hermes 记忆"""
    memories = []
    for filename in ["MEMORY.md", "USER.md"]:
        filepath = HERMES_MEMORY_DIR / filename
        if filepath.exists():
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    memories.append({
                        "source": f"hermes/{filename}",
                        "content": content,
                        "timestamp": datetime.now().isoformat()
                    })
    return memories


def read_openclaw_memories():
    """读取 OpenClaw 记忆"""
    memories = []
    if not OPENCLAW_MEMORY_DB.exists():
        return memories
    
    try:
        conn = sqlite3.connect(str(OPENCLAW_MEMORY_DB))
        cursor = conn.cursor()
        
        # 读取 chunks 表
        cursor.execute(
            "SELECT id, text, updated_at FROM chunks ORDER BY updated_at DESC LIMIT 50"
        )
        rows = cursor.fetchall()
        
        for row in rows:
            if row[1]:  # text 不为空
                memories.append({
                    "source": "openclaw/memory",
                    "id": row[0],
                    "content": row[1],
                    "timestamp": datetime.fromtimestamp(row[2] / 1000).isoformat() if row[2] else None
                })
        
        conn.close()
    except Exception as e:
        print(f"[警告] 读取 OpenClaw 记忆失败: {e}")
    
    return memories


def load_last_hub():
    """加载上一次汇聚的内容，用于差异对比"""
    # 查找最近的 hub 文件
    hub_files = sorted(HUB_DIR.glob("*.md"), reverse=True)
    if hub_files:
        try:
            with open(hub_files[0], "r", encoding="utf-8") as f:
                return f.read()
        except:
            pass
    return ""


def classify_memory(content):
    """
对记忆进行分类：环境知识 / 普通记忆 / 升级候选
    
    返回: (category, reason)
    category: "knowledge" | "memory" | "upgrade_candidate"
    """
    content_lower = content.lower()
    
    # 环境知识关键词
    knowledge_keywords = [
        "windows", "git bash", "path", "port", "directory", "server",
        "daemon", "gateway", "pid", "taskkill", "node.exe"
    ]
    
    # 升级候选关键词（影响工作流或决策）
    upgrade_keywords = [
        "执行纪律", "必须", "禁止", "红线", "原则",
        "算法", "流程", "规范", "标准", "policy"
    ]
    
    # 检测环境知识
    if any(kw in content_lower for kw in knowledge_keywords):
        return "knowledge", "包含环境/工具/路径关键词"
    
    # 检测升级候选
    if any(kw in content_lower for kw in upgrade_keywords):
        return "upgrade_candidate", "影响工作流或决策模式"
    
    return "memory", "普通动态记忆"


def generate_hub_report(date_str, all_memories, new_memories, upgrade_candidates):
    """生成每日汇聚报告"""
    report_lines = [
        f"# 记忆汇聚报告 - {date_str}",
        "",
        "## 汇聚统计",
        f"- Hermes 记忆条目: {sum(1 for m in all_memories if m['source'].startswith('hermes/'))}",
        f"- OpenClaw 记忆条目: {sum(1 for m in all_memories if m['source'].startswith('openclaw/'))}",
        f"- 本次新增: {len(new_memories)}",
        f"- 升级候选: {len(upgrade_candidates)}",
        "",
        "## 新增记忆详情",
        ""
    ]
    
    for i, mem in enumerate(new_memories, 1):
        category, reason = classify_memory(mem["content"])
        report_lines.append(f"### {i}. [{mem['source']}] {category}")
        report_lines.append(f"分类原因: {reason}")
        report_lines.append("")
        # 截取内容预览
        preview = mem["content"][:500] + "..." if len(mem["content"]) > 500 else mem["content"]
        report_lines.append(preview)
        report_lines.append("")
    
    if not new_memories:
        report_lines.append("本次没有新增记忆。")
        report_lines.append("")
    
    if upgrade_candidates:
        report_lines.append("## 升级候选清单（待审核）")
        report_lines.append("")
        for i, mem in enumerate(upgrade_candidates, 1):
            report_lines.append(f"{i}. [{mem['source']}] {mem['content'][:100]}...")
        report_lines.append("")
        report_lines.append("审核方式: 确认后我将更新身份层配置。")
        report_lines.append("")
    
    return "\n".join(report_lines)


def main():
    today = datetime.now().strftime("%Y-%m-%d")
    today_file = HUB_DIR / f"{today}.md"
    
    print(f"[汇聚开始] {datetime.now().isoformat()}")
    
    # 1. 读取所有记忆
    hermes_memories = read_hermes_memories()
    openclaw_memories = read_openclaw_memories()
    all_memories = hermes_memories + openclaw_memories
    
    print(f"  Hermes 记忆: {len(hermes_memories)} 条")
    print(f"  OpenClaw 记忆: {len(openclaw_memories)} 条")
    
    # 2. 差异对比（简化版：假设每次 Hermes memories 变更都是新的）
    last_content = load_last_hub()
    new_memories = []
    upgrade_candidates = []
    
    for mem in all_memories:
        # 简化判断：如果内容不在上次报告中，则视为新增
        if mem["content"] and mem["content"][:200] not in last_content:
            new_memories.append(mem)
            category, reason = classify_memory(mem["content"])
            if category == "upgrade_candidate":
                upgrade_candidates.append(mem)
    
    print(f"  新增记忆: {len(new_memories)} 条")
    print(f"  升级候选: {len(upgrade_candidates)} 条")
    
    # 3. 生成报告
    report = generate_hub_report(today, all_memories, new_memories, upgrade_candidates)
    
    with open(today_file, "w", encoding="utf-8") as f:
        f.write(report)
    
    print(f"  报告已写入: {today_file}")
    
    # 4. 如果有升级候选，生成候选文件
    if upgrade_candidates:
        pending_file = PENDING_DIR / f"{today}-identity-proposal.md"
        with open(pending_file, "w", encoding="utf-8") as f:
            f.write(f"# 身份升级候选 - {today}\n\n")
            for i, mem in enumerate(upgrade_candidates, 1):
                f.write(f"## {i}. [{mem['source']}]\n\n")
                f.write(mem["content"])
                f.write("\n\n---\n\n")
        print(f"  候选文件已生成: {pending_file}")
    
    # 5. 输出结果供上层调用者使用
    result = {
        "date": today,
        "total_memories": len(all_memories),
        "new_memories": len(new_memories),
        "upgrade_candidates": len(upgrade_candidates),
        "report_path": str(today_file),
        "has_upgrade": len(upgrade_candidates) > 0
    }
    
    print(f"[汇聚完成] {json.dumps(result, ensure_ascii=False)}")
    return result


if __name__ == "__main__":
    main()
