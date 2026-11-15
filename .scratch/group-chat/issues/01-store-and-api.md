# 票 01：群聊数据模型与回合 API

Status: done

Spec: `.scratch/group-chat/spec.md`

## 任务

1. `backend/src/eidolon/group_chat.py`：群消息表（speaker 空＝制作人，kind: say/topic_open/topic_end 等，与 outings 消息表同构但独立建表）+ 每用户群状态（当前活跃话题：发起人、已发言角色序列、回合数；无活跃话题＝null）。建/读/推进/收口接口，走 store 现有迁移与事务方式，注册进 database.py 的用户数据清单（删用户时随之删）。
2. `POST /api/group/turns`：制作人回合，SSE 协议与外出回合一致（user → speaker → delta… → done/error），回应人抽取复用 `group_turns.pick_speakers` + `mentioned_in`（不 @ 抽 1–2 位）。非法状态（群关着）409/404 与外出同款处理。
3. `GET /api/group`：时间线（最近 N 条，带说话者名字/颜色）+ 当前话题状态 + 未读判定所需字段。
4. `LiveConfig.GroupChatSettings`（enabled / topics_per_day / max_turns / speaker_mode）+ admin_config_api 输入模型 + adminConfig.ts 管理台卡 + zh.ts 文案（照外出票的 review 修复那样一处不漏）。

## 验收

- [x] pytest：消息建读、话题状态流转、@ 独占/随机 1–2、SSE 流、删用户清理；ruff + pyright 过。
- [x] 管理台「群聊」卡可改四个设置（部分 PUT 也行）。

## Comments

### 实现说明（票 01）

由两位实现者接力：前一位被周限额打断（留下 group_chat.py / group_chat_api.py / test_group_chat.py 主体与管理台卡），主会话修复收尾。最终状态：

- `group_chat.py`：`group_messages`（speaker 空＝制作人，kind say/topic_open/topic_end；与外出消息表同构独立建表）+ `group_state`（opener/spoken/turns 当前话题 + read_at 已读时刻，CHECK 保证三者同 NULL）。`GroupChats`：say/open_topic/end_topic/timeline/state/mark_read/unread。注册进 database.py 用户数据清单（删用户随之删）。
- `group_chat_api.py` + app.py 接线：`GET /api/group`（时间线 + 话题状态，读取即 mark_read）、`GET /api/group/unseen`、`POST /api/group/turns`（SSE：user→speaker→delta…→done/error，与外出同协议；@ 用 `mentioned_in` 独占，否则 `pick_speakers` 抽 1–2，`speaker_mode=random` 时均匀抽 `_uniform`）。群关着统一 409「群聊没有开放」。
- LiveConfig `_GroupChat`（enabled 默认开 / topics_per_day / max_turns / speaker_mode ∈ {random, relation_weighted}，默认 weighted）+ `GroupChatInput`（四字段全可选）+ adminConfig.ts「群聊」卡 + zh.ts。
- 主会话修复（中断稿的 bug）：部分 PUT 时 `enabled:None` 未剔除（`_change` 名单补 enabled）；`_unread` 在 read_at 为 NULL 时拿 None 比较（SQL NULL 比较永不命中）→ 未读永远 False；测试侧修了漏 settings 参数×2、时间戳同刻、名字当 id×2、FakeLLM 脚本次序、人设文件传 None。

### 票 01 交接（给票 02/03）

- `GET /api/group` → `{"messages":[{id,speaker,kind,text,created_at}], "topic": {"opener","spoken":[ids],"turns"} | null, "characters": [{id,name,color}]}`（characters 为当前配置里全部角色，供前端名字着色；说话者若已不在配置里 messages 里只有 id，前端自会兜底）。
- `POST /api/group/turns` SSE 事件：`user{text}`、`speaker{character_id,name,color}`、`delta{speaker,text}`、`done{messages}`、`error{message}`。409＝群关着；空白/超长走 error 事件（「没有收到要说的话。」/长度提示）。
- 票 02 的调度请走 `GroupChats.open_topic/say/end_topic`；一次只允许一个话题（open_topic 在有话题时 ValueError）。
- `records(settings)`（test_solo_outings）看运行记录：群聊回合记 kind="group"。
