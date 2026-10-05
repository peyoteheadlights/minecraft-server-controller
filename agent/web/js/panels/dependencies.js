/* Dependencies panel on the Mods page. */

import { api } from "../api.js";
import { render as renderPage } from "../nav.js";
import { t, tn } from "../strings.js";
import { busy, card, confirmDialog, el, fmt, toast } from "../ui.js";

const STATUS = {
  missing: "error", incompatible: "warn", disabled: "warn", platform_incompatible: "error",
  unverified: "off", satisfied: "ok", platform_ok: "ok",
};
const NEEDS_ATTENTION = ["missing", "incompatible", "disabled", "platform_incompatible"];

export function dependenciesPanel(node, opts = {}) {
  node.append(el("div", { class: "empty", "aria-busy": "true" }, t("deps.checking")));
  load();

  function load() {
    api("/mods/dependencies")
      .then((report) => node.replaceChildren(render(report)))
      .catch((err) => node.replaceChildren(el("div", { class: "banner error", role: "alert" },
        el("div", { class: "grow" }, el("strong", {}, t("deps.check_failed")), " ", err.message))));
  }

  function requiredBy(item) {
    const names = [...new Set(item.required_by.map((r) => r.name))];
    if (names.length === 1) return names[0];
    if (names.length === 2) return t("deps.two_names", { a: names[0], b: names[1] });
    return t("deps.many_names", { a: names[0], b: names[1], n: names.length - 2 });
  }

  function itemRow(item) {
    const tag = STATUS[item.status] || "off";
    const label = STATUS[item.status] ? t(`deps.status_${item.status}`) : item.status;
    const page = item.modrinth && item.modrinth.page;
    const canInstall = item.status === "missing" && item.kind === "required";
    return el("div", { class: "dep-item" },
      el("div", { class: "dep-main" },
        el("div", { class: "dep-title" }, el("strong", {}, item.name),
          el("span", { class: `tag ${tag}` }, label),
          item.kind === "optional" ? el("span", { class: "tag off" }, t("deps.optional")) : null),
        el("div", { class: "dep-meta" },
          t(item.kind === "optional" ? "deps.recommended_by" : "deps.required_by", { names: requiredBy(item) }), " ",
          t("deps.version", { range: item.range_text }),
          item.installed_version ? ` ${t("deps.installed_version", { version: item.installed_version })}` : ""),
        item.reason ? el("div", { class: "dep-meta" }, item.reason) : null,
        item.modrinth && item.modrinth.not_found
          ? el("div", { class: "dep-meta" }, t("deps.not_on_modrinth"))
          : null),
      el("div", { class: "btn-row" },
        canInstall ? el("button", {
          class: "btn small", type: "button", disabled: !opts.offline,
          title: opts.offline ? "" : t("mods.stop_first_short"),
          onclick: (e) => install([item.mod_id], e.currentTarget),
        }, t("mods.install")) : null,
        page ? el("a", { class: "btn plain small", href: page, target: "_blank", rel: "noopener noreferrer" },
          t("deps.view_on_modrinth")) : null));
  }

  function render(report) {
    const attention = report.items.filter((i) => NEEDS_ATTENTION.includes(i.status) && i.kind === "required");
    const optional = report.items.filter((i) => i.kind === "optional" && i.status === "missing");
    const missingCount = attention.filter((i) => i.status === "missing").length;
    const wrap = el("div", { class: "dep-panel" });

    if (report.lookup_error) wrap.append(el("div", { class: "banner" }, report.lookup_error));

    if (!attention.length) {
      wrap.append(el("p", { class: "hint dep-ok" }, t("deps.all_ok"), " ", report.note));
    } else {
      const header = el("div", { class: "dep-head" },
        el("div", { class: "grow" },
          el("strong", {}, missingCount ? tn("deps.missing", missingCount) : t("deps.problems")),
          el("div", { class: "hint" }, report.note)),
        missingCount ? el("button", {
          class: "btn primary small", type: "button", disabled: !opts.offline,
          title: opts.offline ? "" : t("mods.stop_first_short"),
          onclick: (e) => install(null, e.currentTarget),
        }, t("deps.install_missing", { n: missingCount })) : null);
      wrap.append(card(t("deps.title"), header, el("div", { class: "dep-list" }, attention.map(itemRow))));
    }

    if (optional.length) {
      wrap.append(card(t("deps.optional_title", { n: optional.length }),
        el("p", { class: "hint mt-0" }, t("deps.optional_hint")),
        el("div", { class: "dep-list" }, optional.map(itemRow))));
    }
    return wrap;
  }

  function planView(plan) {
    const body = el("div");
    if (plan.items.length) {
      body.append(el("p", {}, t("deps.plan_intro")));
      const shallowFirst = [...plan.items].sort((a, b) => a.depth - b.depth);
      body.append(el("ul", { class: "dep-plan" }, shallowFirst.map((item) => el("li", {
        style: { marginLeft: `${item.depth * 18}px` },
      },
        item.depth ? "└ " : "",
        el("strong", {}, item.title), ` ${item.version_number}`,
        item.size ? el("span", { class: "hint" }, ` (${fmt.bytes(item.size)})`) : null,
        el("div", { class: "hint" },
          t("deps.needed_by", { names: item.required_by.join(", ") }), " ",
          t("deps.version", { range: item.range_text }),
          item.range_verified === null ? ` ${t("deps.range_unchecked")}` : "")))));
    } else {
      body.append(el("p", {}, t("deps.nothing_automatic")));
    }
    if (plan.unresolvable.length) {
      body.append(el("p", {}, el("strong", {}, t("deps.not_automatic"))));
      body.append(el("ul", {}, plan.unresolvable.map((u) => el("li", {},
        el("strong", {}, u.name || u.mod_id), ` - ${u.reason}`))));
    }
    if (plan.skipped.length) {
      body.append(el("p", { class: "hint" }, t("deps.already_installed", { names: plan.skipped.map((s) => s.name).join(", ") })));
    }
    body.append(el("p", { class: "hint" }, t("deps.plan_safety")));
    return body;
  }

  async function install(modIds, button) {
    if (!opts.offline) {
      toast(t("mods.stop_first"), "warn");
      return;
    }
    let plan;
    try {
      plan = await busy(button, t("deps.planning"), () =>
        api("/mods/dependencies/plan", { method: "POST", body: { mod_ids: modIds } }));
    } catch (err) {
      toast(t("deps.plan_failed", { error: err.message }), "error", 9000);
      return;
    }
    if (!plan.items.length) {
      await confirmDialog({ title: t("deps.nothing_title"), body: planView(plan), acknowledge: true });
      return;
    }
    const ok = await confirmDialog({
      title: tn("deps.install_title", plan.items.length),
      body: planView(plan),
      confirmLabel: t("deps.install_confirm", { n: plan.items.length }),
      wide: true,
    });
    if (!ok) return;
    try {
      const result = await busy(button, t("deps.installing"), () =>
        api("/mods/dependencies/install", { method: "POST", body: { mod_ids: modIds } }));
      const installed = result.results.filter((r) => r.result === "installed");
      const failed = result.results.filter((r) => r.result === "failed");
      if (installed.length) {
        toast(t("deps.installed_toast", { names: installed.map((r) => r.title).join(", ") }), "success", 9000);
      }
      failed.forEach((r) => toast(t("deps.failed_toast", { name: r.title, error: r.detail }), "error", 12000));
      if (result.still_missing.length) {
        toast(t("deps.still_missing", { names: result.still_missing.map((g) => g.name).join(", ") }), "warn", 12000);
      }
    } catch (err) {
      toast(t("deps.install_failed", { error: err.message }), "error", 12000);
    }
    renderPage();
  }
}
