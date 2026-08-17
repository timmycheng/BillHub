---
name: issue-writer
description: Use when the user describes a requirement or bug in one sentence of plain language and wants it turned into a standard GitHub Issue (提需求、报 bug、提个 issue、生成 issue、一句话需求). Create the issue via gh issue create with the repo's standard template fields and labels, and do not start development until the user confirms.
---

# Issue Writer — 一句话需求 → 标准 GitHub Issue

把用户的一句话需求/缺陷转换成仓库标准格式的 GitHub Issue，走 BillHub 的 Issues 驱动开发流程。

## 工作步骤

1. **理解与澄清**：先读代码/界面（grep、read 模板或路由）搞清楚现状，需求模糊时用 `question` 工具澄清 1~2 个关键点（不要超过 2 个），其余按合理默认推断并在 Issue 里写明。
2. **选模板**：
   - 需求/改进 → 功能需求（打 `功能` 标签，标题 `[功能] ...`）
   - 缺陷 → Bug 报告（打 `bug` 标签，标题 `[Bug] ...`）
   - 现状行为明显异常且影响用户 → Bug；优化/新增能力 → 功能
3. **写内容**（标题简洁说明行为，不要含糊）：
   - 功能需求：`### 背景与目的`（解决什么问题）、`### 功能描述`（期望行为，列出要点）、`### 验收标准`（可测试的完成标准，便于冒烟测试覆盖）
   - Bug 报告：`### 复现步骤`、`### 期望行为`、`### 实际行为`、`### 版本`（查 pyproject.toml 当前版本）
4. **创建**：`gh issue create --title ... --label <功能|bug> --body <正文>`，用 PowerShell 字面量 here-string（`@'...'@`）传多行正文，避免转义问题。
5. **报告**：把 Issue 链接和摘要给用户。**不要**自动评论 `/dev` 或开始开发，等用户确认。

## 注意事项

- 文案用中文；验收标准尽量具体（页面、行为、边界），别写「体验更好」这类不可测的话
- 用户同时列多条需求时，每条建一个独立 Issue
- 创建后确认 Issue 已自动打上「待开发」标签；若没有，说明 issue-triage workflow 有问题，顺手修复并告知用户
