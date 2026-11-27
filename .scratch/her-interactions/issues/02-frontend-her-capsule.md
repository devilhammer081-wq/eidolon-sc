# 票 02：前端——她的动作胶囊

Status: ready-for-agent

Spec: `.scratch/her-interactions/spec.md`

Blocked by: 01

## 任务

1. `conversationLog.ts`：角色 entry 带 `interactionId`（历史读回 + 流式 `done` 消息）。
2. `ConversationView.tsx`：胶囊渲染从「用户行」扩到任意一侧；她那侧胶囊带她的名字、用她的颜色（文案如「真乃 拥抱了你」，目录缺项时退回叙述行）。流式过程中动作（标签在台词外）不出增量气泡——`done` 后整条渲染。
3. `zh.ts`：她的胶囊文案函数（名字 + 动作）；其余 i18n 齐全。

## 验收

- typecheck + vitest 过；她做的动作渲染为居中胶囊（名字着色），历史一致；用户侧胶囊不变。

## Comments
