# 票 01：后端互动动作管线

Status: ready-for-agent

Spec: `.scratch/interactions/spec.md`

## 任务

1. 新建 `backend/src/eidolon/interactions.py`：
   - 动作目录：摸摸头、拥抱、亲吻、牵手、击掌、戳脸颊、递零食、整理头发、整理衣领。每个含 id、中文名、recommended_tier（对应 `affinity.py` 的 tier 命名）、affinity_delta、LLM prompt 片段（描述动作场景，供注入 system prompt）。
   - 提供「当前 tier 相对 recommended_tier」的反应指令生成（低于→抗拒/尴尬/敷衍且好感零或微负；达到/超过→良好反应）。
   - 腻烦判定：根据会话最近消息里同 interaction 出现次数给衰减系数与 prompt 提示（「她今天已经被摸过好几次头了」）。
2. `POST /api/conversations/{id}/turns` 请求体新增可选 `interaction_id`（找 app.py:690 的 handler 与对应 request model）；非法 id 报 4xx。
3. `engine.py` 的 turn 流程接入：注入动作 prompt 片段 + 反应指令；落库的消息记录 interaction（Message 模型/store 需要能持久化并回放该标记）。好感评判沿既有 judge 链路，把 affinity_delta 与腻烦系数传进去或作为 prompt 上下文（看 affinity.py 现有接缝，选改动最小的）。
4. `GET` 会话历史时 interaction 消息带动作信息返回给前端。

## 验收

- pytest：目录默认值、推荐档位判定（低于/等于/高于）、腻烦衰减、非法 interaction_id 4xx、带 interaction_id 的 turn 完整走通（mock LLM，按现有 conversations 测试风格）。
- `sh scripts/affected-tests.sh <基点>` 通过。

## Comments
