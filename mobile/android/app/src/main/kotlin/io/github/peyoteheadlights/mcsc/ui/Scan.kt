package io.github.peyoteheadlights.mcsc.ui

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.annotation.OptIn
import androidx.camera.core.CameraSelector
import androidx.camera.core.ExperimentalGetImage
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.google.mlkit.vision.barcode.BarcodeScannerOptions
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.common.InputImage
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

/**
 * The pairing code, read by the app's own camera view (CameraX, with the
 * barcode model inside the app, so nothing is sent anywhere). The camera
 * permission is asked here, the first time it is needed.
 */
@Composable
fun ScanScreen(onCode: (String) -> Unit, onType: () -> Unit, onBack: () -> Unit) {
    val context = LocalContext.current
    val hasCamera = remember { context.packageManager.hasSystemFeature(PackageManager.FEATURE_CAMERA_ANY) }
    var allowed by remember {
        mutableStateOf(ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED)
    }
    var asked by remember { mutableStateOf(false) }
    val ask = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
        allowed = it
        asked = true
    }
    LaunchedEffect(hasCamera) {
        if (hasCamera && !allowed) ask.launch(Manifest.permission.CAMERA)
    }
    Scaffold(containerColor = LocalColors.current.sheet, topBar = { Bar(t("mobile.scan.title"), onBack) }) { padding ->
        Column(Modifier.padding(padding).fillMaxSize()) {
            when {
                !hasCamera -> Note(t("mobile.scan.no_camera"))
                allowed -> {
                    Box(Modifier.weight(1f).fillMaxWidth()) {
                        CameraPreview(onCode)
                    }
                    Note(t("mobile.scan.hint"))
                }
                asked -> {
                    Note(t("mobile.scan.camera_denied"))
                    Button(
                        onClick = {
                            context.startActivity(
                                Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", context.packageName, null)),
                            )
                        },
                        modifier = Modifier.padding(horizontal = 20.dp),
                    ) { Text(t("mobile.scan.open_settings")) }
                }
            }
            TextButton(
                onClick = onType,
                modifier = Modifier.fillMaxWidth().padding(16.dp).align(Alignment.CenterHorizontally),
            ) { Text(t("mobile.welcome.type")) }
        }
    }
}

@Composable
private fun CameraPreview(onCode: (String) -> Unit) {
    val context = LocalContext.current
    val owner = LocalLifecycleOwner.current
    val latest by rememberUpdatedState(onCode)
    val done = remember { AtomicBoolean(false) }
    val executor = remember { Executors.newSingleThreadExecutor() }
    val scanner = remember {
        BarcodeScanning.getClient(BarcodeScannerOptions.Builder().setBarcodeFormats(Barcode.FORMAT_QR_CODE).build())
    }
    val providerFuture = remember { ProcessCameraProvider.getInstance(context) }
    DisposableEffect(Unit) {
        onDispose {
            if (providerFuture.isDone) providerFuture.get().unbindAll()
            scanner.close()
            executor.shutdown()
        }
    }
    AndroidView(
        modifier = Modifier.fillMaxSize(),
        factory = { ctx ->
            val view = PreviewView(ctx)
            providerFuture.addListener({
                val provider = providerFuture.get()
                val preview = Preview.Builder().build()
                preview.setSurfaceProvider(view.surfaceProvider)
                val analysis = ImageAnalysis.Builder()
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .build()
                analysis.setAnalyzer(executor) { image ->
                    read(scanner, image) { text ->
                        if (done.compareAndSet(false, true)) {
                            ContextCompat.getMainExecutor(ctx).execute { latest(text) }
                        }
                    }
                }
                provider.unbindAll()
                provider.bindToLifecycle(owner, CameraSelector.DEFAULT_BACK_CAMERA, preview, analysis)
            }, ContextCompat.getMainExecutor(ctx))
            view
        },
    )
}

@OptIn(ExperimentalGetImage::class)
private fun read(scanner: com.google.mlkit.vision.barcode.BarcodeScanner, image: ImageProxy, found: (String) -> Unit) {
    val media = image.image
    if (media == null) {
        image.close()
        return
    }
    scanner.process(InputImage.fromMediaImage(media, image.imageInfo.rotationDegrees))
        .addOnSuccessListener { codes -> codes.firstNotNullOfOrNull { it.rawValue }?.let(found) }
        .addOnCompleteListener { image.close() }
}
