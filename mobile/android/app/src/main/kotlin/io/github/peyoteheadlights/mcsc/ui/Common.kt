package io.github.peyoteheadlights.mcsc.ui

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.browser.customtabs.CustomTabsIntent
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.automirrored.filled.OpenInNew
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableDoubleStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import io.github.peyoteheadlights.mcsc.core.Display
import io.github.peyoteheadlights.mcsc.core.ServerColors
import kotlinx.coroutines.delay

/** Other companies' sites and the GitHub forms open in the phone's browser
 * inside the app (Custom Tabs). Nothing of the app's sign-in goes with them. */
fun openLink(context: Context, url: String) {
    try {
        CustomTabsIntent.Builder().setShowTitle(true).build().launchUrl(context, Uri.parse(url))
    } catch (e: ActivityNotFoundException) {
        try {
            context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        } catch (ignored: ActivityNotFoundException) {
            // No browser at all: nothing to open it with.
        }
    }
}

object Links {
    const val REPO = "https://github.com/peyoteheadlights/minecraft-server-controller"
    const val RELEASES = "$REPO/releases"
    const val PRIVACY = "$REPO/blob/main/PRIVACY.md"
    const val REPORT = "$REPO/issues/new?template=bug_report.yml"
    const val SUGGEST = "$REPO/issues/new?template=feature_request.yml"
    const val TAILSCALE_ANDROID = "https://play.google.com/store/apps/details?id=com.tailscale.ipn"
}

/** Seconds since 1970, ticking every [every] ms, for "Checked 2m ago". */
@Composable
fun rememberNow(every: Long = 15_000): Double {
    var value by remember { mutableDoubleStateOf(now()) }
    LaunchedEffect(every) {
        while (true) {
            delay(every)
            value = now()
        }
    }
    return value
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun Bar(title: String, onBack: (() -> Unit)? = null, actions: @Composable () -> Unit = {}) {
    val colors = LocalColors.current
    TopAppBar(
        title = { Text(title, modifier = Modifier.semantics { heading() }) },
        navigationIcon = {
            if (onBack != null) {
                IconButton(onClick = onBack) {
                    Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = t("mobile.common.close"))
                }
            }
        },
        actions = { actions() },
        colors = TopAppBarDefaults.topAppBarColors(
            containerColor = colors.sheet,
            titleContentColor = colors.text,
            navigationIconContentColor = colors.text,
            actionIconContentColor = colors.text,
        ),
    )
}

@Composable
fun SectionTitle(text: String) {
    Text(
        text,
        style = MaterialTheme.typography.titleSmall,
        color = LocalColors.current.text2,
        modifier = Modifier.padding(start = 20.dp, end = 20.dp, top = 20.dp, bottom = 6.dp).semantics { heading() },
    )
}

/** A rounded card of rows, like the dashboard's cards. */
@Composable
fun Card(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    Surface(
        color = LocalColors.current.surface,
        shape = RoundedCornerShape(14.dp),
        modifier = modifier.fillMaxWidth().padding(horizontal = 16.dp),
    ) {
        Column(content = content)
    }
}

@Composable
fun Item(
    title: String,
    subtitle: String? = null,
    onClick: (() -> Unit)? = null,
    external: Boolean = false,
    leading: (@Composable () -> Unit)? = null,
    trailing: (@Composable () -> Unit)? = null,
) {
    val colors = LocalColors.current
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(min = 56.dp)
            .let { if (onClick != null) it.clickable(role = Role.Button, onClick = onClick) else it }
            .padding(horizontal = 16.dp, vertical = 10.dp),
    ) {
        if (leading != null) {
            leading()
            Spacer(Modifier.width(12.dp))
        }
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.bodyLarge, color = colors.text)
            if (subtitle != null) {
                Text(subtitle, style = MaterialTheme.typography.bodyMedium, color = colors.text2)
            }
        }
        when {
            trailing != null -> trailing()
            external -> Icon(Icons.AutoMirrored.Filled.OpenInNew, contentDescription = null, tint = colors.text3)
            onClick != null -> Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, contentDescription = null, tint = colors.text3)
        }
    }
}

@Composable
fun Note(text: String, color: Color = LocalColors.current.text2, modifier: Modifier = Modifier) {
    Text(
        text,
        style = MaterialTheme.typography.bodyMedium,
        color = color,
        modifier = modifier.padding(horizontal = 20.dp, vertical = 6.dp),
    )
}

/** A problem said plainly, with what to do about it. */
@Composable
fun ProblemNote(message: Message, onRetry: (() -> Unit)? = null) {
    val colors = LocalColors.current
    Card(Modifier.padding(vertical = 8.dp)) {
        Text(
            message.text(),
            color = colors.danger,
            style = MaterialTheme.typography.bodyLarge,
            modifier = Modifier.padding(16.dp),
        )
        if (onRetry != null) {
            TextButton(onClick = onRetry, modifier = Modifier.padding(start = 6.dp, bottom = 6.dp)) {
                Text(t("mobile.common.retry"))
            }
        }
    }
}

/** A server's color as a dot, with a fill and edge that read in every theme. */
@Composable
fun ServerDot(color: String?) {
    val badge = ServerColors.badge(color)
    Box(
        Modifier
            .size(14.dp)
            .background(hexColor(badge?.first) ?: LocalColors.current.neutral, CircleShape),
    )
}

@Composable
fun StateText(state: String?) {
    val words = Display.state(state)
    Text(
        t(words.key),
        color = LocalColors.current.tone(words.tone),
        style = MaterialTheme.typography.bodyMedium,
        fontWeight = FontWeight.Medium,
    )
}

@Composable
fun Confirm(
    title: String,
    body: String,
    confirm: String,
    danger: Boolean,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    val colors = LocalColors.current
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = { Text(body) },
        confirmButton = {
            TextButton(
                onClick = onConfirm,
                colors = ButtonDefaults.textButtonColors(contentColor = if (danger) colors.danger else colors.accentInk),
            ) { Text(confirm) }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text(t("mobile.common.cancel")) } },
        containerColor = colors.float,
        titleContentColor = colors.text,
        textContentColor = colors.text2,
    )
}

val ScreenPadding = PaddingValues(bottom = 24.dp)
val Gap = Arrangement.spacedBy(8.dp)
