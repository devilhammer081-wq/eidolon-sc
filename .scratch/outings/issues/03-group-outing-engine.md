# 票 03：同行外出多角色回合引擎与结算

Status: ready-for-agent

Spec: `.scratch/outings/spec.md`

Blocked by: 01

## 任务

1. 新模块 `backend/src/eidolon/group_turns.py`（多角色回合引擎，群聊复用的接缝）：
   - `pick_speakers(candidates, context, k)`：从候选角色里按权重抽 1–2 位回应者。权重＝与制作人的好感度（affinity tier）+ 与话题中已发言角色的关系远近（moments.py `relations()` 的关系图）+ 随机底噪；被 @ 的角色独占回应。注意：relation 图读取若重，做一次性快照传入。
   - 多角色 prompt 组装：会话最近消息（带说话者名字/颜色标记）、各候选人设 sheet 的相关段、相互关系简述、地点场景。产出下一条发言（结构化：说话者 + 文本，可流式）。
2. `POST /api/outings`（发起同行：角色 1–3 + 地点）→ 生成开场（场景描写 + 各角色到场反应，逐角色或整段，v1 整段即可但消息按说话者落库）→ ongoing。
3. `POST /api/outings/{id}/turns`：制作人的话（支持 @某角色，只她回应；不 @ 随机 1–2 位）。`POST /api/outings/{id}/events`：触发地点事件 → LLM 生成事件场景 + 相关角色反应（事件指定参与角色或按权重抽）。
4. `POST /api/outings/{id}/end`：结算——每位同行角色好感度变化（地点偏好 + 事件走向 + 事件提示的好感倾向，走现有 Affinities 接口），同行记忆写入 memory.py 共享记忆（同一次外出的她们都记得），状态 ended。
5. LiveConfig：`OutingSettings`（encounter_chance 在票 02 已建则沿用；补 responders_max 等）。

## 验收

- pytest：权重选人（好感/关系/随机底噪、@ 独占）、开场/回合/事件/结束的 HTTP 流（mock LLM，仿 test_interactions）、结算与记忆落库、状态流转。
- ruff + pyright 过。

## Comments
