/* App-wide settings, behind the gear: how the dashboard looks, how much
   detail it shows, alerts, maintenance mode and the Windows startup check.
   Everything about one server is on that server's own Settings page. */

import { api } from "../api.js";
import { refreshStatus } from "../live.js";
import { choose, currentTheme, THEMES } from "../prefs.js";
import { currentSubscription, deviceLabel, disablePush, enablePush, pushSupported } from "../pwa.js";
import { renderers, state } from "../state.js";
import { t, technical } from "../strings.js";
import { advanced, busy, card, el, fmt, loadInto, table, toast, withHelp } from "../ui.js";

function choiceGroup(name, options, current, onChange, extraClass = "") {
  return el("div", { class: `choices ${extraClass}`, role: "radiogroup", "aria-label": t(`appset.${name}`) },
    options.map(([value, label, detail, preview]) => {
      const input = el("input", {
        type: "radio", name, value, checked: value === current ? "checked" : false,
        onchange: () => onChange(value),
      });
      return el("label", { class: "choice" }, input,
        preview || null,
        el("span", { class: "choice-text" }, el("strong", {}, label),
          detail ? el("span", { class: "hint" }, detail) : null));
    }));
}

function appearanceCard() {
  const options = THEMES.map((theme) => [theme, t(`theme.${theme}`), null,
    el("span", { class: `theme-preview theme-${theme}`, "aria-hidden": "true" },
      el("span"), el("span"), el("span"))]);
  return card(t("appset.appearance"),
    choiceGroup("theme", options, currentTheme(), (value) => choose("theme", value), "themes"));
}

function detailCard() {
  return card(t("appset.detail"),
    choiceGroup("mode", [
      ["simple", t("mode.simple"), t("mode.simple_hint")],
      ["technical", t("mode.technical"), t("mode.technical_hint")],
    ], technical() ? "technical" : "simple", (value) => choose("mode", value)));
}

function alertsCard(data, push) {
  const config = data.config;
  const pending = {};
  const number = (key, label, value) => {
    const input = el("input", { type: "number", value: String(value), step: "any", id: `f-${key}` });
    input.addEventListener("change", () => { pending[key] = Number(input.value); });
    return el("div", { class: "field" }, el("label", { for: `f-${key}` }, label), input);
  };
  const check = (key, label, checked) => {
    const input = el("input", { type: "checkbox", checked: checked ? "checked" : false });
    input.addEventListener("change", () => { pending[key] = input.checked; });
    return el("label", { class: "check-row pad-y" }, input, label);
  };
  // The key is the settings key the agent accepts ("notifications.x"); the
  // value shown comes from that section.
  const channel = (key, label, configured, missingHint, testChannel) => el("div", { class: "channel" },
    check(key, label, config.notifications[key.split(".").pop()]),
    configured ? null : el("p", { class: "hint" }, missingHint),
    el("button", {
      class: "btn small", type: "button",
      onclick: (e) => busy(e.currentTarget, t("appset.sending"), async () => {
        try {
          const result = await api(`/notifications/test?channel=${testChannel}`, { method: "POST" });
          toast(result.sent ? t("appset.test_sent") : t("appset.test_failed"), result.sent ? "success" : "error");
        } catch (err) { toast(err.message, "error"); }
      }),
    }, t("appset.send_test")));

  const events = Object.entries(config.notifications.events).map(([key, value]) =>
    check(`notifications.events.${key}`, t(`alert_event.${key}`), value));

  return card(t("appset.alerts"),
    el("div", { class: "grid cols-2" },
      channel("notifications.discord_enabled", t("appset.discord"), data.secrets.discord_webhook_configured,
        t("appset.discord_missing"), "discord"),
      channel("notifications.email_enabled", t("appset.email"), data.secrets.smtp_configured,
        t("appset.email_missing"), "email"),
      phoneCard(push, pending)),
    advanced(t("appset.alert_details"),
      el("div", { class: "grid cols-3" },
        number("thresholds.cpu_percent", t("appset.cpu_alert"), config.thresholds.cpu_percent),
        number("thresholds.ram_percent", t("appset.ram_alert"), config.thresholds.ram_percent),
        number("thresholds.disk_free_gb", t("appset.disk_alert"), config.thresholds.disk_free_gb),
        number("thresholds.tps_min", t("appset.tps_alert"), config.thresholds.tps_min),
        number("thresholds.mspt_max", t("appset.mspt_alert"), config.thresholds.mspt_max),
        number("notifications.min_interval_seconds", t("appset.repeat_alert"),
          config.notifications.min_interval_seconds)),
      el("h3", { class: "subheading" }, t("appset.which_events")),
      el("div", { class: "grid cols-3" }, events)),
    el("div", { class: "btn-row mt-12" },
      el("button", {
        class: "btn primary", type: "button",
        onclick: (e) => busy(e.currentTarget, t("action.saving"), async () => {
          if (!Object.keys(pending).length) { toast(t("settings.nothing_changed")); return; }
          try {
            const result = await api("/settings", { method: "PUT", body: { updates: pending } });
            const rejected = Object.entries(result.rejected);
            if (rejected.length) toast(rejected.map(([, why]) => why).join(" "), "error", 9000);
            else toast(t("settings.saved"), "success");
            for (const key of Object.keys(result.applied)) delete pending[key];
          } catch (err) { toast(err.message, "error"); }
        }),
      }, t("appset.save_alerts"))),
    el("p", { class: "hint" }, t("appset.secrets_note")));
}

