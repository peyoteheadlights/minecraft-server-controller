import { api } from "../api.js";
import { signOut } from "../auth.js";
import { renderers, state } from "../state.js";
import { t, technical } from "../strings.js";
import { $, card, confirmDialog, el, emptyState, fmt, known, loadInto, metric, table, toast } from "../ui.js";

const yesNo = (value) => (value === true ? t("value.yes") : value === false ? t("value.no") : null);

/* The certificate rows only mean something while HTTPS is on. */
function connectionStats(data) {
  const tls = data.tls || {};
  const days = tls.days_remaining;
  const httpsOff = data.https_enabled === false;
  return el("div", { class: "stats", role: "group" },
    metric(t("security.agent"), t("security.connected"), t("security.agent_note")),
    metric(t("security.https"),
      httpsOff ? t("security.https_off") : (tls.parsed ? t("security.cert_loaded") : null),
      httpsOff ? t("security.https_off_note")
        : (tls.parsed ? t("security.issued_by", { issuer: tls.issuer || t("security.unknown_issuer") })
          : (tls.parse_error || t("security.cert_unreadable")))),
    httpsOff ? null : metric(t("security.expiry"), known(days) ? `${Math.round(days)}` : null,
      known(days)
        ? `${t("security.days_left")}${technical() && tls.expiry_severity ? ` (${tls.expiry_severity})` : ""}`
        : t("security.expiry_unreadable")),
    metric(t("security.tailscale"),
      data.tailscale.connected === null ? null
        : t(data.tailscale.connected ? "security.ts_connected" : "security.ts_disconnected"),
      data.tailscale.detail),
    metric(t("security.auth"), t(data.authentication.enabled ? "security.auth_on" : "security.auth_off"),
      t("security.auth_note", { hours: data.authentication.session_hours })),
    metric(t("security.failed"), String(data.failed_logins_24h), t("security.failed_note")));
}

function certificateStats(data) {
  const tls = data.tls || {};
  if (data.https_enabled === false) return null;
  return el("div", { class: "stats", role: "group" },
    metric(t("security.covers"), yesNo(tls.covers_hostname),
      data.dashboard_hostname ? t("security.covers_note", { host: data.dashboard_hostname })
        : t("security.covers_unset")),
    metric(t("security.key_match"), yesNo(tls.key_matches_certificate),
      tls.key_check_error || t("security.key_note")),
    // What a phone app pins: shown in Technical mode, and in the pairing code.
    technical() ? metric(t("security.fingerprint"), tls.fingerprint ? t("security.fingerprint_sha") : null,
      tls.fingerprint ? el("span", { class: "mono break" }, tls.fingerprint) : t("security.cert_unreadable"))
      : null);
}

/* Signed-in devices: each can be signed out on its own. A kept sign-in
   ("Keep me signed in") is marked, since it lasts until it is signed out
   or goes unused for a long time. */
function devicesCard(devices, rememberDays) {
  const signOutDevice = async (row) => {
    if (row.current) { signOut(false); return; }
    const ok = await confirmDialog({
      title: t("security.device_out_title", { device: row.label || t("security.device_unknown") }),
      body: t("security.device_out_body"), confirmLabel: t("security.device_out"), danger: true,
    });
    if (!ok) return;
    try {
      await api(`/sessions/${encodeURIComponent(row.id)}`, { method: "DELETE" });
      toast(t("security.device_out_done"), "success");
      renderers.security($("#page"));
    } catch (err) { toast(err.message, "error"); }
  };
  return card(t("security.sessions", { count: devices.length }),
    devices.length
      ? table([t("security.col_device"), t("security.col_user"), t("security.col_signed_in"),
          t("security.col_last_used"), t("security.col_from"), ""], devices.map((row) => [
          el("span", {}, (row.label || t("security.device_unknown")).slice(0, 40),
            row.current ? el("span", { class: "tag ok ml-6" }, t("security.this_device")) : null,
            row.remember ? el("span", { class: "tag ml-6" }, t("security.kept")) : null),
          row.user, fmt.ago(row.created_at), fmt.ago(row.last_used),
          el("span", { class: "mono" }, row.source_ip || "—"),
          el("button", { class: "btn small", type: "button", onclick: () => signOutDevice(row) },
            t("security.device_out"))]))
      : emptyState(t("security.no_sessions")),
    el("p", { class: "hint" }, t("security.kept_note", { days: rememberDays })),
    el("div", { class: "btn-row mt-12" },
      el("button", {
        class: "btn small", type: "button",
        onclick: async () => {
          try {
            const result = await api("/auth/rotate", { method: "POST" });
            state.token = result.token;
            sessionStorage.setItem("mcsc_token", state.token);
            try {
              if (localStorage.getItem("mcsc_token")) localStorage.setItem("mcsc_token", state.token);
            } catch (e) { /* kept for this tab only */ }
            toast(t("security.rotated"), "success");
          } catch (err) { toast(err.message, "error"); }
        },
      }, t("security.rotate")),
      el("button", {
        class: "btn small danger", type: "button",
        onclick: async () => {
          const ok = await confirmDialog({
            title: t("security.revoke_title"), body: t("security.revoke_body"),
            confirmLabel: t("security.revoke"), danger: true,
          });
          if (!ok) return;
          await api("/security/revoke-sessions", { method: "POST" });
          signOut(true);
        },
      }, t("security.revoke"))));
}

function auditCard(audit) {
  return card(t("security.audit"),
    audit.entries.length
      ? table([t("security.col_when"), t("security.col_user"), t("security.col_action"),
          t("security.col_target"), t("security.col_result")], audit.entries.map((e) => [
          fmt.time(e.ts), e.user || "—", el("span", { class: "mono" }, e.action), e.target || "—",
          el("span", { class: `tag ${e.result === "ok" ? "ok" : "error"}` },
            e.result === "ok" ? t("security.result_ok") : e.result)]))
      : emptyState(t("security.audit_none")));
}

renderers.security = (page) => loadInto(page, async () => {
  const [data, audit, devices] = await Promise.all([
    api("/security"), api("/security/audit?limit=100"), api("/sessions")]);
  return el("div", { class: "stack" },
    connectionStats(data),
    certificateStats(data),
    devicesCard(devices.sessions || [], devices.remember_days),
    auditCard(audit),
    el("p", { class: "hint" }, t("security.bind", { address: data.bind_address })));
});
