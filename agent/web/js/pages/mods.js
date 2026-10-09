import { api } from "../api.js";
import { render } from "../nav.js";
import { dependenciesPanel } from "../panels/dependencies.js";
import { modpackPanel } from "../panels/modpack.js";
import { serverRow } from "../servers.js";
import { addonsPage } from "./addons.js";
import { serverAction } from "./overview.js";
import { renderers, stateInfo, state } from "../state.js";
import { t, technical, tn } from "../strings.js";
import { $, advanced, busy, card, confirmDialog, el, emptyState, fmt, loadInto, section, table, toast } from "../ui.js";

const STATUS = { ok: ["ok", "mods.status_ok"], warn: ["warn", "mods.status_warn"],
  error: ["error", "mods.status_error"], disabled: ["off", "mods.status_off"] };

function modStatus(mod) {
  const [tag, key] = STATUS[mod.enabled ? mod.status : "disabled"] || ["off", "mods.status_off"];
  const issue = (mod.issues || [])[0];
  return el("span", { class: `tag ${tag}`, title: issue ? issue.detail || "" : "" }, t(key));
}

function installedTable(data, offline) {
  const headers = [t("mods.col_mod"), t("mods.col_version"),
    ...(technical() ? [t("mods.col_minecraft")] : []), t("mods.col_status"), ""];
  return table(headers, data.mods.map((mod) => [
    el("div", {}, el("strong", {}, mod.name),
      technical() ? el("div", { class: "hint mono" }, mod.mod_id) : null,
      mod.update_available
        ? el("div", { class: "hint" }, t("mods.update_to", { version: mod.update_available.latest_version }))
        : null),
    el("span", { class: "mono" }, mod.version || "—"),
    ...(technical() ? [el("span", { class: "mono" }, mod.minecraft_range || "—")] : []),
    modStatus(mod),
    el("div", { class: "btn-row" },
      mod.update_available
        ? el("button", { class: "btn small", type: "button", disabled: !offline,
            onclick: () => updateMod(mod) }, t("mods.update"))
        : null,
      el("button", {
        class: "btn small", type: "button", disabled: !offline,
        onclick: (e) => busy(e.currentTarget, t("action.saving"), async () => {
          try {
            await api(mod.enabled ? "/mods/disable" : "/mods/enable",
              { method: "POST", body: { filename: mod.filename } });
            toast(t(mod.enabled ? "mods.turned_off" : "mods.turned_on", { name: mod.name }), "success");
            render();
          } catch (err) { toast(err.message, "error"); }
        }),
      }, mod.enabled ? t("mods.turn_off") : t("mods.turn_on")),
      el("button", { class: "btn small", type: "button", onclick: () => showVersions(mod) }, t("mods.history")),
      el("button", { class: "btn small danger", type: "button", disabled: !offline,
        onclick: () => removeMod(mod) }, t("mods.remove"))),
  ]));
}

function searchCard(data, offline) {
  const search = el("input", { type: "search", placeholder: t("mods.search_placeholder"),
    "aria-label": t("mods.search_label"), class: "input grow-input" });
  const results = el("div", { class: "mt-12" });
  const run = async (button) => busy(button, t("mods.searching"), async () => {
    results.replaceChildren();
    try {
      const found = await api(`/mods/search?q=${encodeURIComponent(search.value)}&limit=10`);
      if (!found.hits.length) { results.append(emptyState(t("mods.nothing_found"))); return; }
      results.append(table([t("mods.col_mod"), t("mods.col_downloads"), ""], found.hits.map((hit) => [
        el("div", {}, el("strong", {}, hit.title),
          el("div", { class: "hint" }, (hit.description || "").slice(0, 110))),
        el("span", { class: "num" }, Number(hit.downloads).toLocaleString()),
        el("button", { class: "btn small", type: "button", disabled: !offline,
          title: offline ? "" : t("mods.stop_first_short"), onclick: () => installMod(hit) }, t("mods.install")),
      ])));
    } catch (err) {
      results.append(el("div", { class: "banner error" }, err.message));
    }
  });
  const button = el("button", { class: "btn primary", type: "button", onclick: (e) => run(e.currentTarget) },
    t("mods.search"));
  search.addEventListener("keydown", (e) => { if (e.key === "Enter") run(button); });
  // A suggestion (such as "Install spark") opens this page with its search.
  if (state.modSearch) {
    search.value = state.modSearch;
    state.modSearch = null;
    setTimeout(() => run(button), 0);
  }
  return card(t("mods.add"),
    el("div", { class: "btn-row" }, search, button),
    results,
    el("p", { class: "hint mt-10" }, t("mods.search_hint", { version: data.minecraft_version || t("value.unknown") })));
}