/* ------------------------------------------------------------ phone alerts */

/* The same alerts as Discord and email, on a phone's lock screen. Two
   separate things have to be on: the channel here, and this phone itself,
   which is the browser's own choice and has to be made on each phone. */
function phoneCard(push, pendingFor) {
  const list = el("div", { class: "mt-10" });
  const refresh = (phones) => list.replaceChildren(phones.length
    ? el("ul", { class: "phone-list" }, phones.map((p) => el("li", {},
        el("span", {}, p.label || p.service),
        el("span", { class: "hint" }, p.last_sent ? t("push.last_sent", { when: fmt.ago(p.last_sent) })
          : t("push.not_sent_yet")))))
    : el("p", { class: "hint" }, t("push.no_phones")));
  refresh(push.phones || []);

  const thisPhone = el("div", { class: "btn-row mt-10" });
  const drawThisPhone = (subscribed) => thisPhone.replaceChildren(
    subscribed
      ? el("button", { class: "btn", type: "button",
          onclick: (e) => busy(e.currentTarget, t("push.turning_off"), async () => {
            try {
              const result = await disablePush();
              refresh((result && result.phones) || []);
              drawThisPhone(false);
              toast(t("push.off_here"), "success");
            } catch (err) { toast(err.message, "error", 9000); }
          }) }, t("push.turn_off_here"))
      : el("button", { class: "btn primary", type: "button",
          disabled: push.configured ? false : true,
          onclick: (e) => busy(e.currentTarget, t("push.turning_on"), async () => {
            try {
              const result = await enablePush(push.public_key, deviceLabel());
              refresh(result.phones || []);
              drawThisPhone(true);
              toast(t("push.on_here"), "success");
            } catch (err) { toast(err.message, "error", 9000); }
          }) }, t("push.turn_on_here")),
    el("button", { class: "btn small", type: "button",
      onclick: (e) => busy(e.currentTarget, t("appset.sending"), async () => {
        try {
          const result = await api("/push/test", { method: "POST" });
          toast(result.sent ? t("appset.test_sent") : t("push.test_failed"),
            result.sent ? "success" : "error", 9000);
        } catch (err) { toast(err.message, "error", 9000); }
      }) }, t("appset.send_test")));
  drawThisPhone(false);
  if (pushSupported()) {
    currentSubscription().then((sub) => drawThisPhone(Boolean(sub))).catch(() => {});
  }

  return el("div", { class: "channel" },
    withHelp(el("label", { class: "check-row pad-y" },
      el("input", {
        type: "checkbox", checked: push.enabled ? "checked" : false,
        onchange: (e) => { pendingFor["notifications.push_enabled"] = e.target.checked; },
      }), t("appset.phone")), "phone_alerts", "notifications"),
    push.configured ? null : el("p", { class: "hint" }, t("push.not_set_up", { command: push.setup_command })),
    pushSupported() ? null : el("p", { class: "hint" }, t("push.unsupported")),
    el("p", { class: "hint" }, t("push.iphone")),
    thisPhone,
    list);
}

