# 票 01：群聊数据模型与回合 API

Status: ready-for-agent

Spec: `.scratch/group-chat/spec.md`

## 任务

1. `backend/src/eidolon/group_chat.py`：群消息表（speaker 空＝制作人，kind: say/topic_open/topic_end 等，与 outings 消息表同构但独立建表）+ 每用户群状态（当前活跃话题：发起人、已发言角色序列、回合数；无活跃话题＝null）。建/读/推进/收口接口，走 store 现有迁移与事务方式，注册进 database.py 的用户数据清单（删用户时随之删）。
2. `POST /api/group/turns`：制作人回合，SSE 协议与外出回合一致（user → speaker → delta… → done/error），回应人抽取复用 `group_turns.pick_speakers` + `mentioned_in`（不 @ 抽 1–2 位）。非法状态（群关着）409/404 与外出同款处理。
3. `GET /api/group`：时间线（最近 N 条，带说话者名字/颜色）+ 当前话题状态 + 未读判定所需字段。
4. `LiveConfig.GroupChatSettings`（enabled / topics_per_day / max_turns / speaker_mode）+ admin_config_api 输入模型 + adminConfig.ts 管理台卡 + zh.ts 文案（照外出票的 review 修复那样一处不漏）。

## 验收

- pytest：消息建读、话题状态流转、@ 独占/随机 1–2、SSE 流、删用户清理；ruff + pyright 过。
- 管理台「群聊」卡可改四个设置。

## Comments
