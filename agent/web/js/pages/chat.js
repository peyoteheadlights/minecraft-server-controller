/* The chat page: what players said in the game, and a box to say
   something back as "Server". Every line here was printed by the server's
   own console; a message sent from here appears once the server prints it,
   never before. The Console page stays for commands and raw output. */

import { api } from "../api.js";
import { renderers, state } from "../state.js";
import { t } from "../strings.js";
import { $, el, emptyState, fmt, toast } from "../ui.js";

export function chatLine(message) {
  const who = message.kind === "server"
    ? el("span", { class: "chat-who chat-server" }, t("chat.server"))
    : el("span", { class: "chat-who" }, message.name || "");
  return el("div", { class: `chat-line kind-${message.kind}` },
    el("span", { class: "time" }, fmt.clock(message.ts)),
    who,
    el("span", { class: "chat-text" }, message.kind === "action" ? `• ${message.text}` : message.text));
}

function nearBottom(node) {
  return node.scrollHeight - node.scrollTop - node.clientHeight < 60;
}

export function renderChatLines() {
  const wrap = $("#chat-wrap");
  if (!wrap) return;
  const lines = state.chat.slice(-state.chatLimit);
  if (!lines.length) {
    wrap.replaceChildren(emptyState(t("chat.empty"), t("chat.empty_hint")));
    return;
  }
  const fragment = document.createDocumentFragment();
  lines.forEach((m) => fragment.append(chatLine(m)));
  wrap.replaceChildren(fragment);
  wrap.scrollTop = wrap.scrollHeight;
}

export function appendChatLine(message) {
  state.chat.push(message);
  if (state.chat.length > state.chatLimit + 100) state.chat.splice(0, 100);
  const wrap = $("#chat-wrap");
  if (!wrap) return;
  const follow = nearBottom(wrap);
  const empty = wrap.querySelector(".empty");
  if (empty) empty.remove();
  wrap.append(chatLine(message));
  while (wrap.children.length > state.chatLimit) wrap.firstChild.remove();
  if (follow) wrap.scrollTop = wrap.scrollHeight;
}

async function send(input, button) {
  const text = input.value.trim();
  if (!text) return;
  button.disabled = true;
  try {
    await api("/chat", { method: "POST", body: { message: text } });
    input.value = "";
  } catch (err) {
    toast(err.message, "error", 8000);
  } finally {
    updateChatControls();
    input.focus();
  }
}

/* The box follows the server: it opens when the server comes online and
   closes when it stops, without leaving the page. */
export function updateChatControls() {
  const running = (state.status || {}).state === "ONLINE";
  const input = $("#chat-input");
  const button = $("#chat-send");
  const hint = $("#chat-hint");
  if (input) input.disabled = !running;
  if (button) button.disabled = !running;
  if (hint) hint.textContent = running ? t("chat.hint") : t("chat.offline");
}

renderers.chat = (page) => {
  const running = (state.status || {}).state === "ONLINE";
  const wrap = el("div", { class: "chat-body", id: "chat-wrap", role: "log",
                           "aria-label": t("chat.log_label"), tabindex: "0" });
  const input = el("input", {
    id: "chat-input", class: "input", type: "text", maxlength: "220", placeholder: t("chat.placeholder"),
    "aria-label": t("chat.input_label"), autocomplete: "off",
    disabled: running ? false : true,
    onkeydown: (event) => { if (event.key === "Enter") send(input, button); },
  });
  const button = el("button", { id: "chat-send", class: "btn primary small", type: "button",
    disabled: running ? false : true, onclick: () => send(input, button) }, t("chat.send"));

  page.append(
    el("div", { class: "chat" }, wrap,
      el("div", { class: "chat-foot" },
        el("span", { class: "chat-as" }, t("chat.as_server")), input, button)),
    el("p", { class: "hint", id: "chat-hint" }, running ? t("chat.hint") : t("chat.offline")));

  renderChatLines();
  // The log only holds what this browser has seen live, so load the recent
  // lines the agent kept.
  api("/chat?lines=200").then((data) => {
    state.chat = data.messages || [];
    renderChatLines();
  }).catch(() => { /* the empty state already says there is nothing yet */ });
  if (running) input.focus({ preventScroll: true });
};
