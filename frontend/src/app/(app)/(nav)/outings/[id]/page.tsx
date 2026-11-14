"use client";

import { useParams } from "next/navigation";

import { OutingSession } from "@/components/outings/OutingSession";

/** 一次外出的会话页（`.scratch/outings` spec「会话页」）：进行中的可以说话、触发事件、结束；结束的看全程。 */
export default function OutingPage() {
  const { id } = useParams<{ id: string }>();
  return <OutingSession id={Number(id)} />;
}
