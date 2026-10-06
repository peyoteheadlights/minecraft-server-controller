/* The getting-started checklist, at the top of a new server's Overview.

   Each item ticks itself off from something the agent measured, never from
   a click here: pressing an item only opens the page where it is done. The
   card can be dismissed, and once everything is done it does not return. */

import { api } from "../api.js";
import { navigate } from "../nav.js";
import { t } from "../strings.js";
import { el, fmt, icon, toast } from "../ui.js";

/* The few values the evidence lines need, from what the agent measured. */
function evidence(entry) {
  const found = entry.evidence || {};
  return {
    when: found.created_at ? fmt.ago(found.created_at) : "",
    name: found.name || "",
  };
}

function item(entry) {
  const label = t(`start.${entry.id}`);
  return el("li", { class: `check-item${entry.done ? " is-done" : ""}` },
    el("span", { class: "check-mark", "aria-hidden": "true" }, entry.done ? icon("security") : null),
    el("div", { class: "check-main" },
      el("strong", {}, label),
      el("div", { class: "hint" }, t(`start.${entry.evidence_key}`, evidence(entry)))),
    entry.done
      ? el("span", { class: "tag ok" }, t("start.done"))
      : el("button", { class: "btn small", type: "button", onclick: () => navigate(entry.page) },
          t(`start.${entry.id}_action`)));
}

/* Fills `node` with the card, or empties it when there is nothing to show. */
export async function renderChecklist(node) {
  let data;
  try {
    data = await api("/getting-started");
  } catch (err) {
    node.replaceChildren();
    return;
  }
  if (!data.show) {
    node.replaceChildren();
    return;
  }
  node.replaceChildren(el("section", { class: "section getting-started" },
    el("div", { class: "section-head" },
      el("h2", {}, t("start.title")),
      el("div", { class: "grow" }),
      el("span", { class: "hint" }, t("start.progress", { done: data.done, total: data.total })),
      el("button", {
        class: "btn plain small", type: "button",
        onclick: async () => {
          try {
            await api("/getting-started/dismiss", { method: "POST" });
            node.replaceChildren();
          } catch (err) { toast(err.message, "error"); }
        },
      }, t("start.hide"))),
    el("div", { class: "group-box" },
      el("p", { class: "hint mt-0" }, t("start.lead")),
      el("ul", { class: "check-list" }, data.items.map(item)))));
}
