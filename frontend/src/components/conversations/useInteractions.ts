"use client";

// The interaction catalog (GLOSSARY.md「互动动作」) as a page holds it: asked for once and
// shared wherever it is wanted (the menu, the message flow), the lib's cache keeping the
// asking to one per page load. Read once — the catalog does not change under a page.

import { useEffect, useState } from "react";

import type { Interaction } from "@/lib/interactions";
import { interactionsCatalog } from "@/lib/interactions";

export function useInteractions(): Interaction[] | null {
  const [catalog, setCatalog] = useState<Interaction[] | null>(null);
  useEffect(() => {
    let gone = false;
    interactionsCatalog().then(
      (listed) => {
        if (!gone) setCatalog(listed);
      },
      () => {},
    );
    return () => {
      gone = true;
    };
  }, []);
  return catalog;
}
