/* "How friends join", on each server's Overview: the address and port to
   type into Minecraft, with copy buttons. Every address here was read
   from this PC by the agent; when one couldn't be read the card says so
   instead of showing a likely-looking one. Whether the server can be
   reached from the internet is not known, because nothing tests it. */

import { t, technical } from "../strings.js";
import { el, icon, toast } from "../ui.js";

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast(t("join.copied", { text }), "success", 3000);
  } catch (err) {
    toast(t("join.copy_failed"), "warn", 6000);
  }
}

function addressRow(text, note = null) {
  return el("div", { class: "join-row" },
    el("code", { class: "join-address" }, text),
    el("button", { class: "btn small plain", type: "button", "aria-label": t("join.copy_label", { text }),
      title: t("join.copy"), onclick: () => copy(text) }, icon("copy"), el("span", {}, t("join.copy"))),
    note ? el("span", { class: "hint" }, note) : null);
}

function block(titleKey, hintKey, ...rows) {
  return el("div", { class: "join-block" },
    el("h3", { class: "subheading" }, t(titleKey)),
    el("p", { class: "hint mt-0" }, t(hintKey)),
    ...rows);
}

function withPort(host, port) {
  return `${host}:${port}`;
}

export function friendsCard(info) {
  const java = info.java;
  const port = java.port;
  const home = java.local.filter((a) => technical() || !a.virtual);
  const homeRows = home.length
    ? home.map((a) => addressRow(withPort(a.address, port),
        technical() || home.length > 1 ? t("join.adapter", { adapter: a.adapter }) : null))
    : [el("p", { class: "unknown-note" }, t("join.no_local"))];

  const ts = java.tailscale;
  const tsRows = [];
  if (ts.address) {
    tsRows.push(addressRow(withPort(ts.address, port)));
    if (ts.dns_name) tsRows.push(addressRow(withPort(ts.dns_name, port)));
    if (!ts.verified) tsRows.push(el("p", { class: "hint" }, t("join.ts_unconfirmed")));
    else if (ts.connected === false) tsRows.push(el("p", { class: "hint" }, t("join.ts_off")));
  } else {
    tsRows.push(el("p", { class: "unknown-note" }, t("join.no_tailscale")));
  }
  if (technical() && ts.detail) tsRows.push(el("p", { class: "hint mono" }, ts.detail));

  const portNote = el("p", { class: "hint" },
    t("join.port", { port, source: java.port_source }),
    java.default_port ? ` ${t("join.default_port")}` : "");

  const bedrock = info.bedrock;
  const bedrockHome = bedrock ? (bedrock.local || []).filter((a) => technical() || !a.virtual) : [];
  const bedrockRows = bedrock && bedrock.port
    ? [
        ...bedrockHome.map((a) => addressRow(a.address,
          `${t("join.bedrock_port", { port: bedrock.port })} · ${t("join.home")}`)),
        bedrock.address
          ? addressRow(bedrock.address, `${t("join.bedrock_port", { port: bedrock.port })} · ${t("join.tailscale")}`)
          : el("p", { class: "unknown-note" }, t("join.no_tailscale")),
      ]
    : [el("p", { class: "unknown-note" }, t("join.no_bedrock_port"))];
  const bedrockBlock = bedrock
    ? block("join.bedrock", "join.bedrock_hint",
        ...bedrockRows,
        bedrock.ready ? null : el("p", { class: "hint" }, t("cross.files_missing")),
        el("p", { class: "hint" }, t("join.consoles")))
    : null;

  return el("div", { class: "join-card" },
    el("div", { class: "columns" },
      block("join.home", "join.home_hint", ...homeRows),
      block("join.tailscale", "join.tailscale_hint", ...tsRows)),
    portNote,
    bedrockBlock,
    el("p", { class: "hint" }, t("join.internet")));
}
