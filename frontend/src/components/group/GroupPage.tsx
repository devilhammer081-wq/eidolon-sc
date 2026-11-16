"use client";

import { useEffect, useRef, useState } from "react";

import { PageShell } from "@/components/app/PageShell";
import { SubpageHeader } from "@/components/app/SubpageHeader";
import { MarkedAvatar } from "@/components/app/MarkedAvatar";
import { Bubble, BubbleContent } from "@/components/ui/bubble";
import { Message, MessageContent, MessageHeader } from "@/components/ui/message";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { useDirectory } from "@/components/conversations/ConversationDirectory";
import { copy } from "@/i18n";
import { ApiError, type GroupLine, readGroup, sendGroupTurn } from "@/lib/api";

const t = copy.group;
const MAX_INPUT_LENGTH = 2000;

/** What is being said while a turn streams in: who speaks, and her words so far. */
type Streaming = { speaker: string; name: string; color: string | null; said: string };

/** 消息流里的一行：话题的开合居中灰字，制作人的话靠右（和对话页同一种气泡），她的靠左带名字着色。 */
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
        <Bubble variant="her" align="start">
          <BubbleContent>
            <p className="text-body whitespace-pre-wrap">{line.text}</p>
          </BubbleContent>
        </Bubble>
      </MessageContent>
    </Message>
  );
}

/**
 * 283事务所的群聊页（`/group`）：进页把角色们的话题带到当下（读就是补齐），消息流里制作人的话靠右、
 * 她们的靠左带名字着色，话题的开合居中。说话支持 @（只她回应，后端解析）；部署者关掉群聊时这一页
 * 只说「群聊没有开放」。
 */
export function GroupPage() {
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

  if (closed) {
    return (
      <PageShell
        width="full"
        isInShell
        header={<SubpageHeader title={t.title} backHref="/conversations" />}
      >
        <p className="text-subtitle text-muted-foreground">{t.closed}</p>
      </PageShell>
    );
  }

  return (
    <PageShell
      width="full"
      isInShell
      header={<SubpageHeader title={t.title} backHref="/conversations" />}
    >
      <div className="flex flex-1 flex-col gap-3 overflow-y-auto pb-2">
        {lines === null ? (
          <p className="flex items-center gap-2 text-subtitle text-muted-foreground">
            <Spinner className="size-4" />
            {t.loading}
          </p>
        ) : (
          lines.map((line) => (
            <Line key={line.id} line={line} avatar={avatarOf(line.speaker)} />
          ))
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
                  <p className="text-body whitespace-pre-wrap">{each.said}</p>
                </BubbleContent>
              </Bubble>
            </MessageContent>
          </Message>
        ))}
        <div ref={endRef} />
      </div>

      {failed && <p className="text-subtitle text-destructive">{failed}</p>}

      <div className="flex items-center gap-2">
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
        <Button onClick={() => void say()} disabled={busy || draft.trim() === ""}>
          {t.send}
        </Button>
      </div>
    </PageShell>
  );
}