renderers.mods = (page) => {
  // A Bedrock server's add-ons are packs, on a page of their own.
  if ((serverRow() || {}).edition === "bedrock") return addonsPage(page);
  return modsPage(page);
};

const modsPage = (page) => loadInto(page, async () => {
  const data = await api("/mods");
  const holder = el("div", { class: "stack" });
  const offline = data.server_state === "OFFLINE" || data.server_state === "CRASHED";

  if (!offline) {
    holder.append(el("div", { class: "banner" },
      el("div", { class: "grow" }, t("mods.running_notice", {
        state: t(stateInfo(data.server_state).label).replace("…", "").toLowerCase() })),
      data.server_state === "ONLINE"
        ? el("button", { class: "btn small", type: "button", onclick: (e) => serverAction("stop", e.currentTarget) },
          t("action.stop"))
        : null));
  }
  const others = data.problems.filter((p) => !["missing_dependency", "dependency_version"].includes(p.kind));
  if (others.length) {
    holder.append(el("div", { class: "banner error" }, el("div", { class: "grow" },
      el("strong", {}, tn("mods.problems", others.length)),
      el("ul", {}, others.slice(0, 6).map((p) => el("li", {}, p.detail))))));
  }
  const depPanel = el("div");
  holder.append(depPanel);
  dependenciesPanel(depPanel, { offline });

  holder.append(section(tn("mods.installed", data.mods.length), null, !data.mods.length
    ? emptyState(t("mods.none"), t("mods.none_hint"))
    : installedTable(data, offline)));
  holder.append(searchCard(data, offline));
  holder.append(modpackPanel("into", () => render()));
  holder.append(advanced(t("mods.about_checks"),
    el("p", { class: "hint mt-0" }, `${data.claim || ""}. ${data.claim_note || ""}`),
    el("p", { class: "hint" }, t("mods.limits", { limits: data.limitations.join(" ") }))));
  const history = el("div");
  holder.append(advanced(t("mods.change_history"), history));
  modHistory().then((node) => history.replaceChildren(node)).catch((err) => history.replaceChildren(err.message));
  return holder;
});

export async function modHistory() {
  const data = await api("/mods/history?limit=25");
  return data.history.length
    ? table([t("mods.col_when"), t("mods.col_who"), t("mods.col_action"), t("mods.col_mod"), t("mods.col_change"), t("mods.col_result")],
      data.history.map((h) => [
        fmt.time(h.ts), h.user || "—", h.action, h.mod_name || h.mod_id || "—",
        h.old_version || h.new_version ? `${h.old_version || "—"} → ${h.new_version || "—"}` : "—",
        el("span", { class: `tag ${h.result === "ok" ? "ok" : "error"}` }, h.result),
      ]))
    : emptyState(t("mods.no_history"));
}

