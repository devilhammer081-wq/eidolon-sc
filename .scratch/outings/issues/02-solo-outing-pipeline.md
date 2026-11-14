# 票 02：独自外出管线（散步见闻 + 偶遇）

Status: done

Spec: `.scratch/outings/spec.md`

Blocked by: 01

## 任务

1. `POST /api/outings/solo`：随机（或请求指定的）地点 → LLM 生成 1–2 段散步见闻（按地点场景描述 + 制作人档案；prompt 走现有 llm 接缝）→ 落库为一条 solo outing（含见闻文本）→ 返回。
2. 偶遇判定：概率 `OutingSettings.encounter_chance`（live_config.py 新增，默认 0.3）。命中时按「与制作人好感度 + 该地点在 characters.toml `place_likes` 的偏好」加权抽一位偶像（角色数据经 roster/characters 模块读）；为这次偶遇开一个 1:1 对话会话（复用现有 Conversation 机制，形式上挂到这次 outing 记录），她的开场白由 LLM 生成（地点见闻 + 她的人设 + 好感档位，注入现有 affinity_prompt），开场后就是普通 turn 管线——偶遇对话直接出现在现有对话列表里。
3. 历史接口：`GET /api/outings` 列出用户的外出记录（含见闻文本、偶遇了谁）。

## 验收

- [x] pytest：见闻生成落库（mock LLM）、概率 0/1 时必不/必偶遇、加权抽取（好感与地点偏好权重生效）、HTTP 流。
- [x] ruff + pyright 过。

## Comments

### 票 01 交接

- 目录已在 assembly 启动加载（写错起不来），挂在 `Backend.outing_catalog`，conftest 也拷好了——不用再动 assembly。`OutingLocation.place_categories` 是 `places.toml` 的类别：偶遇加权＝好感档位 + 她 `place_likes` 与地点 `place_categories` 的交集（有交集加成，无交集只按好感）。
- 存储实例已在 assembly 构造：`Backend.outings`（`Outings`，`backend/src/eidolon/outings.py`）。solo 流程照它的形状走：`add(user, "solo", location, (), now)` → 见闻逐段 `message(kind="opening")`（1–2 段，每段一行，或并成一行）→ `end(user, id, now)`。偶遇后开的对话走现有 Conversation，不用落 outing 消息表。
- `GET /api/outings` 历史直接用 `listed(user)`（最新在前）；「偶遇了谁」票 01 没存列，可在偶遇成局时把她的 id 写进一条消息（如 ending 行 `speaker=<她>`）或给 outings 加列，你定。
- 越权/已结束的写操作抛 `OutingGone`（「这次外出已经结束了」），API 层接成 404/409。

### 实现说明（票 02）

前一位实现者中途被用量上限打断，留下未提交的半成品；本票由第二位实现者修完、测完、关票。模块划分沿用了半成品的设计，修了其中的漏洞（见下面「修了什么」）。

新模块（backend/src/eidolon/）：

- `solo_outings.py`：`SoloOutings.walk(user, location_id)`。抽签全在问模型之前（地点未指定时先抽；偶遇概率；命中再抽是谁），两个 LLM 请求（见闻；命中偶遇再要开场白）都走部署者的 chat 模型（`LiveConfig.lease`，不占用户限额），activity 记一条 `outing`（偶遇命中记她的 id，否则空串；`own_llm/exempt` 都 False，同 moment）。全部问完才落库：先开偶遇（新 Conversation + `Store.add_reach_out`，contact 传 None＝他们从未联系过），再写 outing 行（`add("solo")` → 见闻逐段 `opening` 行 → 命中则 `ending` 行 speaker=她「在海边偶遇了某某。」→ `end`）。模型失败/写空 → `OutingFailed`，API 层 502，什么都没落。
- `outing_prompt.py`：见闻 prompt（地点场景 + 制作人档案 + WALK_RULES，无任何角色，明令不安排具体人物搭话——遇见谁不是写见闻的说了算）与偶遇开场 prompt（`always_known` 她的人设/生日/世界设定 + 制作人档案 + 地点名与场景 + 他的见闻 + 当地时间 + `affinity_prompt(tier)` + ENCOUNTER_RULES，user 位是 MET_HIM）；`parse_walk_notes` 按空行分段、最多两段。
- `outings_api.py`：`POST /api/outings/solo`（201，返回 outing 全量 + `encounter: {character_id, conversation_id, opening}` 或 null；`NoLocation`→404、`OutingFailed`→502）、`GET /api/outings`（`listed()` 最新在前，每条含地点名、各行消息、`encounter: {character_id, character_name}`——角色已从配置删掉时 name 为 null，不崩）。

改动：

- `live_config.py`：`_Outings` 条目（`encounter_chance` 0–1、拒绝布尔；env 默认 `DEFAULT_ENCOUNTER_CHANCE = 0.3`，无 .env 开关）+ `LiveConfig.outings -> OutingSettings`（`config.py` 新增 dataclass）。`admin_config_api.py` 配上 `OutingsInput`（半成品漏了这步，管理台 PUT 一律 404）。
- `store.py`：`add_reach_out` 的 `contact` 放宽为 `datetime | None`（从未联系过的会话传 None；守卫对 None 也成立——有先行搭话即拒）。
- `activity.py`：`RecordKind` 加 `outing`（制作人自己的散步和偶遇开场都不占回合/限额，同 moment 的口径）。
- `assembly.py`：`Backend.solo_outings`。

偶遇加权（`solo_outings.encounter_weight`）：好感档位起始值（affinity.TIERS）+ 10 的底（谁都有机会）；她 `place_likes` 与地点 `place_categories` 有交集再 ×2；好感度关着时人人按 trust。概率按百万分之一整数格抽。

修了什么（半成品的实际 bug）：`walk` 里 `_meeting` 是 async 却没 await；`_meeting` 局部变量 `met` 遮蔽了同名的权重抽取函数；管理台缺 `OutingsInput`；`_shown` 里角色被删时 `character.name` 直接 AttributeError；`ReachOutRefused` 路径先把 outing 行写了一半才开偶遇（502 嘴上说「什么都没落」）——改成先开偶遇再落 outing，拒绝时记录 `rejected`、除一个空会话外什么都不留（他们已另开话头，那场偶遇本就开不成）。

测试：`backend/tests/test_solo_outings.py`（15 个测试函数）。好感加权那条在电影院走（两人的 place_likes 都不沾它的类别，权重才是纯好感），并挂 FakeClock 固定在种入好感的那一刻（默认真钟下冷好感早就恢复了）。管理台改概率两条用 `replace(settings, admins=…)` 起管理员。
