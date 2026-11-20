"use client";

import NextLink from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { useDirectory } from "@/components/conversations/ConversationDirectory";
import { copy } from "@/i18n";
import { groupUnseen } from "@/lib/api";
import { cn } from "@/lib/utils";

const t = copy.group.entry;

/**
 * 对话列表最上面的「283事务所」入口：定稿的群头像、群名、一句话说明，有角色说过话而制作人还没读过时
 * 一个前景色小圆点（同列表里搭话的点）。部署者关掉群聊时（409）整行不出现。
 */
export function GroupEntry() {
  const { go } = useDirectory();
  const isCurrent = usePathname() === "/group";
  const [unseen, setUnseen] = useState(false);
  const [closed, setClosed] = useState(false);

  useEffect(() => {
    let alive = true;
    groupUnseen()
      .then((has) => {
        if (alive) setUnseen(has);
      })
      .catch(() => {
        if (alive) setClosed(true);
      });
    return () => {
      alive = false;
    };
  }, []);

  if (closed) return null;
  return (
    <NextLink
      href="/group"
      onClick={() => go("/group")}
      aria-current={isCurrent ? "page" : undefined}
      className={cn(
        "flex w-full items-center gap-3 px-4 py-2.5 text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:ring-inset",
        isCurrent ? "bg-muted" : "hover:bg-muted/60",
      )}
    >
      {/* eslint-disable-next-line @next/next/no-img-element -- 仓库里的群头像 */}
      <img
        src="/group/283.png"
        alt=""
        className="size-10 shrink-0 rounded-full object-cover"
      />
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="flex items-baseline gap-2">
          <span className="min-w-0 flex-1 truncate text-row-name">{t.name}</span>
          {unseen && (
            <>
              <span aria-hidden className="size-2 shrink-0 rounded-full bg-foreground" />
              <span className="sr-only">{t.unseen}</span>
            </>
          )}
        </span>
        <span className="truncate text-preview text-muted-foreground">{t.hint}</span>
      </span>
    </NextLink>
  );
}
