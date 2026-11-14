# 票 04：导航「外出」+ 入口/选人/选地页

Status: done

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

- [x] typecheck + vitest 过；导航与卡片出现（1565 个 vitest 全过，`next build` 出 `/outings`）。
- [x] 选人上限 3 生效；四地点卡片展示图片（素材已拷入 `frontend/public/outings/`）。
- [x] 会话页由票 05 一并实现（本波两票同批）。

## Comments

### 票 02 交接

- 独自外出后端已就绪：`POST /api/outings/solo`（body `{location_id: string | null}`，null 抽随机；201 返回 `{outing, encounter}`，偶遇命中时 `encounter = {character_id, conversation_id, opening}`——拿着 conversation_id 跳现有对话页即可，开场白就是她的搭话；模型失败 502「这次外出没有成行，请稍后再试」，可直接 toast）。历史列表每条的形状见 `outings_api._shown`：`location_id/location_name/messages[]/encounter {character_id, character_name | null}/…`。
- 管理台的「外出」配置卡（encounter_chance）后端已开（`/api/admin/config/outings`），前端 `lib/adminConfig.ts` 还不认识 `outings` 这个 item：加进 `ItemName`/`ITEM_SPECS`/`TAB_ITEMS`（limits 那组，moments 后面）时顺手补上，不然部署者改不了偶遇概率。

### 实现说明（票 04）

由主会话实现（实现子代理两次撞使用限额中断后接手）。要点与判断题：

- 导航：「外出」加在「玩法」和「设置」之间（`navShell.ts` 的 NAV_ITEMS/FIRST_LEVEL/isInShell/currentNavItem/navDots，`AppNav.tsx` 图标 `Footprints as OutingsIcon`，`zh.ts` nav.outings）；`isInShell` 认 `/outings` 和 `/outings/<id>`，通话条覆盖规则随之生效。
- 玩法页卡：`playCards.ts` 的卡 id 类型放宽为 `PlayCardId = PlaySubpage | "outings"`，外出卡永远显示、直去 `/outings?invite=1`（进选人向导）；`PlayCardLink` 图标同款。
- 入口页 `components/outings/OutingsPage.tsx`：「独自外出」就地 POST、就地展示见闻与偶遇引导（去她对话页）；「发起邀约」两步向导（选人最多 3、选地点四卡带图）；下方历史列表（进行中的进会话页，走完的独自外出留原地）。`?invite=1` 经 `OutingsSearch`（useSearchParams 要 Suspense）读入。
- API 客户端（lib/api.ts）：locations/list/start-solo/start/turns(SSE)/events/end 全套，SSE 复用既有 `serverSentEvents`；后端补了 `GET /api/outings/locations`（带事件清单，会话页事件菜单用）。
- worktree 注意：node_modules 联接 Turbopack build 不认（跨根目录），已换真实 `npm install`；typecheck/vitest 用联接没问题。
- 视觉冒烟（导航/卡片/向导长相）留人工验证。
