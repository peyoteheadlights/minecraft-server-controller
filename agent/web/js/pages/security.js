import { api } from "../api.js";
import { signOut } from "../auth.js";
import { renderers, state } from "../state.js";
import { t, technical } from "../strings.js";
import { card, confirmDialog, el, emptyState, fmt, known, loadInto, metric, table, toast } from "../ui.js";

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
      tls.key_check_error || t("security.key_note")));
}

function sessionsCard(data) {
  return card(t("security.sessions", { count: data.active_sessions.length }),
    data.active_sessions.length
      ? table([t("security.col_user"), t("security.col_signed_in"), t("security.col_last_used"),
          t("security.col_from"), t("security.col_device")], data.active_sessions.map((s) => [
          s.user, fmt.time(s.created_at), fmt.ago(s.last_used),
          el("span", { class: "mono" }, s.source_ip || "—"), (s.label || "").slice(0, 40)]))
      : emptyState(t("security.no_sessions")),
    el("div", { class: "btn-row mt-12" },
      el("button", {
        class: "btn small", type: "button",
        onclick: async () => {
          try {
            const result = await api("/auth/rotate", { method: "POST" });
            state.token = result.token;
            sessionStorage.setItem("mcsc_token", state.token);
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
  const [data, audit] = await Promise.all([api("/security"), api("/security/audit?limit=100")]);
  return el("div", { class: "stack" },
    connectionStats(data),
    certificateStats(data),
    sessionsCard(data),
    auditCard(audit),
    el("p", { class: "hint" }, t("security.bind", { address: data.bind_address })));
});
