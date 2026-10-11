package io.github.peyoteheadlights.mcsc.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import io.github.peyoteheadlights.mcsc.core.Permissions
import io.github.peyoteheadlights.mcsc.core.Schedule
import io.github.peyoteheadlights.mcsc.core.Schedules

/**
 * What runs on its own at set times: each schedule with when it runs next
 * and how its last run went, Turn on or off, Run now and Delete, and a
 * form to add one. Only someone allowed to manage schedules gets the buttons.
 */
@Composable
fun SchedulesScreen(vm: AppViewModel, serverId: String, onBack: () -> Unit) {
    val world = vm.pages(serverId).world
    val strings = vm.strings
    val canManage = vm.canDo(Permissions.SCHEDULES_MANAGE)
    var deleting by remember { mutableStateOf<Schedule?>(null) }
    LaunchedEffect(serverId) { world.loadSchedules() }

    ServerFrame(
        vm, serverId,
        title = t("page.schedules"),
        onBack = onBack,
        refreshing = false,
        onRefresh = world::loadSchedules,
        overlay = {
            deleting?.let { schedule ->
                Confirm(
                    title = t("schedules.delete_title", "name" to schedule.name),
                    body = t("schedules.delete_body"),
                    confirm = t("schedules.delete"),
                    danger = true,
                    onConfirm = {
                        deleting = null
                        world.deleteSchedule(schedule, strings)
                    },
                    onDismiss = { deleting = null },
                )
            }
        },
    ) {
        val read = world.schedules
        val tasks = read.value?.tasks.orEmpty()
        val busy = world.busy
        item { SaidNote(world.said) }
        // Above the list, as the dashboard has it ("Add one above").
        if (canManage && read.value != null) item { AddSchedule(tasks, busy == "add") { name, task, kind, expr, added -> world.addSchedule(name, task, kind, expr, strings, added) } }
        item { SectionTitle(t("schedules.list")) }
        emptyOrProblem(Read(read.value?.schedules, read.problem, read.loading), "schedules.none", "schedules.none_hint", onRetry = world::loadSchedules)
        items(read.value?.schedules.orEmpty(), key = { it.id }) { schedule ->
            val colors = LocalColors.current
            Card {
                Item(
                    schedule.name,
                    subtitle = Schedules.taskName(strings, schedule.task, tasks) + " · " + Schedules.whenText(strings, schedule),
                )
                Note(t("schedules.col_next") + ": " + Schedules.next(strings, schedule))
                Note(t("schedules.col_result") + ": " + (schedule.lastResult ?: "—"), color = colors.text3)
                if (canManage) {
                    Presses(
                        listOf(
                            Press(
                                t(if (schedule.enabled) "schedules.turn_off" else "schedules.turn_on"),
                                { world.toggle(schedule, strings) },
                                enabled = busy == null,
                            ),
                            Press(
                                t("schedules.run_now"),
                                { world.runNow(schedule, strings) },
                                enabled = busy == null,
                            ),
                            Press(t("schedules.delete"), { deleting = schedule }, danger = true, enabled = busy == null),
                        ),
                    )
                }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun AddSchedule(
    tasks: List<String>,
    adding: Boolean,
    onAdd: (String, String, String, String, () -> Unit) -> Unit,
) {
    val strings = LocalStrings.current
    val colors = LocalColors.current
    var name by rememberSaveable { mutableStateOf("") }
    var task by rememberSaveable { mutableStateOf(tasks.firstOrNull().orEmpty()) }
    var kind by rememberSaveable { mutableStateOf(Schedules.KINDS.first()) }
    var expr by rememberSaveable { mutableStateOf("") }
    Column {
        SectionTitle(t("schedules.add"))
        Card {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedTextField(
                    value = name,
                    onValueChange = { name = it.take(Schedules.NAME_LENGTH) },
                    label = { Text(t("schedules.name")) },
                    placeholder = { Text(t("schedules.name_placeholder")) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Text(t("schedules.task"), color = colors.text2, modifier = Modifier.semantics { heading() })
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    for (option in tasks) {
                        FilterChip(
                            selected = task == option,
                            onClick = { task = option },
                            label = { Text(Schedules.taskName(strings, option, tasks)) },
                        )
                    }
                }
                Text(t("schedules.repeat"), color = colors.text2, modifier = Modifier.semantics { heading() })
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    for (option in Schedules.KINDS) {
                        FilterChip(selected = kind == option, onClick = { kind = option }, label = { Text(t(Schedules.kindKey(option))) })
                    }
                }
                OutlinedTextField(
                    value = expr,
                    onValueChange = { expr = it.take(Schedules.EXPR_LENGTH) },
                    label = { Text(t("schedules.when")) },
                    placeholder = { Text(t("schedules.when_placeholder")) },
                    supportingText = { Text(t("schedules.when_hint")) },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
                    modifier = Modifier.fillMaxWidth(),
                )
                Button(
                    onClick = { onAdd(name, task, kind, expr) { name = ""; expr = "" } },
                    enabled = !adding && task.isNotEmpty() && expr.isNotBlank(),
                    colors = ButtonDefaults.buttonColors(containerColor = colors.accent, contentColor = colors.accentText),
                ) { Text(t(if (adding) "action.saving" else "schedules.create")) }
            }
        }
    }
}
