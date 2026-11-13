# 票 02：前端互动菜单与气泡

Status: ready-for-agent

Spec: `.scratch/interactions/spec.md`

Blocked by: 01

## 任务

1. `frontend/src/components/conversations/` 新增 `InteractionMenu.tsx`：对话输入栏左侧的按钮 + Popover 菜单，列出全部动作，每项右侧显示「推荐关系」标签（数据从后端动作目录接口拿；若票 01 未暴露目录接口，则在后端补 `GET /api/interactions`）。所有档位都可选、不禁用。
2. 发送：turn 请求带 `interaction_id`；走现有发送管线（流式协议不变）。
3. 消息流渲染：interaction 消息为居中轻量样式（图标/文案如「✋ 摸了摸她的头」），她的回复仍是普通气泡；历史加载同样渲染。
4. 文案全部进 `frontend/src/i18n/zh.ts`（含动作名、推荐关系标签、菜单标题）。遵守 `frontend/AGENTS.md` shadcn 纪律与 DESIGN.md。

## 验收

- typecheck（`npm run build` 或仓库前端惯用检查）通过。
- Playwright 冒烟：打开某角色对话，菜单弹出、发送摸摸头、居中气泡与角色回复出现、刷新后仍在。

## Comments

### 票 01 交接

- 动作目录接口已就位：`GET /api/interactions` → `[{id, name, emoji, recommended_tier}, ...]`，顺序即菜单展示顺序；tier 取值同 affinity（cold/distant/trust/close/intimate）。
- 发送：`POST /api/conversations/{id}/turns` 带 `interaction_id`，`text` 可不传（后端会用动作的叙述行作为用户消息文本）；流式协议与普通 turn 完全一致，首个 `user` 事件的 `text` 是叙述行（如「（轻轻摸了摸她的头。）」）。
- 历史回放：`GET /api/conversations/{id}/messages` 里 interaction 消息（用户侧）带 `interaction_id` 字段，其余消息该字段为 `null`；前端可据 `interaction_id` 映射目录里的 emoji/名字渲染居中气泡。动作目录前端最好自行缓存（id→name/emoji 映射）。
