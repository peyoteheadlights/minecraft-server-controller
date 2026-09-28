/* TPS monitoring panel on the Performance page.
   Shows how TPS is being read, and lets the user override the command.
   Uses the dashboard's own helpers (window.MCSC). */

(function () {
  "use strict";
  window.MCSC_EXT = window.MCSC_EXT || {};

  const STATE_TEXT = {
    active: ["Active", "ok"],
    detecting: ["Detecting…", "warn"],
    unavailable: ["Unavailable", "error"],
    disabled: ["Off", "off"],
    idle: ["Waiting for the server", "off"],
  };
  const DETECTION_TEXT = { automatic: "Automatic", remembered: "Automatic (remembered)", manual: "Manual" };

  window.MCSC_EXT.tps = function (node) {
    const { el, api, card, toast, confirmDialog, busy, fmt } = window.MCSC;
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
          `TPS monitoring status could not be loaded. ${err.message}`)));
    }

    function row(label, value) {
      return el("div", { class: "row" }, el("span", { class: "row-label" }, label),
        el("span", { class: "row-value" }, value));
    }

    function render(s) {
      const [stateText, tag] = STATE_TEXT[s.state] || [s.state, "off"];
      const online = s.server_state === "ONLINE";
      const rows = [
        row("Status", el("span", { class: `tag ${tag}` }, stateText)),
        row("Command", s.command ? el("span", { class: "mono" }, s.command)
          : (s.mode === "manual" ? "Set manually, not answering" : "None")),
        row("Detection", s.mode === "manual" ? "Manual"
          : s.mode === "disabled" ? "Off" : (DETECTION_TEXT[s.detection] || "Automatic")),
        row("Last reading", s.last_reading_at ? `${fmt.ago(s.last_reading_at)}` : "None yet"),
      ];
      const children = [el("div", { class: "rows" }, rows)];
      if (s.state === "unavailable" || s.state === "disabled") {
        children.push(el("p", { class: "hint" }, s.message));
        if ((s.tried || []).length) {
          children.push(el("ul", { class: "hint tps-tried" }, s.tried.map((t) =>
            el("li", {}, el("span", { class: "mono" }, t.command), `: ${t.detail}`))));
        }
      }
      const actions = el("div", { class: "btn-row", style: "margin-top:12px" },
        el("button", { class: "btn small", type: "button", onclick: changeCommand },
          s.state === "unavailable" ? "Configure Manually" : "Change Command"),
        s.mode === "auto" ? el("button", {
          class: "btn small", type: "button", disabled: !online,
          title: online ? "" : "The server must be online",
          onclick: (e) => busy(e.currentTarget, "Detecting…", async () => {
            try { await api("/tps/detect", { method: "POST" }); } catch (err) { toast(err.message, "error"); }
            load();
          }),
        }, "Detect Again") : null);
      children.push(actions);
      return card("TPS monitoring", ...children);
    }

    async function changeCommand() {
      const select = el("select", { class: "input", "aria-label": "TPS command" },
        el("option", { value: "auto" }, "Detect automatically (recommended)"),
        el("option", { value: "tick query" }, "tick query (Minecraft 1.20.3+)"),
        el("option", { value: "tps" }, "tps (Carpet)"),
        el("option", { value: "spark tps" }, "spark tps (spark)"),
        el("option", { value: "custom" }, "Other command…"),
        el("option", { value: "off" }, "Turn off TPS monitoring"));
      const custom = el("input", { class: "input", type: "text", placeholder: "Minecraft command",
        "aria-label": "Custom TPS command", hidden: true });
      select.addEventListener("change", () => { custom.hidden = select.value !== "custom"; });
      const body = el("div", {},
        el("p", {}, "Choose how the agent asks the server for its tick rate. The command is sent "
          + "to Minecraft only, and checked once each time the server starts."),
        el("div", { class: "field" }, select), el("div", { class: "field" }, custom));
      const ok = await confirmDialog({ title: "TPS command", body, confirmLabel: "Save" });
      if (!ok) return;
      const command = select.value === "custom" ? custom.value.trim() : select.value;
      try {
        await api("/tps", { method: "PUT", body: { command } });
        toast(command === "auto" ? "TPS command will be detected automatically."
          : command === "off" ? "TPS monitoring is off." : `TPS will be read with "${command}".`, "success");
      } catch (err) {
        toast(err.message, "error", 9000);
      }
      load();
    }
  };
})();
