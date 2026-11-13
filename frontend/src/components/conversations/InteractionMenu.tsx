"use client";

// 输入栏左侧的「互动」键和它打开的动作目录（GLOSSARY.md「互动动作」，spec「对话互动动作」）：目录从后端来
// （`GET /api/interactions`），每一项是动作的 emoji 和名字，右边一个「推荐关系」标签写它适合的好感度档位
// （`copy.conversation.affinity.tiers`）。任何档位都能选任何动作——不禁用；点了就把这个动作作为一条
// 回合发给后端，她自己按档位反应。

import { useState, type RefObject } from "react";

import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverHeader, PopoverTitle, PopoverTrigger } from "@/components/ui/popover";
import { copy } from "@/i18n";
import { InteractionIcon } from "@/theme/icons";

import { useInteractions } from "./useInteractions";

const t = copy.conversation.interactions;

/**
 * 「互动」键加动作目录。浮层渲染进对话这棵子树（`subtree`），拿得到她的颜色和 `.dark`
 * （DESIGN.md「The Scoped Colour Rule」）；目录还没读到（或读不到）时点开是空的，只写菜单标题。
 */
export function InteractionMenu({
  subtree,
  disabled,
  onPick,
}: {
  /** 对话子树，浮层渲染进去。 */
  subtree: RefObject<HTMLDivElement | null>;
  /** 对话不能发回合时（没开、冷却、已结束）键不可点。 */
  disabled: boolean;
  /** 选了一个动作：把它作为一条回合发出去。 */
  onPick: (interactionId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const catalog = useInteractions();
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        render={
          <Button
            variant="ghost"
            size="icon-lg"
            aria-label={t.menu}
            disabled={disabled}
            focusableWhenDisabled
          />
        }
      >
        <InteractionIcon className="size-5" />
      </PopoverTrigger>
      <PopoverContent container={subtree} align="start" className="max-h-[min(30rem,60dvh)]">
        <PopoverHeader>
          <PopoverTitle>{t.title}</PopoverTitle>
        </PopoverHeader>
        <div className="-mx-1 min-h-0 flex-1 overflow-y-auto px-1">
          {/* 每一项：emoji 加名字，右边推荐档位的标签；任何档位都可选（spec：不做解锁门槛） */}
          {catalog?.map((action) => (
            <Button
              key={action.id}
              variant="ghost"
              className="w-full justify-start gap-2"
              onClick={() => {
                setOpen(false);
                onPick(action.id);
              }}
            >
              <span aria-hidden className="text-base leading-none">
                {action.emoji}
              </span>
              <span>{action.name}</span>
              <span className="ml-auto text-meta text-muted-foreground">
                {t.recommendedTier(copy.conversation.affinity.tiers[action.recommended_tier])}
              </span>
            </Button>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  );
}
