/* One server's kind and version, on its Settings page: what it is now,
   what a change would do, the change itself, and going back.

   Two honesty rules show through here. The version shown is the one this
   server's own console printed - "Not seen yet" until it starts, never the
   name of a jar or the version somebody picked. And a change says what it
   will do before it does it: the server stops, a backup is taken and
   checked, and the files it replaces are kept so one button puts them back. */

import { api } from "../api.js";
import { state } from "../state.js";
import { t, technical } from "../strings.js";
import { busy, card, confirmDialog, detailRows, el, icon, known, problem, toast } from "../ui.js";

const serverUrl = (path) => `/servers/${encodeURIComponent(state.serverId)}${path}`;

/* The mods or plugins a change would move aside, in plain words. Nothing
   is deleted: files go to the mod trash, where they can be put back. */
function contentWarning(report) {
  const aside = report.moved_aside || [];
  const unknown = report.unknown_support || [];
  if (!aside.length && !unknown.length) return null;
  return el("div", { class: "stack" },
    aside.length
      ? el("div", { class: "banner warn" }, el("div", { class: "grow" },
          t("version.moved_aside", { count: aside.length }),
          el("p", { class: "hint mt-0 mono" }, aside.slice(0, 8).join(", ")),
          el("p", { class: "hint mt-0" }, t("version.moved_aside_note"))))
      : null,
    unknown.length
      ? el("div", { class: "banner" }, el("div", { class: "grow" },
          t("version.unknown_support", { count: unknown.length }),
          el("p", { class: "hint mt-0" }, t("version.unknown_support_note"))))
      : null);
}

/* What the preflight found, before anything is changed. */
function preflightReport(report) {
  const java = report.java || {};
  return el("div", { class: "stack preflight" },
    detailRows([
      [t("version.now"), report.current.observed
        ? `${report.current.type_name} ${report.current.minecraft_version}`
        : null],
      [t("version.after"), `${report.target.type_name} ${report.target.minecraft_version}`],
      [t("version.java_needed"), report.java_required ? `Java ${report.java_required}` : null],
      technical() ? [t("version.java_here"), java.detail || null] : null,
    ]),
    report.downgrade_warning
      ? el("div", { class: "banner warn" }, el("div", { class: "grow" }, t("version.downgrade")))
      : null,
    report.type_change && !report.gentle_type_change
      ? el("div", { class: "banner warn" }, el("div", { class: "grow" },
          t("version.type_change", { from: report.current.type_name, to: report.target.type_name })))
      : null,
    report.type_change && report.gentle_type_change
      ? el("div", { class: "banner" }, el("div", { class: "grow" }, t("version.type_change_gentle")))
      : null,
    java.verdict === "incompatible"
      ? el("div", { class: "banner error" }, el("div", { class: "grow" }, java.detail))
      : null,
    java.verdict === "unknown"
      ? el("div", { class: "banner" }, el("div", { class: "grow" }, t("version.java_unknown")))
      : null,
    report.crossplay && !report.crossplay_available
      ? el("div", { class: "banner warn" }, el("div", { class: "grow" }, t("version.crossplay_lost")))
      : null,
    contentWarning(report),
    el("p", { class: "hint" }, t("version.backup_first")));
}

