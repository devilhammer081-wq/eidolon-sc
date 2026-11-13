# 票 05：外出会话页与结算展示

Status: ready-for-agent

Spec: `.scratch/outings/spec.md`

Blocked by: 03, 04

## 任务

1. 外出会话页 `app/(app)/(nav)/outings/[id]/page.tsx`：地点头图（public/outings 图）+ 多角色气泡（头像、名字按 characters.toml 颜色着色、说话者为制作人的气泡靠右）；开场/事件消息特殊样式；输入框发送回合（支持 @：输入 @ 弹出同行角色补全，v1 简化为菜单点选 @ 也行）；「触发事件」按钮（列当前地点事件池）；「结束外出」按钮。
2. 结束后展示结算：好感变化提示（沿用现有 affinity 变化展示样式）+ 本次外出小结；返回外出首页。
3. 独自外出的见闻展示页 + 偶遇引导（「去和她聊聊」跳到她的对话页）。
4. 文案全进 `i18n/zh.ts`；遵守 shadcn 纪律与 DESIGN.md。

## 验收

- typecheck + vitest 过。
- 全流程可走：发起 → 开场 → 说话/@/事件 → 结束 → 结算展示。
- 偶遇场景：见闻 → 跳对话页。

## Comments
