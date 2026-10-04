import { api } from "../api.js";
import { chart } from "../charts.js";
import { tpsPanel } from "../panels/tps.js";
import { renderers } from "../state.js";
import { card, el, fmt, known, loadInto, metric, table } from "../ui.js";

renderers.performance = (page) => {
  const tpsNode = el("div");
  const rest = el("div", { class: "gap-section" });
  page.append(tpsNode, rest);
  tpsPanel(tpsNode);
  return renderPerformance(rest);
};

export const renderPerformance = (page) => loadInto(page, async () => {
  const [data, health] = await Promise.all([api("/performance?hours=6"), api("/health/server")]);
  const holder = el("div");
  const current = data.current;

  holder.append(el("div", { class: "grid cols-4" },
    metric("CPU", fmt.pct(current.cpu_percent), `threshold ${data.thresholds.cpu_percent}%`,
      { bar: current.cpu_percent }),
    metric("RAM", fmt.pct(current.ram_percent), `threshold ${data.thresholds.ram_percent}%`,
      { bar: current.ram_percent }),
    metric("Disk free", fmt.gb(current.disk_free_gb),
      known(current.disk_free_gb) || !current.disk_unknown_reason
        ? `alert under ${data.thresholds.disk_free_gb} GB` : current.disk_unknown_reason),
    metric("Network", `${(current.net_recv_mb_s || 0).toFixed(2)}`, "MB/s received", {})));

  holder.append(el("div", { class: "gap-section" },
    card("Last 6 hours",
      chart(data.history, "cpu_percent", "CPU %"),
      chart(data.history, "ram_used_mb", "RAM used (MB)"),
      data.history.some((h) => h.tps !== null)
        ? chart(data.history, "tps", "TPS")
        : el("p", { class: "hint" },
            "No TPS samples: no tick-rate command answered on this server."))));

  holder.append(el("div", { class: "grid cols-2 mt-14" },
    card("Health checks",
      el("div", { class: "banner mb-10" },
        el("strong", {}, ({
          "ALL CHECKS VERIFIED": "All checks verified",
          "PARTIALLY VERIFIED": "Partially verified",
          "ATTENTION NEEDED": "Attention needed",
        })[health.overall] || health.overall),
        health.note ? el("div", { class: "hint" }, health.note) : null,
        health.unverified && health.unverified.length
          ? el("div", { class: "hint" }, `Not verified: ${health.unverified.join(", ")}`)
          : null),
      health.checks.map((check) => el("div", { class: "check" },
        el("span", { class: "name" }, check.name),
        el("span", { class: `val tag ${check.status === "ok" ? "ok" : check.status === "unknown" ? "off" : "warn"}` },
          check.value === null || check.value === undefined ? "unknown" : String(check.value)),
        el("span", { class: "detail" },
          check.detail
          + (check.threshold !== null && check.threshold !== undefined ? ` (limit ${check.threshold})` : "")
          + (check.source ? ` [source: ${check.source}]` : ""))))),
    card("Storage", table(["Category", "Size"], [
      ["Worlds", fmt.gb(data.storage.worlds_gb)],
      ["Backups", fmt.gb(data.storage.backups_gb)],
      ["Mods", fmt.gb(data.storage.mods_gb)],
      ["Logs", fmt.gb(data.storage.logs_gb)],
      ["Other server files", fmt.gb(data.storage.other_gb)],
      ["Free on drive", data.storage.free_gb === null && data.storage.free_unknown_reason
        ? `Unknown: ${data.storage.free_unknown_reason}` : fmt.gb(data.storage.free_gb)],
    ]))));
  return holder;
});
