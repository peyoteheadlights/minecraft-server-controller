import { api } from "../api.js";
import { render } from "../nav.js";
import { renderers } from "../state.js";
import { t, technical } from "../strings.js";
import { busy, card, confirmDialog, el, emptyState, fmt, loadInto, table, toast } from "../ui.js";

const KINDS = { daily: ["schedules.kind_daily", "schedules.every_daily"],
  weekly: ["schedules.kind_weekly", "schedules.every_weekly"],
  interval: ["schedules.kind_interval", "schedules.every_interval"] };

function taskName(task, tasks) {
  return tasks.includes(task) ? t(`task.${task}`) : task;
}

function whenText(s) {
  const kind = KINDS[s.kind];
  return kind ? t(kind[1], { expr: s.expr }) : `${s.kind} ${s.expr}`;
}

function addCard(data) {
  const name = el("input", { type: "text", id: "schedule-name", placeholder: t("schedules.name_placeholder") });
  const task = el("select", { id: "schedule-task" },
    data.tasks.map((k) => el("option", { value: k }, taskName(k, data.tasks))));
  const kind = el("select", { id: "schedule-kind" },
    Object.entries(KINDS).map(([k, [label]]) => el("option", { value: k }, t(label))));
  const expr = el("input", { type: "text", id: "schedule-when", class: "mono",
    placeholder: t("schedules.when_placeholder"), "aria-describedby": "schedule-when-hint" });
  const field = (id, label, input) => el("div", { class: "field" }, el("label", { for: id }, label), input);
  return card(t("schedules.add"),
    el("div", { class: "grid cols-4" },
      field("schedule-name", t("schedules.name"), name),
      field("schedule-task", t("schedules.task"), task),
      field("schedule-kind", t("schedules.repeat"), kind),
      field("schedule-when", t("schedules.when"), expr)),
    el("p", { class: "hint mt-10", id: "schedule-when-hint" }, t("schedules.when_hint")),
    el("div", { class: "btn-row mt-10" },
      el("button", {
        class: "btn primary", type: "button",
        onclick: (e) => busy(e.currentTarget, t("action.saving"), async () => {
          try {
            await api("/schedules", {
              method: "POST",
              body: { name: name.value || taskName(task.value, data.tasks), task: task.value,
                      kind: kind.value, expr: expr.value, enabled: true, payload: {} },
            });
            toast(t("schedules.created"), "success"); render();
          } catch (err) { toast(err.message, "error"); }
        }),
      }, t("schedules.create"))));
}

function scheduleRow(s, tasks) {
  return [
    s.name,
    technical() ? el("span", { class: "mono" }, s.task) : taskName(s.task, tasks),
    technical() ? el("span", { class: "mono" }, whenText(s)) : whenText(s),
    s.enabled ? fmt.time(s.next_run) : el("span", { class: "tag off" }, t("schedules.off")),
    s.last_result || "—",
    el("div", { class: "btn-row" },
      el("button", {
        class: "btn small", type: "button",
        onclick: async () => {
          try {
            await api(`/schedules/${s.id}`, {
              method: "PUT",
              body: { name: s.name, task: s.task, kind: s.kind, expr: s.expr,
                      payload: s.payload, enabled: !s.enabled },
            });
            render();
          } catch (err) { toast(err.message, "error"); }
        },
      }, s.enabled ? t("schedules.turn_off") : t("schedules.turn_on")),
      el("button", {
        class: "btn small", type: "button",
        onclick: (e) => busy(e.currentTarget, t("schedules.run_now"), async () => {
          try {
            const result = await api(`/schedules/${s.id}/run`, { method: "POST" });
            toast(result.result);
          } catch (err) { toast(err.message, "error"); }
        }),
      }, t("schedules.run_now")),
      el("button", {
        class: "btn small danger", type: "button",
        onclick: async () => {
          const ok = await confirmDialog({
            title: t("schedules.delete_title", { name: s.name }), body: t("schedules.delete_body"),
            confirmLabel: t("schedules.delete"), danger: true,
          });
          if (!ok) return;
          try {
            await api(`/schedules/${s.id}`, { method: "DELETE" });
            toast(t("schedules.deleted")); render();
          } catch (err) { toast(err.message, "error"); }
        },
      }, t("schedules.delete"))),
  ];
}

renderers.schedules = (page) => loadInto(page, async () => {
  const data = await api("/schedules");
  const holder = el("div", { class: "stack" });
  holder.append(card(t("schedules.list"), data.schedules.length
    ? table([t("schedules.col_name"), t("schedules.col_task"), t("schedules.col_when"),
        t("schedules.col_next"), t("schedules.col_result"), ""],
        data.schedules.map((s) => scheduleRow(s, data.tasks)))
    : emptyState(t("schedules.none"), t("schedules.none_hint"))));
  holder.append(addCard(data));
  return holder;
});
