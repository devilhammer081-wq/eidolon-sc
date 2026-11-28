# 票 02：前端——她的动作胶囊

Status: done

Spec: `.scratch/her-interactions/spec.md`

Blocked by: 01

## 任务

1. `conversationLog.ts`：角色 entry 带 `interactionId`（历史读回 + 流式 `done` 消息）。
2. `ConversationView.tsx`：胶囊渲染从「用户行」扩到任意一侧；她那侧胶囊带她的名字、用她的颜色（文案如「真乃 拥抱了你」，目录缺项时退回叙述行）。流式过程中动作（标签在台词外）不出增量气泡——`done` 后整条渲染。
3. `zh.ts`：她的胶囊文案函数（名字 + 动作）；其余 i18n 齐全。

## 验收

- [x] typecheck + vitest 过（1567 个全过）+ `next build` 过；她做的动作渲染为台词上方的居中胶囊（「真乃 拥抱」形态），历史一致；用户侧胶囊不变。

## Comments

### 实现说明（票 02）

- `conversationLog.ts`：`Entry` 的 character 分支加 `interactionId`；`toEntry`（历史读回）把角色行的 `interaction_id` 带上；`api.ts` 的 `Recorded.interaction_id` 文档改为「谁的行都可带」。
- `ConversationView.tsx`：**没有**并入用户的胶囊分支——她做动作时台词照常要成气泡，所以在默认气泡分支里、`Bubbled` 上方渲染一条居中 `Capsule`（`hersCapsule(她的名字, 动作名)`，目录缺项时写动作 id）；用户侧胶囊分支保持原样。流式过程中不出现（`done` 后的消息才带 id），与票 01 交接一致。
- `zh.ts`：`hersCapsule(name, action) ->「真乃 拥抱」`。判断题：不用「拥抱了你」的拼法（对「击掌」不成句）；也不给胶囊上她的颜色（居中胶囊都是中性样式，同用户侧、同事件胶囊）。
