# 票 01：后端——目录反向、prompt 注入、`<action>` 解析与落库

Status: done

Spec: `.scratch/her-interactions/spec.md`

## 任务

1. `interactions.py`：每个动作补 `her_scene`（她发起的 prompt 素材）与 `her_acted`（胶囊叙述行）；新增「按档位筛出她可主动做的动作」辅助函数（`tier` 达到推荐档位才可选）。
2. `reply_format.py`：`ReplyParser` 识别 `<action>id</action>`（回复里最多出现一个，放台词之外）；解析结果带出动作 id；`parse_said` 等入口兼容。解析后 id 不在「允许清单」里时由调用方忽略（解析层不做门控，只如实抽出）。
3. `engine.py`：回合组装时把她可主动做的动作清单（当前档位过滤后）写进指令，含频率约束（偶尔、一回合最多一个、不连续重复同一动作——参考最近消息里她做过的）；模型写出的 `<action>` 越级/未知时忽略。她的台词照常双语、照常交 judge，动作不加分（`interactions.affinity_step` 只在用户侧调用，不动）。
4. `store.py`：`_insert_message` 角色行落 `interaction_id`（列已存在）；`Message.shown()` 回放带出。
5. 测试：仿 `test_interactions`——目录反向文案齐全、prompt 只含允许动作、解析（正常/未知/无标签）、越级忽略、角色行落库回放、全链路 HTTP 一例。

## 验收

- [x] pytest 全过（16 个互动测试 + 130 个相邻回归）；ruff + pyright 过。
- [x] 够档位时 FakeLLM 写 `<action>hug</action>` 全链路走通：解析、落库、历史回放都带；不够档位时该动作不进 prompt，硬写也被忽略。

## Comments

### 实现说明（票 01）

- `interactions.py`：`Interaction` 加 `her_acted`（她那侧的胶囊叙述行）与 `her_scene`（她发起的 prompt 场景）；`she_may`（档位门控，reaches != below）；`her_action_lines`（清单进 prompt 的指令与条目，空清单时什么都不给）+ `HER_ACTION_INSTRUCTIONS`（偶尔做、一回合一个、不连续重复、越级当作没发生）。
- `reply_format.py`：`take_action(written) -> (id, rest)`——顶层抽 `<action>`（回复最前、台词之外），最多取第一个，未闭合当没有；通用解析器（流式段/字幕）不动。
- `engine.py`：回合组装时按当前档位筛 `allowed`（排除她上一条做过的，不连做）；prompt 尾部追加 `her_action_lines`；回复完成后 `take_action` 抽标签、`she_may` 门控（越级静默忽略、台词照留），`hers.id` 经 `_keep`/`_record` 传到 `add_turn` 的 `her_interaction_id`。她的台词照常双语照常评 judge，动作不加分（`affinity_step` 只挂在用户侧 `interaction` 上，未动）。
- `store.py`：`add_turn` 加 `her_interaction_id`，角色行走 `interaction_id` 落库（列早就有，无迁移）；**修了 `Message.without_cues()` 重建角色行时丢 `interaction_id` 的既有缺口**（读回全靠它）；`_insert_message`/`_message` 本就通用。
- 测试 `test_interactions.py` 增 6 个：`she_may` 门控矩阵、目录反向文案齐全、`take_action`（正常/无/未闭/双标签）、全链路落库（好感恰为 judge 单步 0.2，验证不加分）、越级忽略（prompt 无 + 硬写不落）、上一动作不进下一回合清单。

### 票 01 交接（给票 02）

- 角色行的 `interaction_id` 现在会随 `GET /messages` 与 `done` 事件的消息回传（`Message.shown()` 全量含它）。
- 她那侧的胶囊文案：`Interaction.her_acted` 是完整叙述行如「（她轻轻抱住了你。）」——前端胶囊建议用目录名拼「名字 动作」（同用户侧「emoji 名字」的形态），目录缺项时退回 `her_acted`。
- 流式过程中动作标签在回复最前、不进任何 delta（`take_action` 在落库前整体抽掉）；前端在 `done` 后渲染即可。
