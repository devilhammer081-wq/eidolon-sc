"use client";

import { useWide } from "@/components/conversations/ConversationDirectory";
import { GroupPage } from "@/components/group/GroupPage";

/** 283事务所的群聊（`/group`）：在对话外壳的右栏里，像一个虚拟角色的对话页；窄屏占满一页。 */
export default function Group() {
  return <GroupPage isWide={useWide()} />;
}
