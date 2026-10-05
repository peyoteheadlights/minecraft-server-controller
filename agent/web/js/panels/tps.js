/* How server speed (TPS) is read, on the Performance page, and a way to
   choose the command the agent asks Minecraft with. */

import { api } from "../api.js";
import { t } from "../strings.js";
import { busy, confirmDialog, el, fmt, toast } from "../ui.js";

const STATE_TAG = { active: "ok", detecting: "warn", unavailable: "error", disabled: "off", idle: "off" };

export function tpsPanel(node) {
  let timer = null;
  load();

  function load() {
    api("/tps")
      .then((status) => {
        node.replaceChildren(render(status));
        clearTimeout(timer);
        // Follow detection while it runs, including the moments after the
        // server comes online and before detection begins; then stop.
        const pending = status.state === "detecting"
          || (status.state === "idle" && ["ONLINE", "STARTING"].includes(status.server_state));
        if (pending && node.isConnected) timer = setTimeout(load, 1500);
      })
      .catch((err) => node.replaceChildren(el("div", { class: "banner error" },
        t("tps.load_failed", { error: err.message }))));
  }

  function row(label, value) {
    return el("div", { class: "row" }, el("span", { class: "row-label" }, label),
      el("span", { class: "row-value" }, value));
  }

  function render(s) {
    const online = s.server_state === "ONLINE";
    const mode = s.mode === "manual" ? t("tps.manual") : s.mode === "disabled" ? t("tps.off")
      : (s.detection === "remembered" ? t("tps.auto_remembered") : t("tps.auto"));
    const children = [el("div", { class: "rows" },
      row(t("tps.status"), el("span", { class: `tag ${STATE_TAG[s.state] || "off"}` }, t(`tps.state_${s.state}`))),
      row(t("tps.command"), s.command ? el("span", { class: "mono" }, s.command)
        : (s.mode === "manual" ? t("tps.manual_silent") : t("tps.none"))),
      row(t("tps.detection"), mode),
      row(t("tps.last_reading"), s.last_reading_at ? fmt.ago(s.last_reading_at) : t("tps.none_yet")))];
    if (s.state === "unavailable" || s.state === "disabled") {
      children.push(el("p", { class: "hint" }, s.message));
      if ((s.tried || []).length) {
        children.push(el("ul", { class: "hint tps-tried" }, s.tried.map((tried) =>
          el("li", {}, el("span", { class: "mono" }, tried.command), `: ${tried.detail}`))));
      }
    }
    children.push(el("div", { class: "btn-row mt-12" },
      el("button", { class: "btn small", type: "button", onclick: changeCommand },
        s.state === "unavailable" ? t("tps.configure") : t("tps.change")),
      s.mode === "auto" ? el("button", {
        class: "btn small", type: "button", disabled: !online,
        title: online ? "" : t("tps.needs_online"),
        onclick: (e) => busy(e.currentTarget, t("tps.detecting"), async () => {
          try { await api("/tps/detect", { method: "POST" }); } catch (err) { toast(err.message, "error"); }
          load();
        }),
      }, t("tps.detect_again")) : null));
    return el("div", {}, ...children);
  }

  async function changeCommand() {
    const select = el("select", { class: "input", "aria-label": t("tps.command") },
      el("option", { value: "auto" }, t("tps.opt_auto")),
      el("option", { value: "tick query" }, t("tps.opt_tick")),
      el("option", { value: "tps" }, t("tps.opt_carpet")),
      el("option", { value: "spark tps" }, t("tps.opt_spark")),
      el("option", { value: "custom" }, t("tps.opt_custom")),
      el("option", { value: "off" }, t("tps.opt_off")));
    const custom = el("input", { class: "input", type: "text", placeholder: t("tps.custom_placeholder"),
      "aria-label": t("tps.custom_label"), hidden: true });
    select.addEventListener("change", () => { custom.hidden = select.value !== "custom"; });
    const body = el("div", {},
      el("p", {}, t("tps.dialog_body")),
      el("div", { class: "field" }, select), el("div", { class: "field" }, custom));
    const ok = await confirmDialog({ title: t("tps.dialog_title"), body, confirmLabel: t("action.save") });
    if (!ok) return;
    const command = select.value === "custom" ? custom.value.trim() : select.value;
    try {
      await api("/tps", { method: "PUT", body: { command } });
      toast(command === "auto" ? t("tps.saved_auto") : command === "off" ? t("tps.saved_off")
        : t("tps.saved_command", { command }), "success");
    } catch (err) {
      toast(err.message, "error", 9000);
    }
    load();
  }
}
