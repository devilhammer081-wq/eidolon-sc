# 票 02：独自外出管线（散步见闻 + 偶遇）

Status: ready-for-agent

Spec: `.scratch/outings/spec.md`

Blocked by: 01

## 任务

1. `POST /api/outings/solo`：随机（或请求指定的）地点 → LLM 生成 1–2 段散步见闻（按地点场景描述 + 制作人档案；prompt 走现有 llm 接缝）→ 落库为一条 solo outing（含见闻文本）→ 返回。
2. 偶遇判定：概率 `OutingSettings.encounter_chance`（live_config.py 新增，默认 0.3）。命中时按「与制作人好感度 + 该地点在 characters.toml `place_likes` 的偏好」加权抽一位偶像（角色数据经 roster/characters 模块读）；为这次偶遇开一个 1:1 对话会话（复用现有 Conversation 机制，形式上挂到这次 outing 记录），她的开场白由 LLM 生成（地点见闻 + 她的人设 + 好感档位，注入现有 affinity_prompt），开场后就是普通 turn 管线——偶遇对话直接出现在现有对话列表里。
3. 历史接口：`GET /api/outings` 列出用户的外出记录（含见闻文本、偶遇了谁）。

## 验收

- pytest：见闻生成落库（mock LLM）、概率 0/1 时必不/必偶遇、加权抽取（好感与地点偏好权重生效）、HTTP 流。
- ruff + pyright 过。

## Comments

### 票 01 交接

- 目录已在 assembly 启动加载（写错起不来），挂在 `Backend.outing_catalog`，conftest 也拷好了——不用再动 assembly。`OutingLocation.place_categories` 是 `places.toml` 的类别：偶遇加权＝好感档位 + 她 `place_likes` 与地点 `place_categories` 的交集（有交集加成，无交集只按好感）。
- 存储实例已在 assembly 构造：`Backend.outings`（`Outings`，`backend/src/eidolon/outings.py`）。solo 流程照它的形状走：`add(user, "solo", location, (), now)` → 见闻逐段 `message(kind="opening")`（1–2 段，每段一行，或并成一行）→ `end(user, id, now)`。偶遇后开的对话走现有 Conversation，不用落 outing 消息表。
- `GET /api/outings` 历史直接用 `listed(user)`（最新在前）；「偶遇了谁」票 01 没存列，可在偶遇成局时把她的 id 写进一条消息（如 ending 行 `speaker=<她>`）或给 outings 加列，你定。
- 越权/已结束的写操作抛 `OutingGone`（「这次外出已经结束了」），API 层接成 404/409。
