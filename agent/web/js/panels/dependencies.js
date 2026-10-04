/* Dependencies panel on the Mods page. */

import { api } from "../api.js";
import { render as renderPage } from "../nav.js";
import { busy, card, confirmDialog, el, fmt, toast } from "../ui.js";

const STATUS = {
  missing: { tag: "error", text: "Missing" },
  incompatible: { tag: "warn", text: "Wrong version" },
  disabled: { tag: "warn", text: "Disabled" },
  platform_incompatible: { tag: "error", text: "Incompatible" },
  unverified: { tag: "off", text: "Not checked" },
  satisfied: { tag: "ok", text: "Installed" },
  platform_ok: { tag: "ok", text: "OK" },
};
const NEEDS_ATTENTION = ["missing", "incompatible", "disabled", "platform_incompatible"];

export function dependenciesPanel(node, opts = {}) {
  node.append(el("div", { class: "empty", "aria-busy": "true" }, "Checking dependencies…"));
  load();

  function load() {
    api("/mods/dependencies")
      .then((report) => node.replaceChildren(render(report)))
      .catch((err) => node.replaceChildren(el("div", { class: "banner error", role: "alert" },
        el("div", { class: "grow" }, el("strong", {}, "Dependencies could not be checked. "), err.message))));
  }

  function requiredBy(item) {
    const names = [...new Set(item.required_by.map((r) => r.name))];
    return names.length <= 2 ? names.join(" and ") : `${names.slice(0, 2).join(", ")} and ${names.length - 2} more`;
  }

  function itemRow(item) {
    const status = STATUS[item.status] || { tag: "off", text: item.status };
    const page = item.modrinth && item.modrinth.page;
    const canInstall = item.status === "missing" && item.kind === "required";
    return el("div", { class: "dep-item" },
      el("div", { class: "dep-main" },
        el("div", { class: "dep-title" }, el("strong", {}, item.name),
          el("span", { class: `tag ${status.tag}` }, status.text),
          item.kind === "optional" ? el("span", { class: "tag off" }, "Optional") : null),
        el("div", { class: "dep-meta" },
          `${item.kind === "optional" ? "Recommended" : "Required"} by ${requiredBy(item)}. `,
          `Version: ${item.range_text}.`,
          item.installed_version ? ` Installed: ${item.installed_version}.` : ""),
        item.reason ? el("div", { class: "dep-meta" }, item.reason) : null,
        item.modrinth && item.modrinth.not_found
          ? el("div", { class: "dep-meta" }, "Not found on Modrinth. It may need to be installed by hand.")
          : null),
      el("div", { class: "btn-row" },
        canInstall ? el("button", {
          class: "btn small", type: "button", disabled: !opts.offline,
          title: opts.offline ? "" : "Stop the server before installing mods",
          onclick: (e) => install([item.mod_id], e.currentTarget),
        }, "Install") : null,
        page ? el("a", { class: "btn plain small", href: page, target: "_blank", rel: "noopener noreferrer" },
          "View on Modrinth") : null));
  }

  function render(report) {
    const attention = report.items.filter((i) => NEEDS_ATTENTION.includes(i.status) && i.kind === "required");
    const optional = report.items.filter((i) => i.kind === "optional" && i.status === "missing");
    const missingCount = attention.filter((i) => i.status === "missing").length;
    const wrap = el("div", { class: "dep-panel" });

    if (report.lookup_error) wrap.append(el("div", { class: "banner" }, report.lookup_error));

    if (!attention.length) {
      wrap.append(el("p", { class: "hint dep-ok" },
        "All declared dependencies are installed. ", report.note));
    } else {
      const header = el("div", { class: "dep-head" },
        el("div", { class: "grow" },
          el("strong", {}, missingCount ? `Missing ${missingCount === 1 ? "dependency" : "dependencies"}` : "Dependency problems"),
          el("div", { class: "hint" }, report.note)),
        missingCount ? el("button", {
          class: "btn primary small", type: "button", disabled: !opts.offline,
          title: opts.offline ? "" : "Stop the server before installing mods",
          onclick: (e) => install(null, e.currentTarget),
        }, `Install Missing Dependencies (${missingCount})`) : null);
      wrap.append(card("Dependencies", header, el("div", { class: "dep-list" }, attention.map(itemRow))));
    }

    if (optional.length) {
      wrap.append(card(`Optional dependencies (${optional.length})`,
        el("p", { class: "hint mt-0" },
          "Mods work without these, but may offer more with them."),
        el("div", { class: "dep-list" }, optional.map(itemRow))));
    }
    return wrap;
  }

  function planView(plan) {
    const body = el("div");
    if (plan.items.length) {
      body.append(el("p", {}, "These will be downloaded from Modrinth and checked against their published checksums:"));
      const shallowFirst = [...plan.items].sort((a, b) => a.depth - b.depth);
      body.append(el("ul", { class: "dep-plan" }, shallowFirst.map((item) => el("li", {
        style: { marginLeft: `${item.depth * 18}px` },
      },
        item.depth ? "└ " : "",
        el("strong", {}, item.title), ` ${item.version_number}`,
        item.size ? el("span", { class: "hint" }, ` (${fmt.bytes(item.size)})`) : null,
        el("div", { class: "hint" },
          `Needed by ${item.required_by.join(", ")}. Version: ${item.range_text}.`,
          item.range_verified === null ? " The range could not be checked against this version." : "")))));
    } else {
      body.append(el("p", {}, "Nothing can be downloaded automatically."));
    }
    if (plan.unresolvable.length) {
      body.append(el("p", {}, el("strong", {}, "Not installed automatically:")));
      body.append(el("ul", {}, plan.unresolvable.map((u) => el("li", {},
        el("strong", {}, u.name || u.mod_id), ` - ${u.reason}`))));
    }
    if (plan.skipped.length) {
      body.append(el("p", { class: "hint" }, `Already installed: ${plan.skipped.map((s) => s.name).join(", ")}.`));
    }
    body.append(el("p", { class: "hint" }, "Existing mods are not replaced. Each download is archived and can be rolled back."));
    return body;
  }

  async function install(modIds, button) {
    if (!opts.offline) {
      toast("Stop the server before installing mods.", "warn");
      return;
    }
    let plan;
    try {
      plan = await busy(button, "Checking…", () =>
        api("/mods/dependencies/plan", { method: "POST", body: { mod_ids: modIds } }));
    } catch (err) {
      toast(`The installation could not be planned. ${err.message}`, "error", 9000);
      return;
    }
    if (!plan.items.length) {
      await confirmDialog({ title: "Nothing to install automatically", body: planView(plan), confirmLabel: "Close" });
      return;
    }
    const ok = await confirmDialog({
      title: `Install ${plan.items.length} ${plan.items.length === 1 ? "mod" : "mods"}?`,
      body: planView(plan),
      confirmLabel: `Install ${plan.items.length}`,
      wide: true,
    });
    if (!ok) return;
    try {
      const result = await busy(button, "Installing…", () =>
        api("/mods/dependencies/install", { method: "POST", body: { mod_ids: modIds } }));
      const installed = result.results.filter((r) => r.result === "installed");
      const failed = result.results.filter((r) => r.result === "failed");
      if (installed.length) {
        toast(`Installed ${installed.map((r) => r.title).join(", ")}. `
          + "Loaded by Minecraft: not verified until the server starts.", "success", 9000);
      }
      failed.forEach((r) => toast(`${r.title} could not be installed. ${r.detail}`, "error", 12000));
      if (result.still_missing.length) {
        toast(`Still missing: ${result.still_missing.map((g) => g.name).join(", ")}.`, "warn", 12000);
      }
    } catch (err) {
      toast(`Dependencies could not be installed. ${err.message}`, "error", 12000);
    }
    renderPage();
  }
}
