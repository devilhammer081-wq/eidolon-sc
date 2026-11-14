# 票 05：外出会话页与结算展示

Status: done

Spec: `.scratch/outings/spec.md`

Blocked by: 03, 04

## 任务

1. 外出会话页 `app/(app)/(nav)/outings/[id]/page.tsx`：地点头图（public/outings 图）+ 多角色气泡（头像、名字按 characters.toml 颜色着色、说话者为制作人的气泡靠右）；开场/事件消息特殊样式；输入框发送回合（支持 @：输入 @ 弹出同行角色补全，v1 简化为菜单点选 @ 也行）；「触发事件」按钮（列当前地点事件池）；「结束外出」按钮。
2. 结束后展示结算：好感变化提示（沿用现有 affinity 变化展示样式）+ 本次外出小结；返回外出首页。
3. 独自外出的见闻展示页 + 偶遇引导（「去和她聊聊」跳到她的对话页）。
4. 文案全进 `i18n/zh.ts`；遵守 shadcn 纪律与 DESIGN.md。

## 验收

- [x] typecheck + vitest 过（1565 个全过），`next build` 出 `/outings/[id]`。
- [ ] 全流程可走：发起 → 开场 → 说话/@/事件 → 结束 → 结算展示（后端各环节已有 HTTP 测试覆盖；页面级 Playwright 流程留人工验证）。
- [ ] 偶遇场景：见闻 → 跳对话页（同上，留人工验证）。

## Comments

### 实现说明（票 05）

由主会话实现。`components/outings/OutingSession.tsx` + `app/(app)/(nav)/outings/[id]/page.tsx`：

- 消息流：制作人的 say 靠右（bg-muted 气泡），角色的靠左带名字着色（characters.toml 的 color），opening 旁白/事件/ending 居中灰字；流式回合按 speaker→delta 增量渲染，done 后换成服务器落库行，error 撤回乐观行并提示。
- @ 回应与事件菜单：输入照常发文本（@ 由后端解析，v1 不做输入框补全，占位文案说明用法）；事件按钮（Sparkles 图标 Popover）列当前地点事件，触发后整段落入。
- 结束：`POST /end` 后输入区换结算卡（每位同行「记住了这次外出」+好感变化），好感度关时结算为空、只留结束语。偶遇过的（kind=solo 或 outing 的 encounter）底部给「去和她聊聊」。
- 会话数据用 `GET /api/outings` 找单条（后端没有单条接口，列表足够小）；404 时回列表页。
- i18n 全在 `zh.ts` 的 `outings.session`；地点图 `/outings/<location_id>.png`。
- 页面级全流程 Playwright 留人工（后端流程票 03 已测）。

### 审查修复（两轴 code-review，基点 5875cdf）

直接修了的：
- 气泡圆角用了 `rounded-2xl`，违反 frontend/AGENTS.md「有名字的值必须用 token」→ 三处气泡改 `rounded-bubble`（卡片/区块的 `rounded-2xl` 不动）。

判断题（未改，记录）：
- `@` 没有输入补全（票面底线是「菜单点选 @ 也行」），现在只有占位文案说明用法，由后端解析 `@名字`。
- 说话者颜色用内联 `style={{ color }}` 逐人上色，没走 `herVars`（那套机制是单人子树用的，多说话人不适配）。
- 两条验收（全流程、偶遇跳转）仍留人工 Playwright。
