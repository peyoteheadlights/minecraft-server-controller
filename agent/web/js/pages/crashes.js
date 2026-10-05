import { api } from "../api.js";
import { renderers } from "../state.js";
import { card, confirmDialog, el, fmt, loadInto, table } from "../ui.js";

renderers.crashes = (page) => loadInto(page, async () => {
  const data = await api("/crashes");
  if (!data.crashes.length) {
    return card("Crash history", el("div", { class: "empty" }, "No crashes recorded. Good."));
  }
  return card("Crash history", table(
    ["When", "Exit code", "Likely cause", "Confidence", ""],
    data.crashes.map((crash) => [
      fmt.time(crash.ts),
      el("span", { class: "mono" }, String(crash.exit_code)),
      crash.category,
      el("span", { class: `tag ${crash.confidence === "likely" ? "warn" : "off"}` }, crash.confidence),
      el("button", { class: "btn small", onclick: () => showCrash(crash.id) }, "Details"),
    ])));
});

export async function showCrash(id) {
  const crash = await api(`/crashes/${id}`);
  const context = crash.context || {};
  const analysis = context.analysis || {};
  const body = el("div", {},
    el("p", {},
      el("strong", {}, `${(analysis.confidence || "unknown")}: `),
      analysis.category),
    analysis.evidence_basis ? el("p", { class: "hint" }, analysis.evidence_basis) : null,
    el("p", {}, analysis.summary || ""),
    analysis.advice ? el("p", { class: "hint" }, analysis.advice) : null,
    analysis.suspect_mods && analysis.suspect_mods.length
      ? el("p", {}, "Installed mods mentioned in the log: ",
          el("span", { class: "mono" }, analysis.suspect_mods.join(", ")),
          el("span", { class: "hint" },
            " - appearing in a stack trace is not evidence of causing the crash"))
      : null,
    el("h3", { class: "evidence-heading" }, "Evidence"),
    el("div", { class: "console-wrap compact" },
      (crash.evidence || []).map((line) => el("div", { class: "console-line ERROR" }, line))),
    el("h3", { class: "evidence-heading" }, "Context"),
    table(["Field", "Value"], [
      ["Exit code", String(crash.exit_code)],
      ["Minecraft", context.minecraft_version || "unknown"],
      ["Fabric loader", context.fabric_loader || "unknown"],
      ["Java", context.java_version || "unknown"],
      ["Players online", (context.players_online || []).join(", ") || "none"],
      ["Crash report", context.crash_report || "none written by Minecraft"],
      ["Saved log", context.log_file || context.console_file || "—"],
    ]),
    el("p", { class: "hint mt-12" },
      "This is a rule match on the log text, not a certainty. Check the evidence before acting."));
  await confirmDialog({ title: `Crash on ${fmt.time(crash.ts)}`, body, acknowledge: true });
}
