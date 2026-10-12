package io.github.peyoteheadlights.mcsc.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import io.github.peyoteheadlights.mcsc.core.Moderators
import io.github.peyoteheadlights.mcsc.core.formatFingerprint

/** The screens before the app is paired and signed in. */
@Composable
fun Onboarding(vm: AppViewModel) {
    when (val stage = vm.stage) {
        Stage.Welcome -> Welcome(vm)
        Stage.Scan -> {
            BackHandler { vm.back() }
            ScanScreen(
                onCode = { vm.submit(it, scanned = true) },
                onType = { vm.go(Stage.Type()) },
                onBack = { vm.back() },
            )
        }
        is Stage.Type -> {
            BackHandler { vm.back() }
            TypeAddress(vm, stage)
        }
        Stage.Checking -> Busy(t("mobile.pair.checking"))
        is Stage.Confirm -> {
            BackHandler { vm.back() }
            ConfirmFingerprint(vm, stage)
        }
        is Stage.Problem -> {
            BackHandler { vm.back() }
            Problem(vm, stage)
        }
        is Stage.Switch -> {
            BackHandler { vm.back() }
            Page {}
            Confirm(
                title = t("mobile.rescan.other_title"),
                body = t(
                    "mobile.rescan.other_body",
                    "address" to "${stage.pairing.host}:${stage.pairing.port}",
                    "current" to "${stage.current.host}:${stage.current.port}",
                ),
                confirm = t("mobile.rescan.switch"),
                danger = true,
                onConfirm = { vm.check(stage.pairing) },
                onDismiss = { vm.back() },
            )
        }
        is Stage.SignIn -> SignIn(vm, stage)
        is Stage.Invite -> {
            BackHandler { vm.back() }
            InviteAccount(vm, stage)
        }
        Stage.Ready -> Unit
    }
}

@Composable
private fun Page(title: String? = null, onBack: (() -> Unit)? = null, content: @Composable () -> Unit) {
    val colors = LocalColors.current
    Scaffold(
        containerColor = colors.sheet,
        topBar = { if (title != null || onBack != null) Bar(title ?: "", onBack) },
    ) { padding ->
        Column(
            Modifier
                .padding(padding)
                .fillMaxSize()
                .imePadding()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 24.dp, vertical = 16.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) { content() }
    }
}

@Composable
private fun Lead(text: String) {
    Text(text, style = MaterialTheme.typography.bodyLarge, color = LocalColors.current.text2)
}

@Composable
private fun Welcome(vm: AppViewModel) {
    val context = LocalContext.current
    val clipboard = LocalClipboardManager.current
    Page {
        Spacer(Modifier.height(24.dp))
        Text(
            t("mobile.welcome.title"),
            style = MaterialTheme.typography.headlineMedium,
            color = LocalColors.current.text,
            modifier = Modifier.semantics { heading() },
        )
        Lead(t("mobile.welcome.lead"))
        Card(Modifier.padding(vertical = 8.dp)) {
            Text(
                t("mobile.welcome.need_tailscale"),
                color = LocalColors.current.text,
                modifier = Modifier.padding(16.dp),
            )
            Item(t("mobile.welcome.get_tailscale"), onClick = { openLink(context, Links.TAILSCALE_ANDROID) }, external = true)
        }
        Button(onClick = { vm.go(Stage.Scan) }, modifier = Modifier.fillMaxWidth().height(52.dp)) {
            Text(t("mobile.welcome.scan"))
        }
        Note(t("mobile.welcome.scan_hint"), modifier = Modifier.padding(horizontal = 0.dp))
        TextButton(onClick = { vm.go(Stage.Type()) }, modifier = Modifier.fillMaxWidth()) {
            Text(t("mobile.welcome.type"))
        }
        OutlinedButton(onClick = { vm.pasteInvite(clipboard.getText()?.text) }, modifier = Modifier.fillMaxWidth()) {
            Text(t("mobile.welcome.paste"))
        }
        Note(t("mobile.welcome.paste_hint"), modifier = Modifier.padding(horizontal = 0.dp))
    }
}

