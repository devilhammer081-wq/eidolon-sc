"use client";

import NextLink from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { MarkedAvatar } from "@/components/app/MarkedAvatar";
import { PageShell } from "@/components/app/PageShell";
import { SubpageHeader } from "@/components/app/SubpageHeader";
import { useDirectory } from "@/components/conversations/ConversationDirectory";
import { Button } from "@/components/ui/button";
import { copy } from "@/i18n";
import {
  type Outing,
  type OutingLocation,
  listOutingLocations,
  listOutings,
  startOuting,
  startSoloOuting,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { OutingsIcon } from "@/theme/icons";

const t = copy.outings;

/** How many may come along on one outing (.scratch/outings spec). */
const MOST_COMPANY = 3;

/** Where a walk just had, as its card says it: the location with its notes. */
type Walked = { outing: Outing; met: string | null };

/**
 * 外出页第一级（`/outings`，.scratch/outings spec「入口页」）：页首「外出」大标题，下面两张入口——「独自外出」点了就走，
 * 走完就地看见闻（偶遇了谁就给去她对话页的引导）；「发起邀约」进选人（最多 3 位）再选地点，出发进这次外出的会话页。
 * 再往下是走过的外出，最新在前，进行中的可以接着走。玩法页的「外出」卡带 `?invite=1` 直达选人。
 */
export function OutingsPage({ invite }: { invite: boolean }) {
  const router = useRouter();
  const { characters, guard } = useDirectory();
  const [wizard, setWizard] = useState<"who" | "where" | null>(invite ? "who" : null);
  const [picked, setPicked] = useState<string[]>([]);
  const [locationId, setLocationId] = useState<string | null>(null);
  const [walked, setWalked] = useState<Walked | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const [locations, setLocations] = useState<OutingLocation[] | null>(null);
  const [outings, setOutings] = useState<Outing[] | null>(null);
  const [outingsFailed, setOutingsFailed] = useState(false);

  const read = async () => {
    try {
      const [listed, walkedList] = await Promise.all([listOutingLocations(), listOutings()]);
      setLocations(listed);
      setOutings(walkedList);
      setOutingsFailed(false);
    } catch {
      setOutingsFailed(true);
    }
  };

  useEffect(() => {
    void read();
  }, []);

  const byId = useMemo(() => new Map((characters ?? []).map((each) => [each.id, each])), [characters]);

  /** 独自外出：走完就地看见闻；失败只说一句，什么都没留下。 */
  const setOutAlone = async () => {
    setBusy(true);
    setFailed(null);
    setWalked(null);
    try {
      const { outing, encounter } = await startSoloOuting(null);
      setWalked({ outing, met: encounter?.character_id ?? null });
      void read();
    } catch {
      setFailed(t.solo.failed);
    } finally {
      setBusy(false);
    }
  };

  /** 发起邀约：选好人和地点，出发进会话页。 */
  const setOutTogether = async () => {
    if (picked.length === 0 || locationId === null) return;
    setBusy(true);
    setFailed(null);
    try {
      const outing = await startOuting(picked, locationId);
      router.push(`/outings/${outing.id}`);
    } catch {
      setFailed(t.invite.failed);
      setBusy(false);
    }
  };

  return (
    <PageShell width="full" isInShell header={<h1 className="text-list-title">{t.title}</h1>}>
      <div className="grid gap-4 sm:grid-cols-2">
        <Button
          variant="outline"
          disabled={busy}
          onClick={() => void setOutAlone()}
          className="h-auto flex-col items-start gap-1 rounded-2xl p-4 text-left"
        >
          <span className="flex items-center gap-2 text-header">
            <OutingsIcon aria-hidden className="size-5" />
            {t.solo.name}
          </span>
          <span className="text-subtitle text-muted-foreground">{t.solo.hint}</span>
        </Button>
        <Button
          variant="outline"
          disabled={busy}
          onClick={() => {
            setFailed(null);
            setWalked(null);
            setPicked([]);
            setLocationId(null);
            setWizard("who");
          }}
          className="h-auto flex-col items-start gap-1 rounded-2xl p-4 text-left"
        >
          <span className="text-header">{t.invite.name}</span>
          <span className="text-subtitle text-muted-foreground">{t.invite.hint}</span>
        </Button>
      </div>

      {failed && <p className="text-subtitle text-destructive">{failed}</p>}

      {walked && (
        <section className="flex flex-col gap-2 rounded-2xl border p-4">
          <h2 className="text-header">{walked.outing.location_name}</h2>
          {walked.outing.messages
            .filter((line) => line.kind === "opening" || line.kind === "ending")
            .map((line, at) => (
              <p key={at} className="whitespace-pre-wrap text-body">
                {line.text}
              </p>
            ))}
          {walked.met && byId.get(walked.met) && (
            <NextLink
              href={`/conversation/${walked.met}`}
              onClick={guard(`/conversation/${walked.met}`)}
              className="text-body text-primary underline underline-offset-4"
            >
              {t.solo.met(byId.get(walked.met)!.name)}
            </NextLink>
          )}
        </section>
      )}

      {wizard === "who" && (
        <section className="flex flex-col gap-3">
          <SubpageHeader title={t.invite.who} />
          <p className="text-subtitle text-muted-foreground">{t.invite.whoHint(picked.length)}</p>
          <div className="grid grid-cols-3 gap-2 sm:grid-cols-5">
            {(characters ?? []).map((character) => {
              const isPicked = picked.includes(character.id);
              return (
                <button
                  key={character.id}
                  type="button"
                  aria-pressed={isPicked}
                  onClick={() =>
                    setPicked((before) =>
                      isPicked
                        ? before.filter((id) => id !== character.id)
                        : before.length < MOST_COMPANY
                          ? [...before, character.id]
                          : before,
                    )
                  }
                  className={cn(
                    "flex flex-col items-center gap-1 rounded-2xl border p-2 outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                    isPicked && "border-primary",
                  )}
                >
                  <MarkedAvatar name={character.name} src={character.avatar_url} size="list" />
                  <span className="w-full truncate text-center text-meta">{character.name}</span>
                </button>
              );
            })}
          </div>
          <div className="flex justify-end">
            <Button disabled={picked.length === 0} onClick={() => setWizard("where")}>
              {picked.length === 0 ? t.invite.startEmpty : t.invite.start(picked.length)}
            </Button>
          </div>
        </section>
      )}

      {wizard === "where" && (
        <section className="flex flex-col gap-3">
          <SubpageHeader
            title={t.invite.where}
            backHref="/outings"
            end={
              <Button disabled={locationId === null || busy} onClick={() => void setOutTogether()}>
                {t.invite.start(picked.length)}
              </Button>
            }
          />
          <div className="grid grid-cols-2 gap-3">
            {(locations ?? []).map((location) => (
              <button
                key={location.id}
                type="button"
                aria-pressed={locationId === location.id}
                onClick={() => setLocationId(location.id)}
                className={cn(
                  "flex flex-col gap-2 overflow-hidden rounded-2xl border text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                  locationId === location.id && "border-primary",
                )}
              >
                {/* eslint-disable-next-line @next/next/no-img-element -- 仓库里的静态地点图，不走远程优化 */}
                <img src={`/outings/${location.id}.png`} alt="" className="aspect-video w-full object-cover" />
                <span className="px-3 pb-3 text-body">{location.name}</span>
              </button>
            ))}
          </div>
        </section>
      )}

      <section className="flex flex-col gap-2">
        <h2 className="text-header">{t.history.title}</h2>
        {outingsFailed && <p className="text-subtitle text-destructive">{t.failed}</p>}
        {!outingsFailed && outings === null && (
          <p className="text-subtitle text-muted-foreground">{t.loading}</p>
        )}
        {outings?.length === 0 && <p className="text-subtitle text-muted-foreground">{t.history.empty}</p>}
        {(outings ?? []).map((outing) => {
          // 一次走完的独自外出没有会话页，留在原地看。
          const to = outing.kind === "solo" && outing.status === "ended" ? null : `/outings/${outing.id}`;
          return (
            <NextLink
              key={outing.id}
              href={to ?? "/outings"}
              aria-disabled={to === null}
              onClick={(event) => {
                if (to === null) event.preventDefault();
                else guard(to)(event);
              }}
              className={cn(
                "flex min-h-11 items-center gap-3 rounded-2xl border p-3 outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
                to === null && "pointer-events-none opacity-70",
              )}
            >
              {/* eslint-disable-next-line @next/next/no-img-element -- 仓库里的静态地点图 */}
              <img
                src={`/outings/${outing.location_id}.png`}
                alt=""
                className="size-10 shrink-0 rounded-xl object-cover"
              />
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="truncate text-body">
                  {t.history.line(new Date(outing.created_at).toLocaleDateString(), outing.location_name)}
                  {outing.encounter?.character_name && ` · ${t.history.met(outing.encounter.character_name)}`}
                </span>
                <span className="truncate text-meta text-muted-foreground">
                  {outing.participants
                    .map((each) => each.character_name)
                    .filter((name): name is string => name !== null)
                    .join("、")}
                </span>
              </span>
              {outing.status !== "ended" && (
                <span className="shrink-0 text-meta text-muted-foreground">{t.history.ongoing}</span>
              )}
            </NextLink>
          );
        })}
      </section>
    </PageShell>
  );
}
