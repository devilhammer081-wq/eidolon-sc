# 票 03：前端群聊入口与会话页

Status: ready-for-agent

Spec: `.scratch/group-chat/spec.md`

Blocked by: 01

## 任务

1. 素材：`.scratch/temp/20261113/group-avatar-283-final-a.png` 拷入 `frontend/public/group/283.png`。
2. 对话列表（`ConversationList.tsx`）顶部固定「283事务所」入口：A 版头像、群名、最新一条预览、未读点；点进 `/group`。
3. 群聊页 `app/(app)/(nav)/group/page.tsx`：多角色气泡（说话者名字按 characters.toml 颜色、制作人的靠右、topic_open/topic_end 居中样式）——与 `OutingSession` 的渲染抽出共用组件（放 `components/group/` 或公共处，别整页复制）；输入框发回合（SSE 消费与外出同款）、支持 @（占位文案说明，v1 不做补全）；进页拉 `GET /api/group` 并触发票 02 的惰性推进。
4. 导航归属：`/group` 归「对话」项（navShell 的 conversation 判定扩一下）。
5. i18n 全进 `zh.ts`；shadcn 纪律与 DESIGN.md。

## 验收

- typecheck + vitest 过；入口与群聊页可用。
- @ 与随机回应在页面上生效；未读点正确出现/清除。

## Comments
