import { Suspense } from "react";

import { OutingsSearch } from "@/components/outings/OutingsSearch";

/** 外出页第一级（`/outings`）：入口、发起向导和历史（DESIGN.md 由本页自带版式）。玩法页的卡带 `?invite=1` 直达选人。 */
export default function Outings() {
  return (
    <Suspense>
      <OutingsSearch />
    </Suspense>
  );
}
