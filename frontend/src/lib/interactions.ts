// The interaction actions (GLOSSARY.md「互动动作」) the user may take with her: the catalog
// the backend keeps (`GET /api/interactions`), fetched once per page load and shared by the
// menu that offers the actions and the message flow that shows the ones taken.

import { listInteractions, type Interaction } from "@/lib/api";

export type { Interaction };

/** The catalog as asked for, the one asking alone paying for the asking; a failed asking is
 * left behind, so the next one asks again. */
export function interactionsCatalog(): Promise<Interaction[]> {
  catalog ??= listInteractions().catch((e) => {
    catalog = null;
    throw e;
  });
  return catalog;
}

let catalog: Promise<Interaction[]> | null = null;
