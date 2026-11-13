# 票 02：前端互动菜单与气泡

Status: done

Spec: `.scratch/interactions/spec.md`

Blocked by: 01

## 任务

1. `frontend/src/components/conversations/` 新增 `InteractionMenu.tsx`：对话输入栏左侧的按钮 + Popover 菜单，列出全部动作，每项右侧显示「推荐关系」标签（数据从后端动作目录接口拿；若票 01 未暴露目录接口，则在后端补 `GET /api/interactions`）。所有档位都可选、不禁用。
2. 发送：turn 请求带 `interaction_id`；走现有发送管线（流式协议不变）。
3. 消息流渲染：interaction 消息为居中轻量样式（图标/文案如「✋ 摸了摸她的头」），她的回复仍是普通气泡；历史加载同样渲染。
4. 文案全部进 `frontend/src/i18n/zh.ts`（含动作名、推荐关系标签、菜单标题）。遵守 `frontend/AGENTS.md` shadcn 纪律与 DESIGN.md。

## 验收

- [x] typecheck（`npm run build` 或仓库前端惯用检查）通过。
- [x] Playwright 冒烟：打开某角色对话，菜单弹出、发送摸摸头、居中气泡与角色回复出现、刷新后仍在。

## Comments

### 票 01 交接

- 动作目录接口已就位：`GET /api/interactions` → `[{id, name, emoji, recommended_tier}, ...]`，顺序即菜单展示顺序；tier 取值同 affinity（cold/distant/trust/close/intimate）。
- 发送：`POST /api/conversations/{id}/turns` 带 `interaction_id`，`text` 可不传（后端会用动作的叙述行作为用户消息文本）；流式协议与普通 turn 完全一致，首个 `user` 事件的 `text` 是叙述行（如「（轻轻摸了摸她的头。）」）。
- 历史回放：`GET /api/conversations/{id}/messages` 里 interaction 消息（用户侧）带 `interaction_id` 字段，其余消息该字段为 `null`；前端可据 `interaction_id` 映射目录里的 emoji/名字渲染居中气泡。动作目录前端最好自行缓存（id→name/emoji 映射）。

### 实现说明（票 02）

改动：

- `lib/api.ts`：`Message` 加可选 `interaction_id`；新增 `Interaction` 类型和 `GET /api/interactions` 的 `listInteractions()`；`sendTurn` 加可选 `interactionId` 参数，进请求体的 `interaction_id`。
- `lib/interactions.ts`（新）：目录缓存，每次页面加载只拉一次，菜单和消息流共用；`components/conversations/useInteractions.ts`（新）：目录进 React 的 hook。
- `lib/conversationLog.ts`：用户侧 `Entry` 与 `submitted` 动作加可选 `interactionId`；历史读回（`toEntry`）把 `interaction_id` 带上。
- `lib/liveConversation.ts`：`Ports.sendTurn` 加可选第三参；新增 `sendInteraction(interactionId)`——不发文字（后端用动作叙述行），输入框草稿不动，失败/冷却/结束的分支照 `submit` 的规矩（失败不回填草稿，因为没有草稿）。`ConversationDirectory.tsx` 接线传参。
- `components/conversations/InteractionMenu.tsx`（新）：输入栏左侧「互动」键 + Popover 目录（渲染进对话子树拿她的颜色），每项 emoji 加名字、右侧「推荐{档位}」标签，任何档位不禁用。`ConversationView.tsx`：composer 里挂键；消息流里带 `interactionId` 的用户消息渲染成居中胶囊（复用 `Capsule`，文案如「🤚 摸摸头」），目录没到时先写后端的叙述行。
- `i18n/zh.ts`：`conversation.interactions`（menu/title/recommendedTier/capsule）。动作名和 emoji 本身以后端目录为准（单一事实来源），i18n 只放框架文案——这是对票面「含动作名」的偏离，见下面的判断题。
- `theme/icons.ts`：加 `Hand as InteractionIcon`。

判断题：

- 居中胶囊写「🤚 摸摸头」（emoji 加目录名）而不是票面示例的「摸了摸她的头」：后者是叙述行措辞，目录里没有逐动作的这层文案，前端也不该再抄一份动作字典；目录没读到时回退显示后端的叙述行。
- 发送互动不动输入框草稿（`submit` 是清空再回填）：互动没有文字，草稿留着正好接着打字。
- 互动只在文字输入栏有入口，通话里的打字 dock 不加：通话的回合走通话管线，动作没有语音形态。

验收：typecheck 通过；`sh scripts/affected-tests.sh 781aee1` 通过（本机没 uv，用 `backend/.venv` 加临时 uv shim 跑通）；Playwright 冒烟在本地构建版上过（菜单弹出、推荐标签、发送摸摸头、居中胶囊 + 她的日语/中文回复、刷新后仍在），验完一次性脚本和截图已删，服务已停。

### 审查修复（票 02）

- `liveConversation.ts`：`sendInteraction` 原样复制了 `submit` 的整个回合运行块（约 40 行）——已提取私有 `runTurn`，两个入口只留各自的门与提交，草稿回填按「有没有自己的文字」区分。
- `GLOSSARY.md` 补「互动动作」词条（代码注释里的引用此前指向不存在的词条）。
- 判断题（未改）：动作名/emoji 以后端目录为单一事实来源、`zh.ts` 只放框架文案（对 spec「全部文案进 zh.ts」的偏离，实现说明里已声明）。