export async function installMod(hit) {
  let detail;
  try { detail = await api(`/mods/project/${hit.slug}`); }
  catch (err) { toast(err.message, "error"); return; }
  const latest = detail.versions[0];
  if (!latest) { toast(t("mods.no_build"), "error"); return; }
  const deps = latest.dependencies.filter((d) => d.type === "required");
  const installDeps = el("input", { type: "checkbox", checked: "checked" });
  const body = el("div", {},
    el("p", {}, t("mods.install_what", { name: detail.project.title, version: latest.version_number })),
    el("ul", {},
      el("li", {}, t("mods.install_size", { size: fmt.bytes(latest.file.size) })),
      el("li", {}, t("mods.install_minecraft", { versions: latest.game_versions.join(", ") })),
      technical() ? el("li", {}, t("mods.install_file", { file: latest.file.filename })) : null,
      technical() ? el("li", {}, t("mods.install_side", { side: detail.project.server_side })) : null,
      technical() ? el("li", {}, t("mods.install_licence", { licence: detail.project.license || t("value.unknown") })) : null),
    deps.length
      ? el("label", { class: "check-row" }, installDeps, tn("mods.install_deps", deps.length))
      : null,
    el("p", { class: "hint" }, t("mods.install_checked")));
  const ok = await confirmDialog({ title: t("mods.install_title"), body, confirmLabel: t("mods.install_confirm") });
  if (!ok) return;
  try {
    const result = await api("/mods/install", {
      method: "POST",
      body: { project: hit.slug, version_id: latest.version_id, install_dependencies: deps.length > 0 && installDeps.checked },
    });
    toast(t("mods.installed_toast", { name: result.installed.name, version: result.installed.version }), "info", 9000);
    if (result.dependencies_required.some((d) => !d.installed) && !installDeps.checked) {
      toast(t("mods.deps_missing"), "warn", 9000);
    }
    render();
  } catch (err) { toast(err.message, "error", 9000); }
}

export async function updateMod(mod) {
  const ok = await confirmDialog({
    title: t("mods.update_title", { name: mod.name }),
    // Built from text nodes, not an HTML string: version strings come from
    // a mod's own metadata and must never be parsed as markup.
    body: el("div", {},
      el("p", {}, `${mod.version} → ${mod.update_available.latest_version}`),
      el("p", { class: "hint" }, t("mods.update_archived"))),
    confirmLabel: t("mods.update"),
  });
  if (!ok) return;
  try {
    const result = await api("/mods/update", {
      method: "POST",
      body: { filename: mod.filename, version_id: mod.update_available.version_id },
    });
    toast(t("mods.updated_toast", { version: result.updated.version }), "info", 9000);
    render();
  } catch (err) { toast(err.message, "error", 9000); }
}

export async function removeMod(mod) {
  let impact;
  try { impact = await api(`/mods/impact?filename=${encodeURIComponent(mod.filename)}`); }
  catch (err) { toast(err.message, "error"); return; }
  const body = el("div", {},
    impact.warning ? el("div", { class: "banner error" }, impact.warning) : null,
    impact.dependents.length
      ? el("ul", {}, impact.dependents.map((d) => el("li", {}, t("mods.needed_by", { name: d.name, requires: d.requires }))))
      : el("p", {}, t("mods.not_needed")),
    el("p", { class: "hint" }, t("mods.remove_kept")));
  const ok = await confirmDialog({
    title: t("mods.remove_title", { name: mod.name }), body, confirmLabel: t("mods.remove"), danger: true,
  });
  if (!ok) return;
  try {
    await api("/mods/remove", { method: "POST", body: { filename: mod.filename } });
    toast(t("mods.removed_toast", { name: mod.name }), "success");
    render();
  } catch (err) { toast(err.message, "error"); }
}

export async function showVersions(mod) {
  const data = await api(`/mods/versions/${encodeURIComponent(mod.mod_id)}`);
  const body = data.versions.length
    ? table([t("mods.col_version"), t("mods.col_saved"), ""], data.versions.map((v) => [
        el("span", { class: "mono" }, v.version || "—"),
        fmt.time(v.created_at),
        v.is_current ? el("span", { class: "tag ok" }, t("mods.current"))
          : !v.exists ? el("span", { class: "tag error" }, t("mods.file_missing"))
            : el("button", {
              class: "btn small", type: "button",
              onclick: async () => {
                $("#modal-root").replaceChildren();
                const ok = await confirmDialog({
                  title: t("mods.rollback_title", { version: v.version }),
                  body: t("mods.rollback_body"),
                  confirmLabel: t("mods.rollback"), danger: true,
                });
                if (!ok) return;
                try {
                  await api("/mods/rollback", { method: "POST", body: { mod_id: mod.mod_id, archive_path: v.archive_path } });
                  toast(t("mods.rolled_back", { version: v.version }), "success");
                  render();
                } catch (err) { toast(err.message, "error"); }
              },
            }, t("mods.rollback")),
      ]))
    : emptyState(t("mods.no_versions"));
  await confirmDialog({ title: t("mods.versions_title", { name: mod.name }), body, acknowledge: true });
}
