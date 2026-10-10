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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import io.github.peyoteheadlights.mcsc.core.formatFingerprint

/** The screens before the app is paired and signed in. */
@Composable
fun Onboarding(vm: AppViewModel) {
    when (val stage = vm.stage) {
        Stage.Welcome -> Welcome(vm)
        Stage.Scan -> {
            BackHandler { vm.go(Stage.Welcome) }
            ScanScreen(
                onCode = { vm.submit(it, scanned = true) },
                onType = { vm.go(Stage.Type()) },
                onBack = { vm.go(Stage.Welcome) },
            )
        }
        is Stage.Type -> {
            BackHandler { vm.go(Stage.Welcome) }
            TypeAddress(vm, stage)
        }
        Stage.Checking -> Busy(t("mobile.pair.checking"))
        is Stage.Confirm -> {
            BackHandler { vm.go(Stage.Welcome) }
            ConfirmFingerprint(vm, stage)
        }
        is Stage.Problem -> {
            BackHandler { vm.go(Stage.Welcome) }
            Problem(vm, stage)
        }
        is Stage.SignIn -> SignIn(vm, stage)
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
    }
}

@Composable
private fun TypeAddress(vm: AppViewModel, stage: Stage.Type) {
    var text by rememberSaveable { mutableStateOf("") }
    Page(t("mobile.type.title"), onBack = { vm.go(Stage.Welcome) }) {
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
    Page(t("mobile.pair.confirm_title"), onBack = { vm.go(Stage.Welcome) }) {
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
    Page(onBack = { vm.go(Stage.Welcome) }) {
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
