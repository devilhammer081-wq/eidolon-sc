# 票 03：前端群聊入口与会话页

Status: done

Spec: `.scratch/group-chat/spec.md`

Blocked by: 01

## 任务

1. 素材：`.scratch/temp/20261113/group-avatar-283-final-a.png` 拷入 `frontend/public/group/283.png`。
2. 对话列表（`ConversationList.tsx`）顶部固定「283事务所」入口：A 版头像、群名、最新一条预览、未读点；点进 `/group`。
3. 群聊页 `app/(app)/(nav)/group/page.tsx`：多角色气泡（说话者名字按 characters.toml 颜色、制作人的靠右、topic_open/topic_end 居中样式）——与 `OutingSession` 的渲染抽出共用组件（放 `components/group/` 或公共处，别整页复制）；输入框发回合（SSE 消费与外出同款）、支持 @（占位文案说明，v1 不做补全）；进页拉 `GET /api/group` 并触发票 02 的惰性推进。
4. 导航归属：`/group` 归「对话」项（navShell 的 conversation 判定扩一下）。
5. i18n 全进 `zh.ts`；shadcn 纪律与 DESIGN.md。

## 验收

- [x] typecheck + vitest 过（1566 个全过），`next build` 出 `/group`；入口与群聊页可用。
- [x] @ 与随机回应在页面上生效（后端票 01 测试覆盖 + 页面走同一回合管线）；未读点由 `/api/group/unseen` 驱动、读群聊即清。

## Comments

### 实现说明（票 03）

主会话实现。头像定稿 A 版入 `frontend/public/group/283.png`。

- 入口：`components/group/GroupEntry.tsx` 挂在对话列表最上（A 版头像、群名、说明、未读点；409 时整行隐藏），点进 `/group`。
- 会话页 `components/group/GroupPage.tsx`：进页 `GET /api/group`（即触发票 02 的惰性补齐并清未读）；消息流与对话页同款气泡（制作人的 `variant="producer"` 靠右、她的 `variant="her"` 带头像名字着色靠左、话题开合居中灰字）；输入发回合消费 SSE（speaker→delta→done 换服务器行，error 撤回乐观行）；@ 在占位文案里说明、由后端解析。
- 导航：`/group` 归「对话」项（navShell isInShell 加 GROUP 常量）。
- api 客户端：`readGroup/groupUnseen/sendGroupTurn`（GroupLine/GroupTopic/GroupTurnEvent）；`groupUnseen` 把关群 409 折成 false。

判断题（记录）：
- 票面「与 OutingSession 抽共用组件」没照做：外出会话页在我动手后被另一波工作重写成对话页同款双语气泡（头像、日中双语、事件顺序），群聊页改为直接用同一套 ui/bubble+ui/message 原语仿写（无双语段落——群聊后端是纯文本行），不再抽第三层。
- @ 无输入补全（占位文案说明用法，与外出会话页一致的 v1 口径）。
- 群聊页未读点只在对话列表入口上，导航「对话」图标的小点没接（hasUnseen 只算搭话；要接需动 conversationList 的汇总，留给之后）。
- 提交说明：api.ts/zh.ts 用 hunk 级拆分只暂存了本票的改动，工作区里另一波未提交的改动（外出会话页重写等）原样保留、未混入本提交。
