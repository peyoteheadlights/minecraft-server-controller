/* "Let Bedrock players join", on a server's Settings page.

   Switching it on installs Geyser and Floodgate into the server's own
   files, so the server has to be stopped first. The address shown comes
   from this PC's real Tailscale address; when that can't be read the panel
   says so rather than inventing one. The differences are listed in plain
   words, because a Bedrock player does not get exactly the same game. */

import { api } from "../api.js";
import { state } from "../state.js";
import { t } from "../strings.js";
import { busy, card, confirmDialog, detailRows, el, problem, toast } from "../ui.js";

const serverUrl = (path) => `/servers/${encodeURIComponent(state.serverId)}${path}`;

export function crossplayCard(status, afterChange) {
  if (!status.available) {
    return card(t("cross.title"),
      el("p", { class: "hint mt-0" }, status.unavailable_reason || t("cross.not_for_type")),
      el("p", { class: "hint" }, t("cross.switch_type")));
  }

  const port = el("input", {
    id: "cross-port", type: "number", min: "1024", max: "65535",
    value: status.port || status.suggested_port || status.default_port,
  });

  async function turn(button, on) {
    if (on) {
      const ok = await confirmDialog({
        title: t("cross.on_title"),
        body: t("cross.on_body", { port: Number(port.value) || status.default_port }),
        confirmLabel: t("cross.on_button"),
      });
      if (!ok) return;
    }
    await busy(button, on ? t("cross.turning_on") : t("cross.turning_off"), async () => {
      try {
        await api(serverUrl("/crossplay"), {
          method: "PUT",
          body: { enabled: on, port: on ? Number(port.value) || null : null },
        });
        toast(on ? t("cross.on_done") : t("cross.off_done"), "success", 10000);
        if (afterChange) await afterChange();
      } catch (err) { toast(err.message, "error", 14000); }
    });
  }

  return card(t("cross.title"),
    el("p", { class: "hint mt-0" }, t("cross.what")),
    status.missing_mod
      ? el("div", { class: "banner warn" }, el("div", { class: "grow" },
          t("cross.needs_mod", { mod: status.missing_mod })))
      : null,
    status.enabled
      ? detailRows([
          [t("cross.address"), status.address],
          [t("cross.ready"), status.ready ? t("cross.ready_yes") : t("cross.files_missing")],
          [t("cross.names"), t("cross.names_value", { prefix: status.username_prefix })],
        ])
      : el("div", { class: "field" },
          el("label", { for: "cross-port" }, t("cross.port")), port,
          el("div", { class: "hint" }, t("cross.port_hint"))),
    status.enabled && status.address_unknown
      ? el("p", { class: "hint" }, status.address_unknown)
      : null,
    el("div", { class: "btn-row mt-12" },
      status.enabled
        ? el("button", { class: "btn", type: "button", onclick: (e) => turn(e.currentTarget, false) },
            t("cross.turn_off"))
        : el("button", { class: "btn primary", type: "button", onclick: (e) => turn(e.currentTarget, true) },
            t("cross.turn_on")),
      el("span", { class: "hint" }, t("cross.stopped_first"))),
    el("div", { class: "mt-12" },
      el("span", { class: "field-label" }, t("cross.differences")),
      el("ul", { class: "plain-list" },
        (status.differences || []).map((line) => el("li", {}, line)))));
}

export async function crossplayPanel(afterChange) {
  try {
    const status = await api(serverUrl("/crossplay"));
    return crossplayCard(status, afterChange);
  } catch (err) {
    return card(t("cross.title"), problem(err.message));
  }
}
