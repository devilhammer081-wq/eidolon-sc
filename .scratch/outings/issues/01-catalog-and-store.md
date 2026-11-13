# 票 01：外出地点目录与数据模型

Status: ready-for-agent

Spec: `.scratch/outings/spec.md`

## 任务

1. `characters/outings.toml`（新建，风格对齐 `characters/gifts.toml`）：四个地点——电影院、商场、游乐场、海边。每个含 id、中文名、场景描述（喂 LLM 的地点设定）、事件池（每地 3–4 个事件，每个事件一句触发语 + LLM 场景提示）、好感倾向提示。加载模块 `backend/src/eidolon/outing_catalog.py`（对齐 `gift_catalog.py` 的加载与缓存方式）。
2. store 新表（走 `store.py`/`database.py` 现有迁移方式）：
   - `outings`：id、user_id、kind（solo/outing）、location_id、participant character ids（solo 为空）、status（opening/ongoing/ended）、created_at、ended_at。
   - 外出消息表：outing_id、speaker（character id，空＝制作人）、text、kind（say/event/opening/ending）、created_at。表结构按 spec 要求考虑群聊复用（speaker 语义通用）。
3. 好感结算所需的关联：外出结束要在 affinity 上结算（本票只留结算所需的数据接口，结算逻辑在票 03）。
4. 顺手：GLOSSARY.md 加「外出 (Outing)」词条（含「独自外出」「偶遇」语义；分次提交注意 GLOSSARY.md 工作区里可能有别人未提交的改动，提交时只挑本票 hunk——上游分支干净，无此顾虑）。

## 验收

- pytest：目录加载（四地点、事件数）、外出与消息的建/读/状态流转。
- ruff + pyright 过。

## Comments
