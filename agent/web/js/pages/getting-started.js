/* Getting started: the few things to know, in order, each with a button
   to the page where it is done. Linked from the first-visit checklist, from
   every "?" explanation, and from App settings. The same steps in more
   detail are in the README. */

import { navigate } from "../nav.js";
import { can, renderers } from "../state.js";
import { t } from "../strings.js";
import { card, el } from "../ui.js";

// [title, text, button, page, the permission it needs]
const STEPS = [
  ["guide.start", "guide.start_text", "guide.start_button", "dashboard"],
  ["guide.friends", "guide.friends_text", "guide.friends_button", "dashboard"],
  ["guide.world", "guide.world_text", "guide.world_button", "world", "world.replace"],
  ["guide.backups", "guide.backups_text", "guide.backups_button", "backups"],
  ["guide.alerts", "guide.alerts_text", "guide.alerts_button", "app-settings", "settings.edit"],
  ["guide.helpers", "guide.helpers_text", "guide.helpers_button", "helpers", "users.manage"],
  ["guide.trouble", "guide.trouble_text", "guide.trouble_button", "crashes"],
];

renderers["getting-started"] = (page) => {
  const steps = STEPS.filter(([, , , , need]) => !need || can(need));
  page.append(el("div", { class: "stack" },
    el("p", { class: "lead mt-0" }, t("guide.lead")),
    el("ol", { class: "guide" }, steps.map(([title, text, button, target]) => el("li", { class: "guide-step" },
      el("div", { class: "grow" }, el("h3", {}, t(title)), el("p", { class: "hint" }, t(text))),
      el("button", { class: "btn small", type: "button", onclick: () => navigate(target) }, t(button))))),
    card(t("guide.password"),
      el("p", { class: "mt-0" }, t("guide.password_text")),
      el("p", { class: "mono" }, "python -m installer.reset_password"))));
};
