import { api } from "../api.js";
import { logLine } from "./overview.js";
import { renderers, state } from "../state.js";
import { t } from "../strings.js";
import { $, announce, busy, confirmDialog, el, emptyState, icon, toast } from "../ui.js";

export function consoleVisible() {
  const needle = state.filter.toLowerCase();
  return needle
    ? state.console.filter((line) => (line.raw || "").toLowerCase().includes(needle))
    : state.console;
}

export function nearBottom(node) {
  return node.scrollHeight - node.scrollTop - node.clientHeight < 40;
}

export function renderConsoleLines() {
  const wrap = $("#console-wrap");
  if (!wrap) return;
  const lines = consoleVisible().slice(-state.consoleLimit);
  if (!lines.length) {
    wrap.replaceChildren(state.filter
      ? emptyState(t("console.no_match"), t("console.no_match_hint", { filter: state.filter }))
      : emptyState(t("console.empty"), t("console.empty_hint")));
    return;
  }
  const fragment = document.createDocumentFragment();
  lines.forEach((line) => fragment.append(logLine(line)));
  wrap.replaceChildren(fragment);
  if (state.autoscroll) wrap.scrollTop = wrap.scrollHeight;
}

export function appendConsoleLine(line) {
  const wrap = $("#console-wrap");
  if (!wrap) return;
  if (state.filter && !(line.raw || "").toLowerCase().includes(state.filter.toLowerCase())) return;
  // follow the newest line only when the reader has not scrolled up
  const follow = state.autoscroll && nearBottom(wrap);
  const empty = wrap.querySelector(".empty");
  if (empty) empty.remove();
  wrap.append(logLine(line));
  while (wrap.children.length > state.consoleLimit) wrap.firstChild.remove();
  if (follow) wrap.scrollTop = wrap.scrollHeight;
}

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (e) {
    const area = el("textarea", { class: "offscreen" });
    area.value = text;
    document.body.append(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    return ok;
  }
}

renderers.console = (page, toolbar) => {
  const toggle = (label, iconName, key, title) => {
    const button = el("button", {
      class: "btn small", type: "button", title, "aria-pressed": state[key] ? "true" : "false",
      onclick: () => {
        state[key] = !state[key];
        button.setAttribute("aria-pressed", state[key] ? "true" : "false");
        if (key === "autoscroll" && state.autoscroll) {
          const wrap = $("#console-wrap");
          if (wrap) wrap.scrollTop = wrap.scrollHeight;
        }
        if (key === "paused" && !state.paused) renderConsoleLines();
        announce(t(state[key] ? "console.toggle_on" : "console.toggle_off", { label }));
      },
    }, icon(iconName), label);
    return button;
  };

  const filter = el("input", {
    class: "input", type: "search", placeholder: t("console.filter"), "aria-label": t("console.filter_label"),
    value: state.filter,
    oninput: (e) => { state.filter = e.target.value; renderConsoleLines(); },
  });
  toolbar.append(
    el("div", { class: "search" }, icon("search"), filter),
    toggle(t("console.follow"), "follow", "autoscroll", t("console.follow_title")),
    toggle(t("console.pause"), "pause", "paused", t("console.pause_title")),
    el("button", {
      class: "btn small", type: "button", title: t("console.copy_title"),
      onclick: async () => {
        const ok = await copyText(consoleVisible().map((l) => l.raw).join("\n"));
        toast(ok ? t("console.copied") : t("console.copy_unavailable"), ok ? "success" : "warn");
      },
    }, icon("copy"), t("console.copy")),
    el("button", {
      class: "btn small", type: "button", title: t("console.download_title"),
      onclick: () => {
        const body = consoleVisible().map((l) => l.raw).join("\n");
        const url = URL.createObjectURL(new Blob([body], { type: "text/plain" }));
        const link = el("a", { href: url, download: `console-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.log` });
        document.body.append(link); link.click(); link.remove();
        URL.revokeObjectURL(url);
      },
    }, icon("download"), t("console.download")),
    el("button", {
      class: "btn small", type: "button",
      title: t("console.clear_title"),
      onclick: async (e) => {
        await busy(e.currentTarget, t("console.clearing"), async () => {
          await api("/logs/clear", { method: "POST" });
          state.console = [];
          renderConsoleLines();
        });
        toast(t("console.cleared"), "info");
      },
    }, icon("clear"), t("console.clear")));

  const wrap = el("div", { class: "console-body", id: "console-wrap", role: "log",
                           "aria-label": t("console.output_label"), tabindex: "0" });
  const input = el("input", {
    class: "input", type: "text", placeholder: t("console.command_placeholder"),
    "aria-label": t("console.command_label"), autocomplete: "off", spellcheck: "false",
    onkeydown: (event) => { if (event.key === "Enter") sendCommand(input, send); },
  });
  const send = el("button", { class: "btn primary small", type: "button",
                              onclick: () => sendCommand(input, send) }, t("console.send"));
  page.append(
    el("div", { class: "console" },
      wrap,
      el("div", { class: "console-foot" }, el("span", { class: "prompt", "aria-hidden": "true" }, ">"), input, send)),
    el("p", { class: "hint console-hint" },
      t("console.hint"), " ",
      el("button", {
        class: "btn plain small", type: "button",
        onclick: async (e) => {
          await busy(e.currentTarget, t("status.loading"), async () => {
            const data = await api("/logs?lines=500");
            state.console = data.lines;
            renderConsoleLines();
          });
        },
      }, t("console.load_more"))));
  renderConsoleLines();
  input.focus({ preventScroll: true });
};

export async function sendCommand(input, button) {
  const command = input.value.trim();
  if (!command) return;
  try {
    const check = await api(`/server/command/check?command=${encodeURIComponent(command)}`);
    if (!check.valid && check.error && !check.danger_reason) {
      toast(check.error, "error", 8000);
      return;
    }
    if (check.danger_reason) {
      const ok = await confirmDialog({
        title: t("console.run_title", { command }),
        body: check.danger_reason,
        confirmLabel: t("console.run"),
        danger: true,
      });
      if (!ok) return;
    }
    await busy(button, t("console.sending"), async () => {
      await api("/server/command", { method: "POST", body: { command, confirm: true } });
    });
    input.value = "";
    input.focus();
  } catch (err) {
    toast(err.message, "error", 8000);
  }
}
