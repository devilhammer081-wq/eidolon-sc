# Spec: 283事务所群聊

Status: ready-for-agent

固定群聊「283事务所」：全体配置内角色 + 制作人一个群，角色每日自主开话题、互相接话；制作人随时插话。基于外出波建好的 `group_turns` 多角色接缝（pick_speakers / mentioned_in / parse_labelled / speaker_prompt），不另起一套。

## 决定（已与用户确认）

- 群名「283事务所」；头像定稿 A 版（`.scratch/temp/20261113/group-avatar-283-final-a.png`，拷入 `frontend/public/group/`）。
- 每位用户一个自己的群时间线（同朋友圈的私有时间线模式；不是全站一个群）。
- 制作人说话：不 @ 时随机 1–2 位回应（可用好感权重）；@ 某角色仅其回复（复用 `mentioned_in`）。
- 话题推进的两种选人模式（LiveConfig 可切）：`random`（均匀随机）或 `relation_weighted`（好感 + 与本话题已发言角色的关系远近加权，复用 `pick_speakers` 权重）。
- 每日开启话题次数 `topics_per_day`、每话题最多连续回合 `max_turns`（LiveConfig，管理台可改）。
- 制作人不在线时话题照常推进（搭话式：进群/刷新拉取，首版不做实时推送）。

## 行为

- 每日按 `topics_per_day` 由一位角色开新话题（发起人同样按模式抽：random 均匀、weighted 按与制作人的好感）；话题内容来自她的日常 facts / 近况（朋友圈 `moment_draws` 的题材思路），1 句开场。
- 接话：话题内其他角色按模式逐个接话（每回合 1 位，关系/好感加权时同 `pick_speakers`；同角色不连说），到 `max_turns` 或 LLM 判定自然收尾即停。低好感/冷淡角色偶尔敷衍或已读不回（prompt 指令，不是硬规则）。
- 制作人插话走普通回合：SSE 流（user → speaker → delta… → done），与外出会话同协议。
- 群聊入口固定在对话列表顶部（头像 + 名字 + 最新一条），未读话题有小红点。

## 技术方案（接缝）

- 新模块 `backend/src/eidolon/group_chat.py`：群状态（当前活跃话题：发起人、已发言角色与回合数、结束判定）+ 消息表（沿用外出消息表的形态：speaker 空＝制作人；本群自己的表，不与 outings 混表，但同构）。
- `group_topics.py`（暂名）：话题调度——每用户每日 `topics_per_day` 次（对齐 reach_outs/moments 的每日节奏与夜间推迟做法）；发起人/接话人的抽取复用 `group_turns`（relation_weighted）或均匀随机；话题开场与接话的 prompt 复用 `speaker_prompt` 的组装思路（场景换成群聊设定），低好感角色注入「已读不回/敷衍」指令。
- API：`GET /api/group`（时间线 + 当前话题状态）、`POST /api/group/turns`（制作人回合，SSE，同外出协议）。话题推进由后台每日任务/搭话式触发（`reach_outs.py` 的调度接缝），不需要前端专门调。
- LiveConfig：`GroupChatSettings`（enabled / topics_per_day / max_turns / speaker_mode: "random"|"relation_weighted"）+ 管理台卡（adminConfig pattern）。
- 前端：对话列表（`ConversationList.tsx`）顶部固定群入口；群聊页复用外出会话页的多角色气泡形态（`OutingSession` 的渲染抽出共用或仿写）；头像 `public/group/283.png`；未读状态进 nav 点或入口点。i18n 全进 `zh.ts`。

## Testing Decisions

- 后端：pytest——话题调度（每日上限、发起/接话权重、模式切换、max_turns 收口）、制作人回合 SSE（@ 独占/随机回应）、HTTP 流（mock LLM，仿 test_group_outings）。
- 前端：typecheck + vitest（入口、未读点、气泡渲染）。

## 验收

- 对话列表顶部有「283事务所」入口（A 版头像）。
- 每日出现 `topics_per_day` 个角色开的话题，话题内多角色按模式接话，到 max_turns 收口。
- 制作人插话：不 @ 随机 1–2 位回、@ 只该角色回；SSE 流式。
- 管理台能改群聊设置；用户侧可关（对齐 ReachOutsSettings 的用户开关模式，首版可只做数据层）。
