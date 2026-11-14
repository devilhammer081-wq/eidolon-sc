# 票 03：同行外出多角色回合引擎与结算

Status: done

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

- [x] pytest：权重选人（好感/关系/随机底噪、@ 独占）、开场/回合/事件/结束的 HTTP 流（mock LLM，仿 test_interactions）、结算与记忆落库、状态流转。
- [x] ruff + pyright 过。

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

### 实现说明（票 03）

由两位实现者接力完成：前一位被使用限额打断，留下 group_turns.py / group_outings.py / test_group_outings.py 的主体；后一位（主会话）修复并收尾。最终状态：

- `group_turns.py`（多角色引擎，群聊复用接缝）：`Candidate`（角色 + 好感档位 + relations 快照）；`pick_speakers`（逐个不放回抽取，权重＝档位起点 + 全员底噪 AFFINITY_BASE=10 + 每个已发言且她认识的角色 RELATION_STEP=20）；`speaker_weight`；`mentioned_in`（@全名或 short_name，谁被 @ 谁独占）；`parse_labelled`（多角色整段输出的「名字：台词」解析）；`speaker_prompt`（单说话人 prompt：她的 sheet + 世界设定 + 在场者与关系 + 已发言 labelled 行 + 好感 tier 段）。
- `group_outings.py`：`start`（1–3 人 + 地点 → LLM 写开场场景与到场台词，labelled 落库 kind=opening）、`turn`（SSE 流：user → speaker → delta… → done；@ 独占，否则按 responders_max 抽 1–N 位）、`happen`（触发目录事件，落 kind=event 行 + 角色反应）、`end`（LLM 结算 JSON（各角色 level + 结束语）→ 事务内逐角色 `Affinities.change` + `Memories.remember`（共享记忆）→ kind=ending 行 → 状态 ended）。好感度关闭时不问模型、结算列表为空，但记忆照留。
- `outings_api.py`：四个路由；turns 走 SSE。`/events`、`/end` 也先过 `_standing`（别人的 404、已结束 409）——修复：中断稿漏了这两处的归属检查。
- LiveConfig：`OutingSettings` 增 `responders_max`（1–3，默认 2）；`admin_config_api.py` 的 `OutingsInput` 两字段均可选、`_change` 剔除未传字段（修复：中断稿必传 encounter_chance，单独 PUT responders_max 会 422）。
- 测试修复（中断稿的笔误）：@短名测试里「恋鐘」两处写成「恋鎘」；pick_speakers 的 count=2 写成期望只抽一位；affinity_of 直接拿 'producer' 查库（应先解析 users 表真实 id）。

### 票 03 交接（给票 04/05）

- `POST /api/outings` body `{"character_ids": [...1–3], "location_id": "cinema"}` → 201 `{"outing": _shown}`；`_shown` 含 `id/kind/location_id/location_name/participants[{character_id,character_name,color}]/status/created_at/ended_at/messages[{id,speaker(null=制作人),kind(opening|say|event|ending),text,event,at}]`。
- `POST /api/outings/{id}/turns` body `{"text"}` → SSE，事件形状同对话流但多 `speaker`（`{character_id,character_name,color}`，user 之后、delta 之前各一次）与 `delta {character_id, text}`；终态 `done {messages:[…落库行]}` 或 `error {message}`。
- `POST /api/outings/{id}/events` body `{"event_id"}` → `{"event":{id,trigger}, "messages":[…]}`（事件行 + 反应行，整段返回不流式）。
- `POST /api/outings/{id}/end` → `{"outing":_shown(ended), "settlement":[{character_id,character_name,change|null,affinity{tier,cooldown_until}}]}`；好感度关时 `settlement: []`。
- 404＝没有这次外出/不是他的；409＝已结束。空白/超长文本走 SSE error 事件。
