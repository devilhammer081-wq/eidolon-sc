# Spec: 对话互动动作

Status: ready-for-agent

对话页输入栏左侧新增「互动」按钮，弹出动作菜单（Popover）。选定动作后作为一条特殊消息发送，角色由 LLM 依据当前好感度档位（tier）+ 人设生成反应。

## 决定（已与用户确认）

- **不做解锁门槛**：所有动作任何档位都可选；每个动作在菜单里右侧显示「推荐关系」标签。
- 低于推荐档位 → 角色反应较差（抗拒/尴尬/敷衍），好感收益为零或微负；达到/超过 → 反应良好。
- 补充动作全收：摸摸头、拥抱、亲吻、牵手、击掌、戳脸颊、递零食/奶茶、整理头发、整理衣领。
- 好感收益递减/腻烦：同一动作短时间重复，收益衰减，防止刷好感。
- 动作目录与「推荐关系」映射进 `live_config.py`，admin console 可调（首版可只做数据层默认值，admin UI 不强求）。

## 技术方案

- 后端新模块 `backend/src/eidolon/interactions.py`：动作目录（id、名称、recommended_tier、affinity_delta、prompt 片段——喂给 LLM 的动作场景描述）。
- 复用 `POST /api/conversations/{id}/turns`：请求体新增可选 `interaction_id`；engine 组装 prompt 时注入动作 prompt 片段 + 现有 `affinity_prompt()/tier_prompt()`，并按「当前 tier vs recommended_tier」注入「反应较差/良好」的指令。
- 好感变化走现有 `affinity_judge.py` 逐 turn 评判链路；腻烦逻辑可在 `interactions.py` 里查最近消息里同动作的次数，作为 prompt 提示 + 收益系数。
- 前端：`frontend/src/components/conversations/` 新增 `InteractionMenu.tsx`（shadcn/Popover，遵守 frontend/AGENTS.md shadcn 纪律）；发送后在消息流里渲染为居中轻量气泡（如「✋ 摸了摸她的头」），角色回复为普通气泡。
- i18n：全部文案进 `frontend/src/i18n/zh.ts`。

## Testing Decisions

- 后端：pytest 单测 interactions 目录逻辑（推荐档位判定、腻烦衰减、prompt 注入）、turns 带 interaction_id 的 HTTP 行为（复用现有 conversations 测试风格）。
- 前端：typecheck + 手动/Playwright 冒烟（菜单弹出、发送、气泡渲染）。

## 验收

- 任意档位可选所有动作，菜单显示推荐关系标签。
- 低档位做亲密动作时回复明显抗拒/尴尬；达标时反应良好。
- interaction 消息在消息流中有专属样式；重进会话历史仍在。
- 同一动作连续刷，好感收益递减。
