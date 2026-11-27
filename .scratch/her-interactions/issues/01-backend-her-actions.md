# 票 01：后端——目录反向、prompt 注入、`<action>` 解析与落库

Status: ready-for-agent

Spec: `.scratch/her-interactions/spec.md`

## 任务

1. `interactions.py`：每个动作补 `her_scene`（她发起的 prompt 素材）与 `her_acted`（胶囊叙述行）；新增「按档位筛出她可主动做的动作」辅助函数（`tier` 达到推荐档位才可选）。
2. `reply_format.py`：`ReplyParser` 识别 `<action>id</action>`（回复里最多出现一个，放台词之外）；解析结果带出动作 id；`parse_said` 等入口兼容。解析后 id 不在「允许清单」里时由调用方忽略（解析层不做门控，只如实抽出）。
3. `engine.py`：回合组装时把她可主动做的动作清单（当前档位过滤后）写进指令，含频率约束（偶尔、一回合最多一个、不连续重复同一动作——参考最近消息里她做过的）；模型写出的 `<action>` 越级/未知时忽略。她的台词照常双语、照常交 judge，动作不加分（`interactions.affinity_step` 只在用户侧调用，不动）。
4. `store.py`：`_insert_message` 角色行落 `interaction_id`（列已存在）；`Message.shown()` 回放带出。
5. 测试：仿 `test_interactions`——目录反向文案齐全、prompt 只含允许动作、解析（正常/未知/无标签）、越级忽略、角色行落库回放、全链路 HTTP 一例。

## 验收

- pytest 全过；ruff + pyright 过。
- 够档位时 FakeLLM 写 `<action>hug</action>` 全链路走通：解析、落库、`done` 事件、历史回放都带；不够档位时该动作不进 prompt，硬写也被忽略。

## Comments
