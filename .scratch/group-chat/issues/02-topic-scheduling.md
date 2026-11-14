# 票 02：话题调度与角色接话

Status: ready-for-agent

Spec: `.scratch/group-chat/spec.md`

Blocked by: 01

## 任务

1. `backend/src/eidolon/group_topics.py`：每用户每日 `topics_per_day` 次开话题（调度节奏与夜间推迟对齐 `reach_outs.py` 的做法，挂进它或 moments 的每日任务接缝）。发起人抽取：`random` 均匀 / `relation_weighted` 按与制作人的好感。
2. 话题推进：开场后由角色逐回合接话（每回合 1 位；`relation_weighted` 时复用 `pick_speakers` 权重——与已发言角色的关系 + 好感 + 底噪；同角色不连说）。推进的触发：进群/刷新时惰性补齐（搭话式：落后了就推进到当前时间应到的程度），不做后台常驻任务。
3. prompt：复用 `speaker_prompt` 组装思路，场景换成群聊设定（283事务所、谁在线、话题进行中）；低好感/冷淡角色注入「可以敷衍、已读不回」指令（prompt 层，非硬规则）。
4. 收口：到 `max_turns` 或 LLM 判定自然收尾 → topic_end 消息，话题状态清空。
5. 题材：开场内容来自角色日常 facts / 当天近况（`moment_draws` 的题材思路，读它的接缝）。

## 验收

- pytest：每日上限、两种模式的发起人/接话人分布（FakeRandom 断言权重路径）、max_turns 收口、同一角色不连续接话、低好感 prompt 注入。
- ruff + pyright 过。

## Comments