/** An invite opened: the name the owner chose is filled in; they choose the password. */
@Composable
private fun InviteAccount(vm: AppViewModel, stage: Stage.Invite) {
    var password by rememberSaveable { mutableStateOf("") }
    var repeat by rememberSaveable { mutableStateOf("") }
    val short = password.isNotEmpty() && password.length < Moderators.MIN_PASSWORD
    val mismatch = repeat.isNotEmpty() && password != repeat
    val ready = !stage.busy && password.length >= Moderators.MIN_PASSWORD && password == repeat
    Page(t("mobile.invite.title"), onBack = { vm.back() }) {
        Lead(t("mobile.invite.lead"))
        vm.pairing?.let { Note(t("mobile.signin.pc", "host" to it.host), modifier = Modifier.padding(horizontal = 0.dp)) }
        stage.problem?.let { Text(it.text(), color = LocalColors.current.danger) }
        OutlinedTextField(
            value = stage.invite.username,
            onValueChange = {},
            readOnly = true,
            label = { Text(t("mobile.invite.name")) },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        PasswordField(password, { password = it }, t("mobile.invite.password"), error = if (short) t("mobile.invite.too_short") else null, hint = t("mobile.invite.hint"))
        PasswordField(repeat, { repeat = it }, t("mobile.invite.repeat"), error = if (mismatch) t("mobile.invite.mismatch") else null)
        Button(
            onClick = { if (ready) vm.acceptInvite(password) },
            enabled = ready,
            modifier = Modifier.fillMaxWidth().height(52.dp),
        ) { Text(t(if (stage.busy) "mobile.invite.going" else "mobile.invite.go")) }
        Note(t("mobile.signin.stays"), modifier = Modifier.padding(horizontal = 0.dp))
    }
}

@Composable
private fun TypeAddress(vm: AppViewModel, stage: Stage.Type) {
    var text by rememberSaveable { mutableStateOf("") }
    Page(t("mobile.type.title"), onBack = { vm.back() }) {
        OutlinedTextField(
            value = text,
            onValueChange = { text = it },
            label = { Text(t("mobile.type.label")) },
            singleLine = true,
            isError = stage.problem != null,
            supportingText = { Text(stage.problem?.text() ?: t("mobile.type.hint")) },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri, imeAction = ImeAction.Go, autoCorrectEnabled = false),
            keyboardActions = KeyboardActions(onGo = { vm.submit(text, scanned = false) }),
            modifier = Modifier.fillMaxWidth(),
        )
        Button(
            onClick = { vm.submit(text, scanned = false) },
            enabled = text.isNotBlank(),
            modifier = Modifier.fillMaxWidth().height(52.dp),
        ) { Text(t("mobile.type.go")) }
    }
}

@Composable
fun Busy(text: String) {
    Column(
        Modifier.fillMaxSize(),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        CircularProgressIndicator()
        Spacer(Modifier.height(16.dp))
        Text(text, color = LocalColors.current.text2)
    }
}

@Composable
private fun ConfirmFingerprint(vm: AppViewModel, stage: Stage.Confirm) {
    var refused by rememberSaveable { mutableStateOf(false) }
    Page(t("mobile.pair.confirm_title"), onBack = { vm.back() }) {
        Lead(t("mobile.pair.confirm_lead"))
        Card {
            Item(t("pair.fingerprint"))
            Text(
                formatFingerprint(stage.fingerprint),
                fontFamily = FontFamily.Monospace,
                color = LocalColors.current.text,
                modifier = Modifier.padding(start = 16.dp, end = 16.dp, bottom = 16.dp),
            )
        }
        if (refused) {
            Text(t("mobile.pair.confirm_no_body"), color = LocalColors.current.danger)
            Button(onClick = { vm.go(Stage.Scan) }, modifier = Modifier.fillMaxWidth()) { Text(t("mobile.welcome.scan")) }
        } else {
            Button(
                onClick = { vm.confirmFingerprint(stage.pairing, stage.fingerprint) },
                modifier = Modifier.fillMaxWidth().height(52.dp),
            ) { Text(t("mobile.pair.confirm_yes")) }
            OutlinedButton(onClick = { refused = true }, modifier = Modifier.fillMaxWidth()) {
                Text(t("mobile.pair.confirm_no"))
            }
        }
    }
}

