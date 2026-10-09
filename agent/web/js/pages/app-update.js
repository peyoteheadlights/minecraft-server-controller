/* App settings cards about the app itself: a new version (and installing
   it, owner only, after a confirmation), "Open on your phone" (the pairing
   code), and removing the old setup.ps1 copy after a move.

   The update itself is done by the installer (agent/updates.py and
   docs/security.md): this page only asks for it and says what happened. */

import { api } from "../api.js";
import { render, renderRail } from "../nav.js";
import { can, state } from "../state.js";
import { t, technical } from "../strings.js";
import { busy, card, confirmDialog, el, fmt, toast } from "../ui.js";

/* ------------------------------------------------------------ new version */

function whatsNew(notes) {
  const lines = (notes || "").split("\n").map((line) => line.trim()).filter(Boolean).slice(0, 30);
  if (!lines.length) return null;
  return el("details", { class: "whats-new" },
    el("summary", {}, t("update.whats_new")),
    el("ul", {}, lines.map((line) => el("li", {}, line.replace(/^[-*#\s]+/, "")))));
}

function lastResult(result) {
  if (!result || result.ok === null || result.ok === undefined) return null;
  if (result.ok) {
    return el("p", { class: "hint" }, t("update.last_ok", { version: result.version || "" }));
  }
  return el("div", { class: "banner error" },
    t("update.last_failed", { version: result.version || "" }), " ",
    result.rolled_back === true ? t("update.rolled_back")
      : result.rolled_back === false ? t("update.not_rolled_back") : "",
    result.message ? el("div", { class: "hint" }, result.message) : null);
}

async function confirmInstall(status) {
  const check = await api("/updates/preflight");
  const players = check.players_online;
  const body = [t("update.confirm_body")];
  if (players > 0) body.push(t("update.confirm_players", { count: players }));
  else if (players === null || players === undefined) body.push(t("update.confirm_players_unknown"));
  return confirmDialog({
    title: t("update.confirm_title", { version: status.latest.version }),
    body: body.join(" "),
    confirmLabel: players > 0 ? t("update.install_anyway") : t("update.install"),
  });
}

async function install(button, status) {
  if (!(await confirmInstall(status))) return;
  await busy(button, t("update.installing"), async () => {
    try {
      const started = await api("/updates/install", { method: "POST" });
      state.jobs[started.job.id] = started.job;
      toast(t("update.started"), "success", 12000);
    } catch (err) { toast(err.message, "error", 12000); }
  });
}

export function updateCard(status) {
  const owner = can("app.update");
  const latest = status.latest;
  let line;
  if (status.available) line = el("p", { class: "update-lead" }, t("update.available", { version: latest.version }));
  else if (status.checked_at) line = el("p", {}, t("update.up_to_date", { version: status.current }));
  else line = el("p", {}, t("update.current", { version: status.current }));
  const checkNow = owner ? el("button", { class: "btn small", type: "button",
    onclick: (e) => busy(e.currentTarget, t("update.checking"), async () => {
      try {
        const now = await api("/updates/check", { method: "POST" });
        state.newVersion = now.available && now.latest ? now.latest.version : "";
        if (now.error) toast(now.error, "error", 9000);
        else toast(now.available ? t("update.available", { version: now.latest.version })
          : t("update.up_to_date", { version: now.current }), "success");
        renderRail();
        render();
      } catch (err) { toast(err.message, "error", 9000); }
    }) }, t("update.check_now")) : null;
  const installButton = owner && status.can_install ? el("button", { class: "btn primary", type: "button",
    onclick: (e) => install(e.currentTarget, status) }, t("update.install")) : null;
  return card(t("update.title"),
    line,
    status.available ? whatsNew(latest.notes) : null,
    status.available && status.cannot_install_reason
      ? el("p", { class: "hint" }, status.cannot_install_reason) : null,
    status.available && latest.page
      ? el("p", { class: "hint" }, el("a", { href: latest.page, target: "_blank", rel: "noopener" },
          t("update.release_page"))) : null,
    status.error ? el("p", { class: "hint" }, t("update.check_failed", { reason: status.error })) : null,
    status.checked_at ? el("p", { class: "hint" }, t("update.checked", { when: fmt.ago(status.checked_at) }))
      : el("p", { class: "hint" }, status.checking ? t("update.checks_daily") : t("update.checks_off")),
    lastResult(status.last_result),
    el("div", { class: "btn-row mt-10" }, installButton, checkNow));
}

/* ------------------------------------------------------------ open on your phone */

/* The QR code, drawn square by square from the agent's rows (no picture
   markup from the server goes into the page). Black on white with a quiet
   border, so a phone reads it in dark mode too. */
function qrCode(rows) {
  const ns = "http://www.w3.org/2000/svg";
  const size = rows.length + 4;
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${size} ${size}`);
  svg.setAttribute("class", "qr-code");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", t("pair.qr_label"));
  const back = document.createElementNS(ns, "rect");
  back.setAttribute("width", String(size));
  back.setAttribute("height", String(size));
  back.setAttribute("class", "qr-back");
  svg.append(back);
  let d = "";
  rows.forEach((row, y) => {
    for (let x = 0; x < row.length; x += 1) if (row[x] === "1") d += `M${x + 2} ${y + 2}h1v1h-1z`;
  });
  const path = document.createElementNS(ns, "path");
  path.setAttribute("d", d);
  path.setAttribute("class", "qr-dark");
  svg.append(path);
  return svg;
}

export function pairingCard(code) {
  if (!code.ok) {
    return card(t("pair.title"), el("p", {}, t("pair.not_ready")), el("p", { class: "hint" }, code.reason));
  }
  return card(t("pair.title"),
    el("div", { class: "pair" },
      el("div", { class: "pair-text" },
        el("p", {}, t("pair.scan")),
        el("p", { class: "mono break" }, code.address_url),
        el("p", { class: "hint" }, t("pair.no_secret")),
        el("p", { class: "hint" }, t("pair.app")),
        el("p", { class: "hint" }, t("pair.rescan")),
        technical() ? el("dl", { class: "pair-facts" },
          el("dt", {}, t("pair.fingerprint")), el("dd", { class: "mono break" }, code.fingerprint),
          el("dt", {}, t("pair.api")), el("dd", {}, String(code.api_version)),
          el("dt", {}, t("pair.link")), el("dd", { class: "mono break" }, code.url)) : null),
      qrCode(code.qr || [])));
}

/* ------------------------------------------------------------ the old copy */

export function oldCopyCard(info) {
  if (!info || !info.offer) return null;
  const key = `mcsc_oldcopy_hidden:${info.path}`;
  try { if (localStorage.getItem(key)) return null; } catch (e) { /* shown */ }
  const node = card(t("oldcopy.title"),
    el("p", {}, t("oldcopy.body", { path: info.path })),
    el("p", { class: "hint" }, t("oldcopy.keeps")),
    info.problems.length
      ? el("div", { class: "banner warn" }, el("strong", {}, t("oldcopy.cant")), el("ul", {},
          info.problems.map((p) => el("li", {}, p))))
      : null,
    el("div", { class: "btn-row mt-10" },
      info.problems.length || !can("app.update") ? null : el("button", { class: "btn danger", type: "button",
        onclick: async (e) => {
          const ok = await confirmDialog({
            title: t("oldcopy.confirm_title"), body: t("oldcopy.confirm_body", { path: info.path }),
            confirmLabel: t("oldcopy.remove"), danger: true,
          });
          if (!ok) return;
          await busy(e.currentTarget, t("oldcopy.removing"), async () => {
            try {
              const result = await api("/updates/old-copy/remove", { method: "POST" });
              toast(result.folder_removed ? t("oldcopy.removed")
                : t("oldcopy.removed_kept", { count: result.kept.length }), "success", 9000);
              render();
            } catch (err) { toast(err.message, "error", 9000); }
          });
        } }, t("oldcopy.remove")),
      el("button", { class: "btn plain", type: "button",
        onclick: () => {
          try { localStorage.setItem(key, "1"); } catch (e) { /* comes back next time */ }
          node.remove();
        } }, t("oldcopy.not_now"))));
  return node;
}
