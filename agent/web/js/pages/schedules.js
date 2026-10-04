import { api } from "../api.js";
import { render } from "../nav.js";
import { renderers } from "../state.js";
import { card, el, fmt, loadInto, table, toast } from "../ui.js";

renderers.schedules = (page) => loadInto(page, async () => {
  const data = await api("/schedules");
  const holder = el("div");
  const name = el("input", { type: "text", placeholder: "Nightly backup" });
  const task = el("select", {}, data.tasks.map((t) => el("option", { value: t }, t)));
  const kind = el("select", {}, ["daily", "weekly", "interval"].map((k) => el("option", { value: k }, k)));
  const expr = el("input", { type: "text", placeholder: "23:00 / sun 04:00 / 6h", class: "mono" });

  holder.append(card("Add a schedule",
    el("div", { class: "grid cols-4" },
      el("div", { class: "field" }, el("label", {}, "Name"), name),
      el("div", { class: "field" }, el("label", {}, "Task"), task),
      el("div", { class: "field" }, el("label", {}, "Repeat"), kind),
      el("div", { class: "field" }, el("label", {}, "When"), expr)),
    el("button", {
      class: "btn primary",
      onclick: async () => {
        try {
          await api("/schedules", {
            method: "POST",
            body: { name: name.value || task.value, task: task.value,
                    kind: kind.value, expr: expr.value, enabled: true, payload: {} },
          });
          toast("Schedule created"); render();
        } catch (err) { toast(err.message, "error"); }
      },
    }, "Create schedule")));

  holder.append(el("div", { class: "gap-section" },
    card("Schedules", data.schedules.length
      ? table(["Name", "Task", "When", "Next run", "Last result", ""], data.schedules.map((s) => [
          s.name, el("span", { class: "mono" }, s.task), el("span", { class: "mono" }, `${s.kind} ${s.expr}`),
          s.enabled ? fmt.time(s.next_run) : el("span", { class: "tag off" }, "disabled"),
          s.last_result || "—",
          el("div", { class: "btn-row" },
            el("button", {
              class: "btn small",
              onclick: async () => {
                await api(`/schedules/${s.id}`, {
                  method: "PUT",
                  body: { name: s.name, task: s.task, kind: s.kind, expr: s.expr,
                          payload: s.payload, enabled: !s.enabled },
                });
                render();
              },
            }, s.enabled ? "Disable" : "Enable"),
            el("button", {
              class: "btn small",
              onclick: async () => {
                const result = await api(`/schedules/${s.id}/run`, { method: "POST" });
                toast(result.result);
              },
            }, "Run now"),
            el("button", {
              class: "btn small danger",
              onclick: async () => {
                await api(`/schedules/${s.id}`, { method: "DELETE" });
                toast("Schedule deleted"); render();
              },
            }, "Delete")),
        ]))
      : el("div", { class: "empty" }, "No schedules"))));
  return holder;
});