@Composable
private fun Problem(vm: AppViewModel, stage: Stage.Problem) {
    Page(onBack = { vm.back() }) {
        Text(stage.message.text(), style = MaterialTheme.typography.titleMedium, color = LocalColors.current.text)
        if (stage.message.key == "mobile.error.unreachable") Lead(t("mobile.help.unreachable_body"))
        if (stage.message.key == "mobile.error.certificate_changed") Lead(t("mobile.help.certificate_body"))
        val retry = stage.retry
        if (retry != null) {
            Button(onClick = { vm.check(retry) }, modifier = Modifier.fillMaxWidth()) { Text(t("mobile.pair.try_again")) }
        }
        Button(onClick = { vm.go(Stage.Scan) }, modifier = Modifier.fillMaxWidth().height(52.dp)) {
            Text(t("mobile.welcome.scan"))
        }
        TextButton(onClick = { vm.go(Stage.Type()) }, modifier = Modifier.fillMaxWidth()) { Text(t("mobile.welcome.type")) }
    }
}

@Composable
private fun SignIn(vm: AppViewModel, stage: Stage.SignIn) {
    var username by rememberSaveable { mutableStateOf("") }
    var password by rememberSaveable { mutableStateOf("") }
    val submit = { if (username.isNotBlank() && password.isNotEmpty() && !stage.busy) vm.signIn(username, password) }
    Page(t("mobile.signin.title")) {
        Lead(t("mobile.signin.lead"))
        vm.pairing?.let { Note(t("mobile.signin.pc", "host" to it.host), modifier = Modifier.padding(horizontal = 0.dp)) }
        stage.problem?.let { Text(it.text(), color = LocalColors.current.danger) }
        OutlinedTextField(
            value = username,
            onValueChange = { username = it },
            label = { Text(t("login.username")) },
            singleLine = true,
            keyboardOptions = KeyboardOptions(autoCorrectEnabled = false, imeAction = ImeAction.Next),
            modifier = Modifier.fillMaxWidth(),
        )
        OutlinedTextField(
            value = password,
            onValueChange = { password = it },
            label = { Text(t("login.password")) },
            singleLine = true,
            visualTransformation = PasswordVisualTransformation(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Done),
            keyboardActions = KeyboardActions(onDone = { submit() }),
            modifier = Modifier.fillMaxWidth(),
        )
        Button(
            onClick = submit,
            enabled = !stage.busy && username.isNotBlank() && password.isNotEmpty(),
            modifier = Modifier.fillMaxWidth().height(52.dp),
        ) { Text(t(if (stage.busy) "login.signing_in" else "login.sign_in")) }
        Note(t("mobile.signin.stays"), modifier = Modifier.padding(horizontal = 0.dp))
        TextButton(onClick = { vm.forgetPc() }, modifier = Modifier.fillMaxWidth()) {
            Text(t("mobile.settings.forget_pc"))
        }
    }
}

/** Shown over everything until the phone's own unlock succeeds. */
@Composable
fun LockScreen(available: Boolean, onUnlock: () -> Unit) {
    Page {
        Spacer(Modifier.height(48.dp))
        Text(
            t("mobile.lock.title"),
            style = MaterialTheme.typography.headlineSmall,
            color = LocalColors.current.text,
            modifier = Modifier.semantics { heading() },
        )
        if (!available) Lead(t("mobile.lock.unavailable"))
        Button(onClick = onUnlock, modifier = Modifier.fillMaxWidth().height(52.dp)) { Text(t("mobile.lock.unlock")) }
    }
}
