import { api } from "../api.js";
import { signOut } from "../auth.js";
import { renderers, state } from "../state.js";
import { card, confirmDialog, el, fmt, loadInto, metric, table, toast } from "../ui.js";

renderers.security = (page) => loadInto(page, async () => {
  const [data, audit] = await Promise.all([api("/security"), api("/security/audit?limit=100")]);
  const holder = el("div");
  const tls = data.tls || {};
  const certDays = tls.days_remaining;
  holder.append(el("div", { class: "grid cols-4" },
    metric("Agent", "connected", "this dashboard is talking to it"),
    metric("HTTPS",
      data.https_enabled === false ? "disabled"
        : (tls.parsed ? "certificate loaded" : null),
      data.https_enabled === false
        ? "plain HTTP - loopback only"
        : (tls.parsed
            ? `issued by ${tls.issuer || "unknown issuer"}`
            : (tls.parse_error || "the certificate could not be read"))),
    metric("Certificate expiry",
      certDays === null || certDays === undefined ? null : `${Math.round(certDays)}`,
      certDays === null || certDays === undefined
        ? "could not be read from the certificate file"
        : `days remaining (${tls.expiry_severity})`),
    metric("Tailscale",
      data.tailscale.connected === null ? null
        : (data.tailscale.connected ? "connected" : "not connected"),
      data.tailscale.detail),
    metric("Authentication", data.authentication.enabled ? "enabled" : "NOT SET",
      `sessions last ${data.authentication.session_hours}h`)));
  holder.append(el("div", { class: "grid cols-3", style: "margin-top:14px" },
    metric("Failed sign-ins", String(data.failed_logins_24h), "in the last 24 hours"),
    metric("Certificate covers", tls.covers_hostname === true ? "yes"
      : tls.covers_hostname === false ? "no" : null,
      data.dashboard_hostname
        ? `checked against ${data.dashboard_hostname}`
        : "tls.hostname is not configured, so this cannot be checked"),
    metric("Key matches certificate",
      tls.key_matches_certificate === true ? "yes"
        : tls.key_matches_certificate === false ? "no" : null,
      tls.key_check_error || "compared as public keys; the private key is never exposed")));

  holder.append(el("div", { class: "gap-section" }, card(
    `Active sessions (${data.active_sessions.length})`,
    data.active_sessions.length
      ? table(["User", "Signed in", "Last used", "From", "Device"], data.active_sessions.map((s) => [
          s.user, fmt.time(s.created_at), fmt.ago(s.last_used),
          el("span", { class: "mono" }, s.source_ip || "—"), (s.label || "").slice(0, 40)]))
      : el("div", { class: "empty" }, "No active sessions"),
    el("div", { class: "btn-row", style: "margin-top:12px" },
      el("button", {
        class: "btn small",
        onclick: async () => {
          const result = await api("/auth/rotate", { method: "POST" });
          state.token = result.token;
          sessionStorage.setItem("mcsc_token", state.token);
          toast("This session's token was rotated");
        },
      }, "Rotate my token"),
      el("button", {
        class: "btn small danger",
        onclick: async () => {
          const ok = await confirmDialog({
            title: "Sign every session out?",
            body: "All sessions, including this one, are revoked. You will sign in again.",
            confirmLabel: "Revoke all sessions", danger: true,
          });
          if (!ok) return;
          await api("/security/revoke-sessions", { method: "POST" });
          signOut(true);
        },
      }, "Revoke all sessions")))));

  holder.append(el("div", { class: "gap-section" }, card("Audit log",
    audit.entries.length
      ? table(["When", "User", "Action", "Target", "Result"], audit.entries.map((e) => [
          fmt.time(e.ts), e.user || "—", e.action, e.target || "—",
          el("span", { class: `tag ${e.result === "ok" ? "ok" : "error"}` }, e.result)]))
      : el("div", { class: "empty" }, "Nothing logged yet"))));

  holder.append(el("p", { class: "hint", style: "margin-top:12px" },
    `The agent is bound to ${data.bind_address}. Keep that address private to your tailnet;
     do not port-forward it.`));
  return holder;
});
