"use client";

import { useEffect, useRef, useState } from "react";

import { MarkedAvatar } from "@/components/app/MarkedAvatar";
import { Bubble, BubbleContent } from "@/components/ui/bubble";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Message, MessageContent, MessageHeader } from "@/components/ui/message";
import { Spinner } from "@/components/ui/spinner";
import { useDirectory } from "@/components/conversations/ConversationDirectory";
import { BackIcon, SendIcon } from "@/theme/icons";
import { Ja } from "@/theme/Ja";
import { copy } from "@/i18n";
import { ApiError, type GroupLine, readGroup, sendGroupTurn } from "@/lib/api";

const t = copy.group;
const MAX_INPUT_LENGTH = 2000;

/** What is being said while a turn streams in: who speaks, and her words so far. */
type Streaming = { speaker: string; name: string; color: string | null; said: string };

/** 她的一条话：和对话页同一种气泡（`Bubble variant="her"`），日语原文在上、中文字幕在下
 * （The Original-Then-Subtitle Rule）；没带字幕的行（朴素回复、旧数据）只有一句话，照原样显示。 */
function HerBubble({ line }: { line: GroupLine }) {
  const segments = line.segments ?? [];
  return (
    <Bubble variant="her" align="start">
      <BubbleContent>
        {segments.length === 0 ? (
          <p className="text-body whitespace-pre-wrap">{line.text}</p>
        ) : (
          <div className="flex flex-col gap-2">
            {segments.map((segment, at) => (
              <div key={at} className="flex flex-col gap-0.5">
                <p className="text-japanese-line">
                  <Ja>{segment.ja}</Ja>
                </p>
                {segment.zh && (
                  <p className="text-subtitle text-muted-foreground">{segment.zh}</p>
                )}
              </div>
            ))}
          </div>
        )}
      </BubbleContent>
    </Bubble>
  );
}

/** 消息流里的一行：话题的开合居中灰字，制作人的话靠右（和对话页同一种气泡），她的靠左带头像、
 * 名字着色和日语加字幕的气泡。 */
function Line({ line, avatar }: { line: GroupLine; avatar: string | null }) {
  if (line.speaker === null && line.kind !== "say") {
    return <p className="text-meta text-muted-foreground">{line.text}</p>;
  }
  if (line.speaker === null) {
    return (
      <Bubble variant="producer" align="end">
        <BubbleContent>
          <p className="text-body whitespace-pre-wrap">{line.text}</p>
        </BubbleContent>
      </Bubble>
    );
  }
  return (
    <Message align="start">
      <MarkedAvatar name={line.speaker_name ?? line.speaker} src={avatar} size="bubble" />
      <MessageContent className="gap-1">
        <MessageHeader
          className="px-1"
          style={line.color ? { color: line.color } : undefined}
        >
          {line.speaker_name ?? line.speaker}
        </MessageHeader>
        <HerBubble line={line} />
      </MessageContent>
    </Message>
  );
}

/**
 * 283事务所的群聊页（`/group`，GLOSSARY.md「群聊」）：在对话外壳的右栏里，像一个虚拟角色的对话页
 * （DESIGN.md「Layout」的双栏，列表不动，右栏换她）。进页把角色们的话题带到当下（读就是补齐）；
 * 消息流制作人的话靠右、她们的靠左带头像和名字着色，气泡是日语原文加中文字幕。说话支持 @（只她
 * 回应，后端解析）；部署者关掉群聊时这一页只说一句。窄屏是独立的一页，页首有回列表的键。
 */
