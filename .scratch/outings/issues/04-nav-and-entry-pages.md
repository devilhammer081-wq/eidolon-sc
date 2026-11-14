# 票 04：导航「外出」+ 入口/选人/选地页

Status: ready-for-agent

Spec: `.scratch/outings/spec.md`

Blocked by: 01

## 任务

1. 素材：把 `.scratch/temp/20261113/{cinema,mall,amusement-park,seaside}.png` 拷入 `frontend/public/outings/`（文件名与后端目录 id 对应）。
2. `AppNav.tsx` + `i18n/zh.ts` nav 段加「外出」（第四项，设置之前）。
3. 新路由 `app/(app)/(nav)/outings/page.tsx` 入口页：「独自外出」按钮 + 「发起邀约」（选人 → 选地）向导；下方历史外出列表（GET /api/outings）。选人页复用对话列表的角色选择交互，上限 3、至少 1；选地页四张地点卡片（图 + 名）。
4. 玩法页 `playCards` 加「外出」卡片，点击带参进入外出入口页（直接进入选人向导）。
5. 文案全进 `i18n/zh.ts`；遵守 frontend/AGENTS.md shadcn 纪律与 DESIGN.md。
6. API 客户端函数进 `lib/api.ts`。

## 验收

- typecheck + vitest 过；导航与卡片出现。
- 选人上限 3 生效；四地点卡片展示图片。
- （票 05 未做时会话页不可用，入口可先禁用或占位）

## Comments

### 票 02 交接

- 独自外出后端已就绪：`POST /api/outings/solo`（body `{location_id: string | null}`，null 抽随机；201 返回 `{outing, encounter}`，偶遇命中时 `encounter = {character_id, conversation_id, opening}`——拿着 conversation_id 跳现有对话页即可，开场白就是她的搭话；模型失败 502「这次外出没有成行，请稍后再试」，可直接 toast）。历史列表每条的形状见 `outings_api._shown`：`location_id/location_name/messages[]/encounter {character_id, character_name | null}/…`。
- 管理台的「外出」配置卡（encounter_chance）后端已开（`/api/admin/config/outings`），前端 `lib/adminConfig.ts` 还不认识 `outings` 这个 item：加进 `ItemName`/`ITEM_SPECS`/`TAB_ITEMS`（limits 那组，moments 后面）时顺手补上，不然部署者改不了偶遇概率。
