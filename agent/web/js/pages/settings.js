import { api } from "../api.js";
import { refreshStatus } from "../live.js";
import { renderers, state } from "../state.js";
import { card, el, loadInto, table, toast } from "../ui.js";

renderers.settings = (page) => loadInto(page, async () => {
  const data = await api("/settings");
  const config = data.config;
  const holder = el("div");
  const pending = {};
  const track = (key, input, parse = (v) => v) => {
    input.addEventListener("change", () => { pending[key] = parse(input.value ?? input.checked); });
    return input;
  };

  const numberField = (key, label, value, note) => {
    const input = el("input", { type: "number", value: String(value), step: "any" });
    track(key, input, Number);
    return el("div", { class: "field" }, el("label", {}, label), input,
      note ? el("div", { class: "hint" }, note) : null);
  };
  const checkField = (key, label, checked) => {
    const input = el("input", { type: "checkbox", checked: checked ? "checked" : false });
    input.addEventListener("change", () => { pending[key] = input.checked; });
    return el("label", { class: "check-row pad-y" }, input, label);
  };

  holder.append(card("Crash handling and restarts",
    el("div", { class: "grid cols-3" },
      el("div", {}, checkField("monitor.auto_restart", "Restart automatically after a crash", config.monitor.auto_restart)),
      numberField("monitor.restart_delay", "Delay before restart (seconds)", config.monitor.restart_delay),
      numberField("monitor.max_crashes", "Stop retrying after this many crashes", config.monitor.max_crashes,
        `within ${config.monitor.crash_window_minutes} minutes`))));

  holder.append(el("div", { class: "gap-section" }, card("Alert thresholds",
    el("div", { class: "grid cols-3" },
      numberField("thresholds.cpu_percent", "CPU alert above (%)", config.thresholds.cpu_percent),
      numberField("thresholds.ram_percent", "RAM alert above (%)", config.thresholds.ram_percent),
      numberField("thresholds.disk_free_gb", "Disk alert below (GB)", config.thresholds.disk_free_gb),
      numberField("thresholds.tps_min", "TPS alert below", config.thresholds.tps_min),
      numberField("thresholds.mspt_max", "MSPT alert above (ms)", config.thresholds.mspt_max),
      numberField("notifications.min_interval_seconds", "Minimum seconds between repeat alerts",
        config.notifications.min_interval_seconds)))));

  const eventChecks = Object.entries(config.notifications.events).map(([key, value]) =>
    checkField(`notifications.events.${key}`, key.replace(/_/g, " "), value));
  holder.append(el("div", { class: "gap-section" }, card("Notifications",
    el("div", { class: "grid cols-2" },
      el("div", {},
        checkField("notifications.discord_enabled", "Send to Discord", config.notifications.discord_enabled),
        el("div", { class: "hint" }, data.secrets.discord_webhook_configured
          ? "Webhook URL is configured in the agent's .env file."
          : "No webhook URL configured. Add MCSC_DISCORD_WEBHOOK to the agent's .env file."),
        el("button", {
          class: "btn small mt-8",
          onclick: async () => {
            const result = await api("/notifications/test?channel=discord", { method: "POST" });
            toast(result.sent ? "Discord test sent" : "Discord test failed, see notification history",
              result.sent ? "info" : "error");
          },
        }, "Send test")),
      el("div", {},
        checkField("notifications.email_enabled", "Send email", config.notifications.email_enabled),
        el("div", { class: "hint" }, data.secrets.smtp_configured
          ? "SMTP credentials are configured in the agent's .env file."
          : "No SMTP password configured. Add MCSC_SMTP_USERNAME and MCSC_SMTP_PASSWORD to .env."),
        el("button", {
          class: "btn small mt-8",
          onclick: async () => {
            const result = await api("/notifications/test?channel=email", { method: "POST" });
            toast(result.sent ? "Email test sent" : "Email test failed, see notification history",
              result.sent ? "info" : "error");
          },
        }, "Send test"))),
    el("h3", { class: "subheading" }, "Which events to send"),
    el("div", { class: "grid cols-3" }, eventChecks))));

  const startupResult = el("div", { class: "mt-10" });
  holder.append(el("div", { class: "gap-section" }, card("Windows startup",
    el("p", { class: "hint" },
      "Checks the scheduled task that starts this agent with Windows, reads it back from "
      + "Windows, and shows what happened the last time the agent started."),
    el("button", {
      class: "btn small",
      onclick: async () => {
        startupResult.innerHTML = "";
        startupResult.append(el("div", { class: "empty" }, "Asking Windows..."));
        try {
          const r = await api("/system/startup");
          startupResult.innerHTML = "";
          const yesNo = (v) => v === true ? "yes" : v === false ? "no" : "unknown";
          const task = r.task || {};
          const runtime = r.runtime || {};
          const last = r.last_startup || {};
          const initialised = (last.events || []).some((e) => e.event === "controller_initialized");
          const verdictClass = r.verdict === "registered correctly" ? "ok"
            : r.verdict === "unsupported" ? "" : "error";
          startupResult.append(
            el("div", { class: `banner ${verdictClass}` }, el("strong", {}, r.verdict.toUpperCase())),
            table(["Check", "Result"], [
              ["Startup registration", r.registered === true ? "found"
                : r.registered === false ? "not found" : "unknown"],
              ["Mechanism", r.mechanism || "none"],
              ["Mode", task.mode === "boot" ? "at boot (no login needed)"
                : task.mode === "logon" ? "when you log in" : "-"],
              ["Registered executable", el("span", { class: "mono" }, task.command || "-")],
              ["Registered working directory", el("span", { class: "mono" }, task.working_directory || "-")],
              ["Points to this installation", yesNo(r.points_to_current_app)],
              ["Windows last run", runtime.last_run_time || "unknown"],
              ["Windows last result", runtime.last_result || "unknown"],
              ["Last startup recorded by agent", last.started_at
                ? `${last.started_at} (launched by ${last.launched_by})` : "none recorded"],
              ["Controller initialised on that start", last.started_at ? (initialised ? "yes" : "no") : "-"],
            ]),
            (r.problems || []).length
              ? el("div", { class: "banner error mt-10" },
                  el("strong", {}, "Problems"),
                  el("ul", {}, r.problems.map((p) => el("li", {}, p))))
              : null,
            el("p", { class: "hint" }, `Full log: ${r.startup_log}`));
        } catch (err) {
          startupResult.innerHTML = "";
          startupResult.append(el("div", { class: "banner error" }, err.message));
        }
      },
    }, "Test Windows Startup"),
    startupResult)));

  holder.append(el("div", { class: "gap-section" }, card("Maintenance mode",
    checkField("maintenance.enabled", "Pause automatic restarts and scheduled tasks",
      config.maintenance.enabled),
    el("button", {
      class: "btn small mt-8",
      onclick: async () => {
        const next = !(state.status && state.status.maintenance);
        await api("/maintenance", { method: "POST", body: { enabled: next } });
        toast(`Maintenance mode ${next ? "on" : "off"}`);
        refreshStatus();
      },
    }, "Toggle maintenance mode now"))));

  holder.append(el("div", { class: "mt-16" },
    el("button", {
      class: "btn primary",
      onclick: async () => {
        if (!Object.keys(pending).length) { toast("Nothing changed"); return; }
        try {
          const result = await api("/settings", { method: "PUT", body: { updates: pending } });
          toast(`Saved ${Object.keys(result.applied).length} setting(s)`);
          if (Object.keys(result.rejected).length) {
            toast(`Rejected: ${Object.keys(result.rejected).join(", ")}`, "warn");
          }
        } catch (err) { toast(err.message, "error"); }
      },
    }, "Save settings"),
    el("p", { class: "hint mt-10" },
      "Secrets (Discord webhook, SMTP password, API token) are never edited here. "
      + "They live in the agent's .env file on the Minecraft PC.")));
  return holder;
});
