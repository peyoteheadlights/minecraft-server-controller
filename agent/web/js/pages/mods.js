import { api } from "../api.js";
import { render } from "../nav.js";
import { dependenciesPanel } from "../panels/dependencies.js";
import { STATES, renderers } from "../state.js";
import { $, card, confirmDialog, el, emptyState, fmt, loadInto, table, toast } from "../ui.js";

renderers.mods = (page) => loadInto(page, async () => {
  const data = await api("/mods");
  const holder = el("div");
  const offline = data.server_state === "OFFLINE" || data.server_state === "CRASHED";

  if (!offline) {
    holder.append(el("div", { class: "banner" },
      `The server is ${(STATES[data.server_state] || STATES.UNKNOWN).label.replace("…", "").toLowerCase()}. `
      + "You can browse mods now. Installing, removing, enabling, disabling and updating "
      + "need the server stopped first."));
  }
  const others = data.problems.filter((p) => !["missing_dependency", "dependency_version"].includes(p.kind));
  if (others.length) {
    holder.append(el("div", { class: "banner error" },
      el("strong", {}, `${others.length} mod problem(s) found: `),
      el("ul", {}, others.slice(0, 6).map((p) => el("li", {}, p.detail)))));
  }
  const depPanel = el("div");
  holder.append(depPanel);
  dependenciesPanel(depPanel, { offline });

  const search = el("input", { type: "text", placeholder: "Search Modrinth for Fabric mods…",
    class: "mono", style: "flex:1;min-width:200px;padding:8px 11px;background:var(--bg);border:1px solid var(--line);border-radius:8px" });
  const results = el("div", { style: "margin-top:12px" });
  holder.append(card("Install from Modrinth",
    el("div", { class: "btn-row" }, search,
      el("button", {
        class: "btn primary",
        onclick: async () => {
          results.innerHTML = "";
          results.append(el("div", { class: "empty" }, "Searching Modrinth…"));
          try {
            const found = await api(`/mods/search?q=${encodeURIComponent(search.value)}&limit=10`);
            results.innerHTML = "";
            if (!found.hits.length) { results.append(el("div", { class: "empty" }, "Nothing found")); return; }
            results.append(table(["Mod", "Downloads", "Server side", ""], found.hits.map((hit) => [
              el("div", {}, el("strong", {}, hit.title),
                el("div", { class: "hint" }, (hit.description || "").slice(0, 110))),
              Number(hit.downloads).toLocaleString(),
              hit.server_side || "?",
              el("button", { class: "btn small", disabled: !offline,
                onclick: () => installMod(hit) }, "Install"),
            ])));
          } catch (err) {
            results.innerHTML = "";
            results.append(el("div", { class: "banner error" }, err.message));
          }
        },
      }, "Search")),
    results,
    el("p", { class: "hint", style: "margin-top:10px" },
      `Downloads are checked against the SHA-512 Modrinth publishes, and only .jar files from
       Modrinth's own CDN are accepted. Minecraft version in use: ${data.minecraft_version || "unknown"}.`)));

  holder.append(el("div", { class: "gap-section" },
    card(`Installed mods (${data.mods.length})`, !data.mods.length
      ? emptyState("No mods installed", "Search Modrinth above, or place .jar files in the mods folder.")
      : table(
      ["Mod", "Version", "Minecraft", "Status", "Update", ""],
      data.mods.map((mod) => [
        el("div", {}, el("strong", {}, mod.name),
          el("div", { class: "hint mono" }, mod.mod_id)),
        el("span", { class: "mono" }, mod.version || "—"),
        el("span", { class: "mono" }, mod.minecraft_range || "—"),
        el("span", { class: `tag ${mod.status === "ok" ? "ok" : mod.status === "disabled" ? "off" : mod.status}` },
          mod.enabled ? mod.status : "disabled"),
        mod.update_available
          ? el("span", { class: "tag warn" }, mod.update_available.latest_version)
          : "—",
        el("div", { class: "btn-row" },
          mod.update_available
            ? el("button", { class: "btn small", disabled: !offline,
                onclick: () => updateMod(mod) }, "Update")
            : null,
          el("button", {
            class: "btn small", disabled: !offline,
            onclick: async () => {
              try {
                await api(mod.enabled ? "/mods/disable" : "/mods/enable",
                  { method: "POST", body: { filename: mod.filename } });
                toast(`${mod.name} ${mod.enabled ? "disabled" : "enabled"}`);
                render();
              } catch (err) { toast(err.message, "error"); }
            },
          }, mod.enabled ? "Disable" : "Enable"),
          el("button", { class: "btn small", onclick: () => showVersions(mod) }, "History"),
          el("button", { class: "btn small danger", disabled: !offline,
            onclick: () => removeMod(mod) }, "Remove")),
      ])),
    el("p", { class: "hint", style: "margin-top:10px" },
      (data.claim || "") + ". " + (data.claim_note || "")),
    el("p", { class: "hint" },
      "What this checker cannot see: " + data.limitations.join(" ")))));

  holder.append(el("div", { class: "gap-section" }, await modHistoryCard()));
  return holder;
});

export async function modHistoryCard() {
  const data = await api("/mods/history?limit=25");
  return card("Mod audit history", data.history.length
    ? table(["When", "Who", "Action", "Mod", "Change", "Result"], data.history.map((h) => [
        fmt.time(h.ts), h.user || "—", h.action, h.mod_name || h.mod_id || "—",
        h.old_version || h.new_version
          ? `${h.old_version || "—"} → ${h.new_version || "—"}` : "—",
        el("span", { class: `tag ${h.result === "ok" ? "ok" : "error"}` }, h.result),
      ]))
    : el("div", { class: "empty" }, "No mod changes recorded yet"));
}

