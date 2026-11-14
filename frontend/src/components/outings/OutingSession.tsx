"use client";

import NextLink from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { PageShell } from "@/components/app/PageShell";
import { SubpageHeader } from "@/components/app/SubpageHeader";
import { useDirectory } from "@/components/conversations/ConversationDirectory";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Spinner } from "@/components/ui/spinner";
import { Sparkles as EventIcon } from "lucide-react";
import { copy } from "@/i18n";
import {
  type Outing,
  type OutingLocation,
  type OutingMessage,
  type OutingSettlement,
  type OutingTurnEvent,
  endOuting,
  listOutingLocations,
  listOutings,
  sendOutingTurn,
  setOffOutingEvent,
} from "@/lib/api";

const t = copy.outings.session;
const MAX_INPUT_LENGTH = 2000;

/** What is being said while a turn streams in: who speaks, and her words so far. */
type Streaming = { speaker: string; name: string; color: string | null; said: string };

/** A line as the session shows it: who said it (null for the producer), or the scene it
 * stands for (an opening's narration, an event, the ending). */
function Line({
  line,
  characters,
}: {
  line: OutingMessage;
  characters: Map<string, { name: string; color: string | null }>;
}) {
  // 场景与事件居中，像对话页里送礼那样的提示行。
  if (line.speaker === null && line.kind !== "say") {
    return <p className="text-meta text-muted-foreground">{line.text}</p>;
  }
  if (line.speaker === null) {
    return (
      <p className="max-w-[85%] self-end rounded-2xl bg-muted px-3 py-2 text-body whitespace-pre-wrap">
        {line.text}
      </p>
    );
  }
  const who = characters.get(line.speaker);
  return (
    <div className="flex max-w-[85%] flex-col gap-0.5">
      <span className="text-meta" style={who?.color ? { color: who.color } : undefined}>
        {who?.name ?? line.speaker}
      </span>
      <p className="rounded-2xl border px-3 py-2 text-body whitespace-pre-wrap">{line.text}</p>
    </div>
  );
}

/**
 * 一次外出的会话页（`.scratch/outings` spec「会话页」）：地点做页首，下面是消息流——制作人的话靠右、
 * 她们的靠左带名字着色，场景与事件居中。进行中的能说话（@某位只让她回应）、触发地点事件、结束外出（结算就地说）；
 * 结束的只看全程。独自外出的没有回合，只有见闻和偶遇的去处。
 */
