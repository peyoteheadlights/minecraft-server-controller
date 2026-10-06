/* What happened, as plain sentences grouped by day. Technical mode adds
   each event's raw type and data under its line (see feed.js). */

import { api } from "../api.js";
import { feedList } from "../feed.js";
import { renderers } from "../state.js";
import { t } from "../strings.js";
import { card, emptyState, loadInto } from "../ui.js";

renderers.events = (page) => loadInto(page, async () => {
  const data = await api("/events?limit=200");
  if (!data.events.length) return card(t("events.title"), emptyState(t("events.none")));
  return card(t("events.title"), feedList(data.events));
});