export function GroupPage({ isWide }: { isWide: boolean }) {
  const { characters } = useDirectory();
  const avatarOf = (id: string | null): string | null =>
    id === null ? null : (characters?.find((each) => each.id === id)?.avatar_url ?? null);
  const [lines, setLines] = useState<GroupLine[] | null>(null);
  const [closed, setClosed] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [streaming, setStreaming] = useState<Streaming[]>([]);
  const endRef = useRef<HTMLDivElement>(null);

  const read = async () => {
    try {
      const shown = await readGroup();
      setLines(shown.messages);
      setClosed(false);
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setClosed(true);
      else setFailed(t.loadFailed);
    }
  };

  useEffect(() => {
    void read();
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [lines?.length, streaming]);

  /** 说一句话：流进来谁在说、她说了什么，成了才换成服务器记下的行。 */
  const say = async () => {
    const text = draft.trim();
    if (!text || busy || lines === null) return;
    setBusy(true);
    setDraft("");
    setFailed(null);
    setStreaming([]);
    const mine: GroupLine = {
      id: -1,
      speaker: null,
      speaker_name: null,
      color: null,
      kind: "say",
      text,
      segments: null,
      created_at: new Date().toISOString(),
    };
    setLines([...lines, mine]);
    let failure: string | null = null;
    try {
      for await (const event of sendGroupTurn(text)) {
        if (event.type === "speaker") {
          setStreaming((before) => [
            ...before,
            { speaker: event.character_id, name: event.name, color: event.color, said: "" },
          ]);
        } else if (event.type === "delta") {
          setStreaming((before) =>
            before.map((each) =>
              each.speaker === event.speaker ? { ...each, said: each.said + event.text } : each,
            ),
          );
        } else if (event.type === "done") {
          setLines(event.messages);
          setStreaming([]);
        } else if (event.type === "error") {
          failure = event.message;
        }
      }
    } catch {
      failure = t.turnFailed;
    }
    if (failure !== null) {
      setFailed(failure);
      setLines((before) => (before ? before.slice(0, -1) : before));
    }
    setStreaming([]);
    setBusy(false);
  };

  return (
    <div className="flex h-full min-h-0 flex-col bg-background text-foreground">
      <header className="flex shrink-0 items-center gap-2 px-2 py-2">
        {/* 窄屏是独立的一页，回对话列表；宽屏右栏旁边本来就有列表。 */}
        {!isWide && (
          <Button
            variant="ghost"
            size="icon-lg"
            aria-label={copy.common.back}
            nativeButton={false}
            render={<a href="/conversations" />}
            className="-ml-2"
          >
            <BackIcon className="size-6" />
          </Button>
        )}
        {/* eslint-disable-next-line @next/next/no-img-element -- 仓库里的群头像 */}
        <img src="/group/283.png" alt="" className="size-9 shrink-0 rounded-full object-cover" />
        <div className="flex min-w-0 flex-1 flex-col px-2">
          <h1 className="truncate text-header">{t.title}</h1>
          <p className="truncate text-meta text-muted-foreground">{t.entry.hint}</p>
        </div>
      </header>

      {closed ? (
        <p className="px-4 py-6 text-center text-subtitle text-muted-foreground">{t.closed}</p>
      ) : (
        <>
          <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto px-3 py-3">
            {lines === null ? (
              <p className="flex items-center gap-2 text-subtitle text-muted-foreground">
                <Spinner className="size-4" />
                {t.loading}
              </p>
            ) : (
              lines.map((line) => <Line key={line.id} line={line} avatar={avatarOf(line.speaker)} />)
            )}
            {streaming.map((each, at) => (
              <Message key={at} align="start">
                <MarkedAvatar name={each.name} src={avatarOf(each.speaker)} size="bubble" />
                <MessageContent className="gap-1">
                  <MessageHeader
                    className="px-1"
                    style={each.color ? { color: each.color } : undefined}
                  >
                    {each.name}
                  </MessageHeader>
                  <Bubble variant="her" align="start">
                    <BubbleContent>
                      <p className="text-japanese-line">
                        <Ja>{each.said}</Ja>
                      </p>
                    </BubbleContent>
                  </Bubble>
                </MessageContent>
              </Message>
            ))}
            <div ref={endRef} />
          </div>

          {failed && <p className="px-3 pb-2 text-subtitle text-destructive">{failed}</p>}

          <div className="flex shrink-0 items-center gap-2 px-3 py-2">
            <Input
              value={draft}
              onChange={(event) => setDraft(event.target.value.slice(0, MAX_INPUT_LENGTH))}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.nativeEvent.isComposing) void say();
              }}
              placeholder={t.inputPlaceholder}
              aria-label={t.inputPlaceholder}
              disabled={busy || lines === null}
              className="flex-1"
            />
            <Button
              variant="ghost"
              size="icon-lg"
              aria-label={t.send}
              onClick={() => void say()}
              disabled={busy || draft.trim() === ""}
            >
              <SendIcon className="size-5" />
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
