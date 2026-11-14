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

### 票 01 交接

- 存储实例已在 assembly 构造：`Backend.outings`（`backend/src/eidolon/outings.py`）。同行流程照它的形状走：`add(user, "outing", location, participants(1–3), now)`（建为 opening）→ 开场逐条 `message(kind="opening", speaker=<角色>)` → `begin`（→ongoing）→ 回合 `message(kind="say")`、事件 `message(kind="event", event=<目录事件 id>)` + 角色反应 say 行 → `end(user, id, now)`。
- 结算读法：`outings.outing()`（participants/location）+ `outings.messages()`；事件行的 `event` 列是 `characters/outings.toml` 里的事件 id，回 `Backend.outing_catalog[location_id].event(id)` 拿事件的 affinity 提示，地点级提示在 `OutingLocation.affinity`。这两处就是票 01 留的结算数据接口。
- 消息表已按群聊复用设计（`speaker` 空＝制作人、语义通用）：功能二群聊可以直接用这张表/照这个形态建，别另起一套时以它为准。
- 写操作越权/已结束抛 `OutingGone`（「这次外出已经结束了」），API 层接成 404/409；`begin` 只能从 opening 进、`end` 只能一次，重复调同样抛。
- LiveConfig 的 `OutingSettings`（encounter_chance、responders_max 等）本票没建，按你的任务 2/5 自己加。

### 票 02 交接

- `OutingSettings` 已经建好（config.py + live_config.py `_Outings`，`LiveConfig.outings` 读）：`encounter_chance`（默认 0.3）就是沿用它；补 `responders_max` 等字段在同一 dataclass + `_Outings.fields`/`candidate`/`env` 里加，`admin_config_api.py` 的 `OutingsInput` 同步加字段（漏了后者管理台改不了，PUT 一律 404）。
- `GET /api/outings` 和它的 `_shown`（outings_api.py）对 solo/outing 两种 kind 通用，你建的同行 outing 会自动进历史列表；返回里要给同行加的字段（比如参与角色详情）就在 `_shown` 里加。
- 抽签接缝别硬复用：solo_outings 里「按权重抽一位」是偶遇专用（好感档位 + place_likes），和你要写的 `group_turns.pick_speakers`（好感 + relations 关系图 + 底噪）不是一个东西；真要共享等形状趋同再说。
- 同行的开场不是搭话：照票 01 交接的 `message(kind="opening", speaker=…)` 落消息表，别学偶遇的 `Store.add_reach_out`（那是偶遇把新对话开起来的做法，见 `outing_prompt.encounter_prompt`）。
