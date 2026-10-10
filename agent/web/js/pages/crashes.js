import { api } from "../api.js";
import { getHelp } from "./app-settings.js";
import { CAUSES, can, renderers } from "../state.js";
import { t, technical } from "../strings.js";
import { advanced, card, confirmDialog, detailRows, el, emptyState, fmt, known, loadInto, table } from "../ui.js";

const CONFIDENCE = { confirmed: ["error", "crashes.conf_confirmed"], likely: ["warn", "crashes.conf_likely"],
  possible: ["off", "crashes.conf_possible"], unknown: ["off", "crashes.conf_unknown"] };

/* The crash cause in words; the analyzer's own name in Technical mode. */
export function causeText(category) {
  if (!category || category === "Unknown") return t("crashes.cause_unknown");
  if (technical() || !CAUSES.includes(category)) return category;
  const text = t(`cause.${category}`);
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function confidenceTag(confidence) {
  const [tone, key] = CONFIDENCE[confidence] || CONFIDENCE.unknown;
  return el("span", { class: `tag ${tone}` }, t(key));
}

/* "Get help": the zip of logs and checks to send to whoever is helping. */
function helpRow() {
  if (!can("help.bundle")) return null;
  return el("div", { class: "btn-row mt-12" },
    el("button", { class: "btn", type: "button", onclick: (e) => getHelp(e.currentTarget) }, t("gethelp.button")),
    el("span", { class: "hint" }, t("gethelp.crash_hint")));
}

renderers.crashes = (page) => loadInto(page, async () => {
  const data = await api("/crashes");
  if (!data.crashes.length) return card(t("crashes.title"), emptyState(t("crashes.none")), helpRow());
  const code = technical();
  return card(t("crashes.title"), table(
    [t("crashes.col_when"), ...(code ? [t("crashes.col_code")] : []), t("crashes.col_cause"),
      t("crashes.col_confidence"), ""],
    data.crashes.map((crash) => [
      fmt.time(crash.ts),
      ...(code ? [known(crash.exit_code) ? el("span", { class: "mono" }, String(crash.exit_code))
        : el("span", { class: "unknown-note" }, t("value.unknown"))] : []),
      causeText(crash.category),
      confidenceTag(crash.confidence),
      el("button", { class: "btn small", type: "button", onclick: () => showCrash(crash.id) }, t("crashes.details")),
    ])), helpRow());
});

export async function showCrash(id) {
  const crash = await api(`/crashes/${id}`);
  const context = crash.context || {};
  const analysis = context.analysis || {};
  const evidence = el("div", { class: "console-wrap compact" },
    (crash.evidence || []).map((line) => el("div", { class: "console-line ERROR" }, line)));
  const details = detailRows([
    [t("crashes.f_code"), known(crash.exit_code) ? String(crash.exit_code) : null, true],
    [t("crashes.f_minecraft"), context.minecraft_version || null],
    [t("crashes.f_loader"), context.fabric_loader || null],
    [t("crashes.f_java"), context.java_version || null],
    [t("crashes.f_players"), (context.players_online || []).join(", ") || t("crashes.no_players")],
    [t("crashes.f_report"), context.crash_report || t("crashes.no_report"), Boolean(context.crash_report)],
    [t("crashes.f_log"), context.log_file || context.console_file || null, true],
  ]);
  const body = el("div", {},
    el("p", {}, confidenceTag(analysis.confidence), " ", el("strong", {}, causeText(analysis.category))),
    analysis.summary ? el("p", {}, analysis.summary) : null,
    analysis.advice ? el("p", { class: "hint" }, analysis.advice) : null,
    analysis.suspect_mods && analysis.suspect_mods.length
      ? el("p", {}, t("crashes.suspect_mods"),
          el("span", { class: "mono" }, analysis.suspect_mods.join(", ")),
          el("span", { class: "hint" }, t("crashes.suspect_hint")))
      : null,
    technical() && analysis.evidence_basis ? el("p", { class: "hint" }, analysis.evidence_basis) : null,
    advanced(t("crashes.evidence"), evidence),
    advanced(t("crashes.context"), details),
    el("p", { class: "hint mt-12" }, t("crashes.rule_match")));
  await confirmDialog({ title: t("crashes.dialog_title", { when: fmt.time(crash.ts) }), body, acknowledge: true });
}
