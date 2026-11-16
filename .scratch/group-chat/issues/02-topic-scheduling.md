# 票 02：话题调度与角色接话

Status: done

Spec: `.scratch/group-chat/spec.md`

Blocked by: 01

## 任务

1. `backend/src/eidolon/group_topics.py`：每用户每日 `topics_per_day` 次开话题（调度节奏与夜间推迟对齐 `reach_outs.py` 的做法，挂进它或 moments 的每日任务接缝）。发起人抽取：`random` 均匀 / `relation_weighted` 按与制作人的好感。
2. 话题推进：开场后由角色逐回合接话（每回合 1 位；`relation_weighted` 时复用 `pick_speakers` 权重——与已发言角色的关系 + 好感 + 底噪；同角色不连说）。推进的触发：进群/刷新时惰性补齐（搭话式：落后了就推进到当前时间应到的程度），不做后台常驻任务。
3. prompt：复用 `speaker_prompt` 组装思路，场景换成群聊设定（283事务所、谁在线、话题进行中）；低好感/冷淡角色注入「可以敷衍、已读不回」指令（prompt 层，非硬规则）。
4. 收口：到 `max_turns` 或 LLM 判定自然收尾 → topic_end 消息，话题状态清空。
5. 题材：开场内容来自角色日常 facts / 当天近况（`moment_draws` 的题材思路，读它的接缝）。

## 验收

- [x] pytest：每日上限、两种模式的发起人/接话人分布（FakeRandom 断言权重路径）、max_turns 收口、同一角色不连续接话、低好感 prompt 注入。
- [x] ruff + pyright 过。

## Comments

### 实现说明（票 02）

主会话实现（实现子代理受周限额所限）。`backend/src/eidolon/group_topics.py`：

- **惰性推进**：`GroupChat.shown()`（即 `GET /api/group`）先 `catch_up` 再读——无后台常驻任务。进行中话题按 `FOLLOW_SPACING`（8 分钟/回合）补齐落后回合；无话题时，当日（按北京时间划天，对齐全站配额）已开数 < `topics_per_day` 且距上次开题 ≥ `TOPIC_GAP`（4 小时）才开新题。单次补齐最多 `CATCH_UP_AT_MOST`（4 回合），防止用户回来面对洪流。
- **选人**：`speaker_mode=random` 均匀抽（`random(n)`）；`relation_weighted` 用 `speaker_weight`（好感档位 + 底噪 + 关系步进，复用 group_turns）；接话人排除「上一句刚说的角色」（两人群即自动轮替）。
- **prompt**：复用 `speaker_prompt`，场景固定 `GROUP_SCENE`，指令分开题/接话两种；低好感（cold/distant）追加「可简短敷衍」指令（prompt 层，非硬规则）。模型失败或写空 → 静默终止本次补齐，已落的保留，运行记录记 failed。
- **收口**到 `max_turns` 落一条 `WENT_QUIET` 静场行（topic_end）。发题/接话每次走独立 lease + 活动记录（kind="group"）。

判断题（未做，记录）：
- 「LLM 判定自然收尾」没做：只按 max_turns 硬收口（外出票 03 的审查对同类缺口同样记过）。
- 开题的「题材来自 facts/近况」靠人设 sheet + 开题指令自由发挥，没接 `moment_draws` 的题材管线。
- 夜间推迟（reach_outs 那种安静时段）没做：`TOPIC_GAP`/`FOLLOW_SPACING` 全天适用。
- `_world_prompt` 第三处近似重复（solo/group_outings/group_topics 各一份），留给审查统一。
