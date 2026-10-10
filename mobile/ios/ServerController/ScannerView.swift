import AVFoundation
import Core
import SwiftUI
import UIKit
import Vision
import VisionKit

/// The in-app scanner for the dashboard's pairing code. The camera is asked
/// for only when this opens; typing the address is always the other way.
struct ScannerSheet: View {
    private enum Access {
        case checking
        case ready
        case noCamera
        case denied
    }

    let onPairing: (Pairing) -> Void

    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL
    @State private var access: Access = .checking
    @State private var message: String?
    @State private var lastRefused: String?
    @State private var done = false

    var body: some View {
        NavigationStack {
            Group {
                switch access {
                case .checking:
                    ProgressView()
                case .ready:
                    ZStack(alignment: .bottom) {
                        QRScanner { payload in
                            handle(payload)
                        }
                        .ignoresSafeArea(edges: .bottom)
                        Text(message ?? model.t("mobile.scan.hint"))
                            .font(.callout)
                            .multilineTextAlignment(.center)
                            .padding(14)
                            .frame(maxWidth: .infinity)
                            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12))
                            .padding(16)
                            .accessibilityAddTraits(.updatesFrequently)
                    }
                case .noCamera:
                    problem(model.t("mobile.scan.no_camera"), settings: false)
                case .denied:
                    problem(model.t("mobile.scan.camera_denied"), settings: true)
                }
            }
            .navigationTitle(model.t("mobile.scan.title"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(model.t("mobile.common.close")) {
                        dismiss()
                    }
                }
            }
        }
        .task {
            await checkAccess()
        }
    }

    private func problem(_ text: String, settings: Bool) -> some View {
        VStack(spacing: 20) {
            Image(systemName: "camera")
                .font(.system(size: 44))
                .foregroundStyle(.secondary)
                .accessibilityHidden(true)
            Text(text)
                .multilineTextAlignment(.center)
            if settings {
                Button {
                    if let url = URL(string: UIApplication.openSettingsURLString) {
                        openURL(url)
                    }
                } label: {
                    Text(model.t("mobile.scan.open_settings"))
                        .frame(minHeight: 44)
                }
                .buttonStyle(.borderedProminent)
            }
        }
        .padding(24)
    }

    private func checkAccess() async {
        guard DataScannerViewController.isSupported else {
            access = .noCamera
            return
        }
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized:
            access = DataScannerViewController.isAvailable ? .ready : .denied
        case .notDetermined:
            let granted = await AVCaptureDevice.requestAccess(for: .video)
            access = granted && DataScannerViewController.isAvailable ? .ready : .denied
        case .denied, .restricted:
            access = .denied
        @unknown default:
            access = .denied
        }
    }

    /// Only a pairing link from the dashboard is taken; anything else is
    /// named once and scanning carries on.
    private func handle(_ payload: String) {
        guard !done else { return }
        do {
            let pairing = try PairingLink.parse(payload)
            guard pairing.fingerprint != nil else {
                refuse(payload, model.t("mobile.scan.not_ours"))
                return
            }
            done = true
            onPairing(pairing)
        } catch let error as PairingParseError {
            if error.problem == .badFingerprint {
                refuse(payload, model.t("mobile.pair.error_bad_code"))
            } else {
                refuse(payload, model.t("mobile.scan.not_ours"))
            }
        } catch {
            refuse(payload, model.t("mobile.scan.not_ours"))
        }
    }

    private func refuse(_ payload: String, _ words: String) {
        if lastRefused == payload { return }
        lastRefused = payload
        message = words
        UIAccessibility.post(notification: .announcement, argument: words)
    }
}

/// Apple's live-camera code reader (VisionKit), for QR codes only.
struct QRScanner: UIViewControllerRepresentable {
    let onPayload: (String) -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(onPayload: onPayload)
    }

    func makeUIViewController(context: Context) -> DataScannerViewController {
        let scanner = DataScannerViewController(
            recognizedDataTypes: [.barcode(symbologies: [.qr])],
            qualityLevel: .balanced,
            recognizesMultipleItems: false,
            isHighFrameRateTrackingEnabled: false,
            isPinchToZoomEnabled: true,
            isGuidanceEnabled: true,
            isHighlightingEnabled: true
        )
        scanner.delegate = context.coordinator
        return scanner
    }

    func updateUIViewController(_ scanner: DataScannerViewController, context: Context) {
        context.coordinator.onPayload = onPayload
        if !scanner.isScanning {
            try? scanner.startScanning()
        }
    }

    static func dismantleUIViewController(_ scanner: DataScannerViewController, coordinator: Coordinator) {
        scanner.stopScanning()
    }

    @MainActor
    final class Coordinator: NSObject, DataScannerViewControllerDelegate {
        var onPayload: (String) -> Void

        init(onPayload: @escaping (String) -> Void) {
            self.onPayload = onPayload
        }

        func dataScanner(_ dataScanner: DataScannerViewController, didAdd addedItems: [RecognizedItem], allItems: [RecognizedItem]) {
            for item in addedItems {
                if case .barcode(let code) = item, let text = code.payloadStringValue {
                    onPayload(text)
                    return
                }
            }
        }

        func dataScanner(_ dataScanner: DataScannerViewController, didTapOn item: RecognizedItem) {
            if case .barcode(let code) = item, let text = code.payloadStringValue {
                onPayload(text)
            }
        }
    }
}
