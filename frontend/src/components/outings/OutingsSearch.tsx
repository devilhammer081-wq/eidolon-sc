"use client";

import { useSearchParams } from "next/navigation";

import { OutingsPage } from "@/components/outings/OutingsPage";

/** 把网址上的 `?invite=1` 读给入口页：玩法页的「外出」卡要直达选人（useSearchParams 要一层 Suspense）。 */
export function OutingsSearch() {
  const params = useSearchParams();
  return <OutingsPage invite={params.get("invite") === "1"} />;
}
