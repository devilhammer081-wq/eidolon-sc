# 票 01：后端互动动作管线

Status: done

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

- [x] pytest：目录默认值、推荐档位判定（低于/等于/高于）、腻烦衰减、非法 interaction_id 4xx、带 interaction_id 的 turn 完整走通（mock LLM，按现有 conversations 测试风格）。
- [x] `sh scripts/affected-tests.sh <基点>` 通过。

## Comments

### 实现说明（票 01）

接口与模块：

- 新增 `backend/src/eidolon/interactions.py`：动作目录 `CATALOG`/`BY_ID`（id、中文名、emoji、`acted` 动作叙述行、`recommended_tier`、`affinity_delta`、scene prompt 片段）、`reaches`（当前档 vs 推荐档：below/at/above）、`turn_lines`（scene + 反应指令 + 腻烦提示）、`taken_before`（最近 `WEARINESS_TURNS=8` 条用户消息里同动作计数）、`decay`（`0.5^n` 衰减）、`affinity_step`、`shown()`。
- `POST /api/conversations/{id}/turns`：`TurnInput` 新增可选 `interaction_id`，`text` 改为可缺省；未知 id 报 422「没有这个互动」；只带 `interaction_id` 不带 text 时，用户消息文本用动作的 `acted` 行（如「（轻轻摸了摸她的头。）」）。动作对象经 `engine.turn(interaction=...)` 传入。
- 新增 `GET /api/interactions`：返回目录（id、name、emoji、recommended_tier），供菜单与推荐关系标签。
- `engine.py`：turn 注入动作 prompt（scene + 按档位的反应指令 + 腻烦提示）到逐 turn 变化的 system message 最前；落库时用户消息带 `interaction_id`；好感步长在 `judged.step >= 0` 且非 out_of_line 时用 `affinity_step` 覆盖（低于推荐档→0.0；达到/超过→`delta * 0.5^重复次数`）。
- `affinity.py`：`Affinities.change` 新增可选 `step_override`（替代 judge 的 step+considerate_step，日上限照旧适用）。
- `store.py`：`messages` 表新增 `interaction_id TEXT` 列（含旧库迁移 `_add_missing_columns`）；`Message` 新增 `interaction_id` 字段，读回（`_MESSAGE_COLUMNS`/`_message`）与写入（`_insert_message`/`add_turn`）都带上；`Message.shown()` 因 `asdict` 自动带出，GET 会话历史即返回该标记。数据包导出走 `m.*`，自动包含。

判断题（judgement calls）：

- 好感实现选了「步长覆盖」而不是只给 prompt 上下文：judge 看到的只是动作叙述行，按档位/腻烦的确定性数值没法靠 judge 猜；故 judge 链路照常跑（out_of_line、hurt、ends/warns 判定不变），只在「动作本会加分」时把步长换成动作自己的（低于推荐档为 0.0）。会拉低好感的判断（out of line 等）不被覆盖。
- 低于推荐档选「好感收益为零」而非微负（spec 允许两者）；角色抗拒/尴尬由 prompt 反应指令表现。
- 既有 `GAINS_PER_DAY=0.6` 日上限对互动动作照常生效（防刷更严，测试里第三个动作被截到剩余额度）。
- 腻烦提示从同一动作重复第 3 次（已出现 2 次）起注入；衰减每次 ×0.5，窗口为最近 8 条用户消息。
- 目录未进 `live_config.py`：spec 说首版可只做数据层默认值，admin 可调留待后续票。
- 测试跑法：本机没装 `uv`，用 `backend/.venv` 的 pytest/ruff/pyright 直跑（pyright 需 `--pythonpath .venv/Scripts/python.exe`）；`affected-tests.sh` 用了临时 uv shim 跑通。