export function versionCard(current, afterChange) {
  const body = el("div", { class: "stack" });
  const typeSelect = el("select", { id: "version-type" });
  const versionSelect = el("select", { id: "version-pick" });
  const loaderSelect = el("select", { id: "version-loader" });
  const snapshots = el("input", { type: "checkbox", id: "version-snapshots" });
  const checkBox = el("div", {});
  let payload = null;
  let report = null;

  const pending = current.pending_version;
  const change = current.last_change;

  function versionRows() {
    if (!payload) return;
    const list = snapshots.checked ? payload.versions : payload.versions.filter((v) => v.stable);
    const keep = versionSelect.value;
    versionSelect.replaceChildren(...list.map((v) => el("option", {
      value: v.minecraft,
      selected: v.minecraft === (keep || payload.latest_stable) ? "selected" : false,
    }, v.stable ? v.minecraft : t("new.snapshot_option", { version: v.minecraft }))));
    loaderRows();
  }

  function loaderRows() {
    const entry = (payload.versions || []).find((v) => v.minecraft === versionSelect.value);
    const loaders = (entry && entry.loaders) || [];
    loaderSelect.replaceChildren(...loaders.map((v, i) =>
      el("option", { value: v, selected: i === 0 ? "selected" : false }, v)));
    loaderSelect.closest(".field").hidden = !loaders.length || !technical();
    checkBox.replaceChildren();
    report = null;
  }

  async function loadVersions() {
    checkBox.replaceChildren();
    report = null;
    versionSelect.replaceChildren(el("option", {}, t("status.loading")));
    try {
      payload = await api(`/server-types/${typeSelect.value}/versions`);
    } catch (err) {
      checkBox.replaceChildren(problem(err.message));
      return;
    }
    snapshots.closest("label").hidden = !payload.snapshots;
    versionRows();
  }

  async function check(button) {
    await busy(button, t("version.checking"), async () => {
      try {
        report = await api(serverUrl("/version/preflight"), {
          method: "POST",
          body: {
            type: typeSelect.value,
            minecraft_version: versionSelect.value,
            loader_version: loaderSelect.value || null,
          },
        });
        checkBox.replaceChildren(preflightReport(report));
      } catch (err) {
        report = null;
        checkBox.replaceChildren(problem(err.message));
      }
    });
  }

  async function apply(button) {
    if (!report) { toast(t("version.check_first"), "warn"); return; }
    const ok = await confirmDialog({
      title: t("version.confirm_title", {
        name: `${report.target.type_name} ${report.target.minecraft_version}`,
      }),
      body: t("version.confirm_body"),
      confirmLabel: t("version.confirm_button"),
      danger: report.downgrade_warning || (report.type_change && !report.gentle_type_change),
    });
    if (!ok) return;
    await busy(button, t("version.changing"), async () => {
      try {
        const result = await api(serverUrl("/version"), {
          method: "POST",
          body: {
            type: typeSelect.value,
            minecraft_version: versionSelect.value,
            loader_version: loaderSelect.value || null,
            confirm: true,
          },
        });
        toast(t("version.changed", {
          version: `${report.target.type_name} ${report.target.minecraft_version}`,
        }), "success", 11000);
        if (result.verified === false) toast(t("new.unverified"), "warn", 12000);
        if (afterChange) await afterChange();
      } catch (err) {
        toast(err.message, "error", 14000);
      }
    });
  }

  async function rollBack(button) {
    const ok = await confirmDialog({
      title: t("version.back_title"),
      body: t("version.back_body"),
      confirmLabel: t("version.back_button"),
    });
    if (!ok) return;
    await busy(button, t("version.going_back"), async () => {
      try {
        await api(serverUrl("/version/roll-back"), { method: "POST" });
        toast(t("version.went_back"), "success", 9000);
        if (afterChange) await afterChange();
      } catch (err) { toast(err.message, "error", 14000); }
    });
  }

  typeSelect.replaceChildren(...(state.serverTypes || []).map((type) => el("option", {
    value: type.id, selected: type.id === current.type ? "selected" : false,
  }, type.name)));
  typeSelect.addEventListener("change", loadVersions);
  versionSelect.addEventListener("change", loaderRows);
  snapshots.addEventListener("change", versionRows);

  const changer = el("details", { class: "advanced" },
    el("summary", {}, el("span", { class: "chev", "aria-hidden": "true" }, icon("chevron")),
      t("version.change_opener")),
    el("div", { class: "advanced-body" },
      el("div", { class: "grid cols-2" },
        el("div", { class: "field" },
          el("label", { for: "version-type" }, t("version.change_kind")), typeSelect),
        el("div", { class: "field" },
          el("label", { for: "version-pick" }, t("version.change_to")), versionSelect)),
      el("div", { class: "field", hidden: true },
        el("label", { for: "version-loader" }, t("version.loader_pick")), loaderSelect),
      el("label", { class: "switch", hidden: true }, snapshots, el("span", {}, t("new.show_snapshots"))),
      checkBox,
      el("div", { class: "btn-row mt-12" },
        el("button", { class: "btn", type: "button", onclick: (e) => check(e.currentTarget) },
          t("version.check")),
        el("button", { class: "btn primary", type: "button", onclick: (e) => apply(e.currentTarget) },
          t("version.change")))));
  changer.addEventListener("toggle", () => {
    if (changer.open && !payload) loadVersions();
  });

  const parts = [
    detailRows([
      [t("version.kind"), current.capabilities.name],
      // Only what the console printed. null shows as "Not known".
      [t("version.minecraft"), current.minecraft_version],
      current.loader_name ? [current.loader_name, current.loader_version] : null,
      technical() ? [t("version.seen_in"), current.minecraft_version_source] : null,
    ]),
    !current.minecraft_version
      ? el("p", { class: "hint" }, t("version.not_seen_yet"))
      : null,
    current.detected_type && current.detected_type !== current.type
      ? el("div", { class: "banner warn" }, el("div", { class: "grow" },
          t("version.type_disagrees", {
            console: current.detected_type, set: current.capabilities.name,
          })))
      : null,
    pending
      ? el("div", { class: "banner" }, el("div", { class: "grow" },
          t("version.pending", { version: pending.minecraft_version }),
          el("p", { class: "hint mt-0" }, t("version.pending_note"))))
      : null,
    current.eula_required
      ? el("div", { class: "banner warn" }, el("div", { class: "grow" }, t("version.eula_needed")),
          el("button", {
            class: "btn small", type: "button",
            onclick: (e) => busy(e.currentTarget, t("version.accepting"), async () => {
              try {
                await api(serverUrl("/eula"), { method: "POST" });
                toast(t("version.eula_done"), "success");
                if (afterChange) await afterChange();
              } catch (err) { toast(err.message, "error", 9000); }
            }),
          }, t("version.eula_accept")))
      : null,
    // The version list comes from the official source over the internet, so
    // it is fetched when the person opens this, not every time the page
    // is drawn.
    changer,
    change && change.can_roll_back
      ? el("div", { class: "btn-row mt-12" },
          el("button", { class: "btn", type: "button", onclick: (e) => rollBack(e.currentTarget) },
            t("version.back")))
      : null,
    change && change.at
      ? el("p", { class: "hint" }, t("version.last_change", {
          what: `${change.type} ${change.minecraft_version}`,
          when: new Date(change.at * 1000).toLocaleString(),
        }))
      : null,
  ];
  // append() would turn a null into the text "null"; el() skips them.
  body.append(...parts.filter(Boolean));

  return card(t("version.title"), body);
}

/* The dashboard keeps the type list once, so every panel names types the
   same way. */
export async function loadServerTypes() {
  if (state.serverTypes) return state.serverTypes;
  const answer = await api("/server-types");
  state.serverTypes = answer.types;
  state.recommendedType = answer.recommended;
  return state.serverTypes;
}

export function typeOf(id) {
  return (state.serverTypes || []).find((type) => type.id === id) || null;
}

export const contentKind = (id) => {
  const type = typeOf(id);
  return type && known(type.content) ? type.content : null;
};