export async function installMod(hit) {
  let detail;
  try { detail = await api(`/mods/project/${hit.slug}`); }
  catch (err) { toast(err.message, "error"); return; }
  const latest = detail.versions[0];
  if (!latest) { toast("No Fabric build for this Minecraft version", "error"); return; }
  const deps = latest.dependencies.filter((d) => d.type === "required");
  const installDeps = el("input", { type: "checkbox" });
  const body = el("div", {},
    el("p", {}, `Install ${detail.project.title} ${latest.version_number} (${latest.release_type}).`),
    el("ul", {},
      el("li", {}, `File: ${latest.file.filename} (${fmt.bytes(latest.file.size)})`),
      el("li", {}, `Minecraft: ${latest.game_versions.join(", ")}`),
      el("li", {}, `Server side: ${detail.project.server_side}`),
      el("li", {}, `Licence: ${detail.project.license || "unknown"}`)),
    deps.length
      ? el("div", {},
          el("p", {}, el("strong", {}, `${deps.length} required dependency/dependencies declared.`)),
          el("label", { style: "display:flex;gap:8px;align-items:center" },
            installDeps, "Install required dependencies too"))
      : el("p", { class: "hint" }, "No required dependencies declared."),
    el("p", { class: "hint" },
      "The jar is downloaded from Modrinth's CDN and its checksum is verified before it is written."));
  const ok = await confirmDialog({ title: "Install this mod?", body, confirmLabel: "Back up and install" });
  if (!ok) return;
  try {
    const result = await api("/mods/install", {
      method: "POST",
      body: { project: hit.slug, version_id: latest.version_id,
              install_dependencies: installDeps.checked },
    });
    toast(`Installed ${result.installed.name} ${result.installed.version}. `
      + "Loaded by Minecraft: not verified - start the server to confirm.", "info", 9000);
    if (result.dependencies_required.some((d) => !d.installed) && !installDeps.checked) {
      toast("Required dependencies are missing. Open the mod list to see which.", "warn", 9000);
    }
    render();
  } catch (err) { toast(err.message, "error", 9000); }
}

export async function updateMod(mod) {
  const ok = await confirmDialog({
    title: `Update ${mod.name}?`,
    // Built from text nodes, not an HTML string: version strings come from
    // a mod's own metadata and must never be parsed as markup.
    body: el("div", {},
      el("p", {}, `${mod.version} → ${mod.update_available.latest_version} `,
        `(${mod.update_available.release_type}).`),
      el("p", { class: "hint" },
        "The current jar is archived first, so you can roll back from History.")),
    confirmLabel: "Update mod",
  });
  if (!ok) return;
  try {
    const result = await api("/mods/update", {
      method: "POST",
      body: { filename: mod.filename, version_id: mod.update_available.version_id },
    });
    toast(`Updated to ${result.updated.version}. Loaded by Minecraft: not verified `
      + "- start the server to confirm, and roll back from History if startup fails.",
      "info", 9000);
    render();
  } catch (err) { toast(err.message, "error", 9000); }
}

export async function removeMod(mod) {
  let impact;
  try { impact = await api(`/mods/impact?filename=${encodeURIComponent(mod.filename)}`); }
  catch (err) { toast(err.message, "error"); return; }
  const body = el("div", {},
    el("p", {}, `Remove ${mod.name} ${mod.version}?`),
    impact.warning ? el("div", { class: "banner error" }, impact.warning) : null,
    impact.dependents.length
      ? el("ul", {}, impact.dependents.map((d) => el("li", {}, `${d.name} requires ${d.requires}`)))
      : el("p", { class: "hint" }, "No installed mod declares this as a dependency."),
    el("p", { class: "hint" },
      "The jar is copied to mod-backups and then moved to mod-trash. It is not deleted outright."));
  const ok = await confirmDialog({
    title: "Remove this mod?", body, confirmLabel: "Back up and remove", danger: true,
  });
  if (!ok) return;
  try {
    await api("/mods/remove", { method: "POST", body: { filename: mod.filename } });
    toast(`${mod.name} removed and archived`);
    render();
  } catch (err) { toast(err.message, "error"); }
}

export async function showVersions(mod) {
  const data = await api(`/mods/versions/${encodeURIComponent(mod.mod_id)}`);
  const body = data.versions.length
    ? table(["Version", "Archived", "File", ""], data.versions.map((v) => [
        el("span", { class: "mono" }, v.version || "—"),
        fmt.time(v.created_at),
        v.exists ? "on disk" : el("span", { class: "tag error" }, "missing"),
        v.is_current || !v.exists ? (v.is_current ? el("span", { class: "tag ok" }, "current") : "—")
          : el("button", {
              class: "btn small",
              onclick: async () => {
                $("#modal-root").innerHTML = "";
                const ok = await confirmDialog({
                  title: `Roll back to ${v.version}?`,
                  body: "The current jar is archived first, and the archived jar's SHA-256 "
                        + "is verified before it is restored.",
                  confirmLabel: "Roll back", danger: true,
                });
                if (!ok) return;
                try {
                  await api("/mods/rollback", {
                    method: "POST",
                    body: { mod_id: mod.mod_id, archive_path: v.archive_path },
                  });
                  toast(`Rolled back to ${v.version}`);
                  render();
                } catch (err) { toast(err.message, "error"); }
              },
            }, "Roll back"),
      ]))
    : el("div", { class: "empty" }, "No archived versions yet");
  await confirmDialog({ title: `${mod.name} version history`, body, confirmLabel: "Close" });
}
