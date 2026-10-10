// swift-tools-version:5.9
import PackageDescription

// The iPhone app's platform-free logic: pairing, the certificate check, the
// agent's API, wording, colors and alerts. It mirrors mobile/android/core
// rule for rule and is tested on macOS with `swift test`.
let package = Package(
    name: "Core",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [
        .library(name: "Core", targets: ["Core"]),
    ],
    targets: [
        .target(name: "Core", path: "Sources/Core"),
        .testTarget(name: "CoreTests", dependencies: ["Core"], path: "Tests/CoreTests"),
    ]
)
