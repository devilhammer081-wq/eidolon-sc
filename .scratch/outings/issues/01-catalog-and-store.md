# 票 01：外出地点目录与数据模型

Status: done

Spec: `.scratch/outings/spec.md`

## 任务

1. `characters/outings.toml`（新建，风格对齐 `characters/gifts.toml`）：四个地点——电影院、商场、游乐场、海边。每个含 id、中文名、场景描述（喂 LLM 的地点设定）、事件池（每地 3–4 个事件，每个事件一句触发语 + LLM 场景提示）、好感倾向提示。加载模块 `backend/src/eidolon/outing_catalog.py`（对齐 `gift_catalog.py` 的加载与缓存方式）。
2. store 新表（走 `store.py`/`database.py` 现有迁移方式）：
   - `outings`：id、user_id、kind（solo/outing）、location_id、participant character ids（solo 为空）、status（opening/ongoing/ended）、created_at、ended_at。
   - 外出消息表：outing_id、speaker（character id，空＝制作人）、text、kind（say/event/opening/ending）、created_at。表结构按 spec 要求考虑群聊复用（speaker 语义通用）。
3. 好感结算所需的关联：外出结束要在 affinity 上结算（本票只留结算所需的数据接口，结算逻辑在票 03）。
4. 顺手：GLOSSARY.md 加「外出 (Outing)」词条（含「独自外出」「偶遇」语义；分次提交注意 GLOSSARY.md 工作区里可能有别人未提交的改动，提交时只挑本票 hunk——上游分支干净，无此顾虑）。

## 验收

- [x] pytest：目录加载（四地点、事件数）、外出与消息的建/读/状态流转。
- [x] ruff + pyright 过。

## Comments

### 实现说明（票 01）

目录与加载：

- `characters/outings.toml`：四地点（cinema/mall/amusement-park/seaside，对齐 `.scratch/temp/20261113/` 的头图文件名），每地 3–4 个事件（触发语 + LLM 场景提示 + 好感倾向），地点级好感倾向提示。
- `backend/src/eidolon/outing_catalog.py`：`load_outing_catalog`/`outings_path`/`OutingCatalogError`，对齐 `gift_catalog.py`（缺文件/写错都 `OutingCatalogError`）。assembly 启动即加载、写错了后端起不来，挂在 `Backend.outing_catalog`；`tests/conftest.py` 的 `CharacterConfig` 照 gifts 的样子把仓库 outings.toml 拷到测试角色目录。
- 每个地点多了 `place_categories` 字段（`places.toml` 的类别，加载时校验）：票 02 偶遇按 `place_likes` 加权要用，目录里就得说清这个外出地点算她喜欢的哪几类。

数据模型：

- `backend/src/eidolon/outings.py`：`outings` + `outing_messages` 两表，模块自建（`db.prepare` + `CREATE TABLE IF NOT EXISTS`，即 store.py/database.py 的现有迁移方式；跟随 bar/letters/moments 各自管自己表的做法，没放进 store.py 的 `_SCHEMA`）。`database.py` 的 `USER_DATA` 注册（outing_messages 在 outings 前，删用户连带删）。
- `Outings`：`add`（solo 不带人、outing 1–3 人不重复，建为 opening）、`begin`（opening→ongoing）、`end`（opening/ongoing→ended，solo 从 opening 直达 ended）、`message`（say/event/opening/ending 四种行）、`outing`/`listed`（最新在前）/`messages`（按说出顺序）。不在/不是他的/已结束一律 `OutingGone`。
- 消息表按 spec 考虑了群聊复用：`speaker` 存角色 id、空＝制作人（事件行也无人说，靠 kind 区分）。
- 结算数据接口：事件行带 `event` 列存目录事件 id——票 03 结算要「地点偏好 + 事件走向 + 事件提示的好感倾向」，只存生成出来的文本不够，结算时拿 event id 回目录查提示。`outings.participants`/`location_id`/`messages()` 就是结算要读的全部。

判断点（都写在上面了，两条再点一下）：

- 事件池校验只要求至少一件（`MIN_EVENTS = 1`）；「每地 3–4 个」是首批内容量，由测试对仓库目录断言，不加硬上限，维护者以后加事件不用改代码。
- 外出不进数据包（同朋友圈）、删对话不影响外出。

测试：`backend/tests/test_outing_catalog.py`（仓库目录四地点/事件数/类别、加载报错、起不来）、`backend/tests/test_outings.py`（建/读/状态流转、消息顺序与事件标识、越权、删用户连带删）。