export function OutingSession({ id }: { id: number }) {
  const { guard } = useDirectory();
  const [outing, setOuting] = useState<Outing | null>(null);
  const [locations, setLocations] = useState<OutingLocation[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [turnFailed, setTurnFailed] = useState<string | null>(null);
  const [streaming, setStreaming] = useState<Streaming[]>([]);
  const [settlement, setSettlement] = useState<OutingSettlement[] | null>(null);
  const [eventsOpen, setEventsOpen] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [outings, listed] = await Promise.all([listOutings(), listOutingLocations()]);
        if (!alive) return;
        setOuting(outings.find((each) => each.id === id) ?? null);
        setLocations(listed);
      } catch {
        if (alive) setFailed(true);
      }
    })();
    return () => {
      alive = false;
    };
  }, [id]);

  const location = locations?.find((each) => each.id === outing?.location_id) ?? null;
  const characters = useMemo(() => {
    const byId = new Map<string, { name: string; color: string | null }>();
    for (const each of outing?.participants ?? []) {
      byId.set(each.character_id, { name: each.character_name ?? each.character_id, color: each.color });
    }
    return byId;
  }, [outing]);
  const ongoing = outing?.status !== "ended";

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [outing?.messages.length, streaming, settlement]);

  /** 说一句话：流进来谁在说、她说了什么，成了才换成服务器记下的行。 */
  const say = async () => {
    const text = draft.trim();
    if (!text || !outing || busy || !ongoing) return;
    setBusy(true);
    setDraft("");
    setTurnFailed(null);
    setStreaming([]);
    const mine: OutingMessage = {
      speaker: null,
      kind: "say",
      text,
      event: null,
      created_at: new Date().toISOString(),
    };
    setOuting({ ...outing, messages: [...outing.messages, mine] });
    let failed: string | null = null;
    try {
      for await (const event of sendOutingTurn(outing.id, text)) {
        onEvent(event);
      }
    } catch {
      failed = t.turnFailed;
    }
    function onEvent(event: OutingTurnEvent) {
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
        setOuting((before) =>
          before
            ? {
                ...before,
                messages: [
                  ...before.messages.slice(0, -1),
                  ...event.messages.map((line) => ({ ...line })),
                ],
              }
            : before,
        );
        setStreaming([]);
      } else if (event.type === "error") {
        failed = event.message;
      }
    }
    if (failed !== null) {
      setTurnFailed(failed);
      setOuting((before) =>
        before ? { ...before, messages: before.messages.slice(0, -1) } : before,
      );
    }
    setStreaming([]);
    setBusy(false);
  };

  /** 触发一件地点事件，把留下的行整段落进来。 */
  const setOff = async (eventId: string) => {
    if (!outing || busy || !ongoing) return;
    setEventsOpen(false);
    setBusy(true);
    setTurnFailed(null);
    try {
      const happened = await setOffOutingEvent(outing.id, eventId);
      setOuting((before) =>
        before ? { ...before, messages: [...before.messages, ...happened.messages] } : before,
      );
    } catch {
      setTurnFailed(t.eventFailed);
    } finally {
      setBusy(false);
    }
  };

  /** 结束这次外出：结算就地说，谁的好感怎么变、都记住了什么。 */
  const finish = async () => {
    if (!outing || busy || !ongoing) return;
    setBusy(true);
    setTurnFailed(null);
    try {
      const ended = await endOuting(outing.id);
      setOuting(ended.outing);
      setSettlement(ended.settlement);
    } catch {
      setTurnFailed(t.turnFailed);
    } finally {
      setBusy(false);
    }
  };

  if (failed) {
    return (
      <PageShell width="full" isInShell header={<SubpageHeader title={copy.outings.title} backHref="/outings" />}>
        <p className="text-subtitle text-destructive">{copy.outings.failed}</p>
      </PageShell>
    );
  }

  if (outing === null || locations === null) {
    return (
      <PageShell width="full" isInShell header={<SubpageHeader title={copy.outings.title} backHref="/outings" />}>
        <p className="flex items-center gap-2 text-subtitle text-muted-foreground">
          <Spinner className="size-4" />
          {copy.outings.loading}
        </p>
      </PageShell>
    );
  }

  return (
    <PageShell
      width="full"
      isInShell
      header={
        <SubpageHeader
          title={outing.location_name}
          backHref="/outings"
          end={
            ongoing && outing.kind === "outing" ? (
              <Button variant="ghost" disabled={busy} onClick={() => void finish()}>
                {t.end}
              </Button>
            ) : undefined
          }
        />
      }
    >
      <div className="flex flex-1 flex-col gap-3 overflow-y-auto pb-2">
        {outing.messages.map((line, at) => (
          <Line key={at} line={line} characters={characters} />
        ))}
        {streaming.map((each, at) => (
          <div key={at} className="flex max-w-[85%] flex-col gap-0.5">
            <span className="text-meta" style={each.color ? { color: each.color } : undefined}>
              {each.name}
            </span>
            <p className="rounded-2xl border px-3 py-2 text-body whitespace-pre-wrap">{each.said}</p>
          </div>
        ))}
        {settlement !== null && (
          <section className="flex flex-col gap-1 rounded-2xl border p-3">
            <h2 className="text-header">{t.ending}</h2>
            {settlement.map((each) => (
              <p key={each.character_id} className="text-body">
                {t.settled(each.character_name)}
              </p>
            ))}
          </section>
        )}
        <div ref={endRef} />
      </div>

      {turnFailed && <p className="text-subtitle text-destructive">{turnFailed}</p>}

      {ongoing && outing.kind === "outing" && (
        <div className="flex items-center gap-2">
          {location && location.events.length > 0 && (
            <Popover open={eventsOpen} onOpenChange={setEventsOpen}>
              <PopoverTrigger
                render={
                  <Button variant="outline" size="icon" aria-label={t.events} disabled={busy} />
                }
              >
                <EventIcon aria-hidden className="size-5" />
              </PopoverTrigger>
              <PopoverContent className="w-56 p-1">
                <div className="flex flex-col">
                  {location.events.map((event) => (
                    <button
                      key={event.id}
                      type="button"
                      onClick={() => void setOff(event.id)}
                      className="rounded-lg px-2 py-1.5 text-left text-body outline-none hover:bg-muted focus-visible:ring-3 focus-visible:ring-ring/50"
                    >
                      {event.trigger}
                    </button>
                  ))}
                </div>
              </PopoverContent>
            </Popover>
          )}
          <Input
            value={draft}
            onChange={(event) => setDraft(event.target.value.slice(0, MAX_INPUT_LENGTH))}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.nativeEvent.isComposing) void say();
            }}
            placeholder={t.inputPlaceholder}
            aria-label={t.inputPlaceholder}
            disabled={busy}
            className="flex-1"
          />
          <Button onClick={() => void say()} disabled={busy || draft.trim() === ""}>
            {t.send}
          </Button>
        </div>
      )}

      {outing.status === "ended" && settlement === null && outing.kind === "outing" && (
        <p className="text-subtitle text-muted-foreground">{t.ending}</p>
      )}

      {outing.encounter?.character_id && (
        <NextLink
          href={`/conversation/${outing.encounter.character_id}`}
          onClick={guard(`/conversation/${outing.encounter.character_id}`)}
          className="text-body text-primary underline underline-offset-4"
        >
          {copy.outings.solo.met(outing.encounter.character_name ?? outing.encounter.character_id)}
        </NextLink>
      )}
    </PageShell>
  );
}