function maintenanceCard() {
  const on = Boolean(state.status && state.status.maintenance);
  const input = el("input", {
    type: "checkbox", checked: on ? "checked" : false, id: "maintenance-switch",
    onchange: async () => {
      try {
        await api("/maintenance", { method: "POST", body: { enabled: input.checked } });
        toast(input.checked ? t("appset.maintenance_on") : t("appset.maintenance_off"), "success");
        refreshStatus();
      } catch (err) {
        input.checked = !input.checked;
        toast(err.message, "error");
      }
    },
  });
  return card(t("appset.maintenance"),
    el("label", { class: "switch" }, input, t("appset.maintenance_label")));
}

function startupCard() {
  const result = el("div", { class: "mt-10" });
  return advanced(t("appset.startup"),
    el("p", { class: "hint mt-0" }, t("appset.startup_hint")),
    el("button", {
      class: "btn small", type: "button",
      onclick: (e) => busy(e.currentTarget, t("appset.startup_asking"), async () => {
        try {
          result.replaceChildren(startupReport(await api("/system/startup")));
        } catch (err) {
          result.replaceChildren(el("div", { class: "banner error" }, err.message));
        }
      }),
    }, t("appset.startup_check")),
    result);
}

function startupReport(r) {
  const yesNo = (v) => (v === true ? t("value.yes") : v === false ? t("value.no") : t("value.unknown"));
  const task = r.task || {};
  const runtime = r.runtime || {};
  const last = r.last_startup || {};
  const initialised = (last.events || []).some((e) => e.event === "controller_initialized");
  const tone = r.verdict === "registered correctly" ? "ok" : r.verdict === "unsupported" ? "" : "error";
  return el("div", {},
    el("div", { class: `banner ${tone}` }, el("strong", {}, t(`startup.${r.verdict.replace(/ /g, "_")}`))),
    table([t("appset.check"), t("appset.result")], [
      [t("startup.registered"), r.registered === true ? t("startup.found")
        : r.registered === false ? t("startup.not_found") : t("value.unknown")],
      [t("startup.mode"), task.mode === "boot" ? t("startup.at_boot")
        : task.mode === "logon" ? t("startup.at_logon") : "—"],
      [t("startup.points_here"), yesNo(r.points_to_current_app)],
      [t("startup.last_run"), runtime.last_run_time || t("value.unknown")],
      [t("startup.last_start"), last.started_at
        ? t("startup.last_start_value", { when: last.started_at, by: last.launched_by }) : t("startup.none")],
      [t("startup.initialised"), last.started_at ? yesNo(initialised) : "—"],
      ...(technical() ? [
        [t("startup.mechanism"), r.mechanism || "—"],
        [t("startup.command"), el("span", { class: "mono" }, task.command || "—")],
        [t("startup.folder"), el("span", { class: "mono" }, task.working_directory || "—")],
        [t("startup.last_result"), runtime.last_result || t("value.unknown")],
      ] : []),
    ]),
    (r.problems || []).length
      ? el("div", { class: "banner error mt-10" }, el("ul", {}, r.problems.map((p) => el("li", {}, p))))
      : null,
    technical() ? el("p", { class: "hint mono" }, r.startup_log) : null);
}

renderers["app-settings"] = (page) => loadInto(page, async () => {
  const [data, push] = await Promise.all([
    api("/settings"),
    api("/push").catch(() => ({ configured: false, enabled: false, phones: [], public_key: "",
      setup_command: "python -m installer.make_push_keys" })),
  ]);
  return el("div", { class: "stack" },
    appearanceCard(),
    detailCard(),
    alertsCard(data, push),
    maintenanceCard(),
    startupCard());
});
