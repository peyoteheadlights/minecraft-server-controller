import XCTest
@testable import Core

/// What an account may do on each server (agent/security/permissions.py).
final class PerServerTests: XCTestCase {
    private let moderator = try! JSONDecoder().decode(Me.self, from: Data("""
        {"user": "sam", "kind": "session", "role": "helper", "servers": ["survival", "creative"],
         "permissions": ["account.self", "server.view", "server.control", "console.read", "mods.manage", "settings.edit"],
         "account_permissions": ["account.self", "settings.view"],
         "server_permissions": {"survival": ["server.control", "server.view"],
            "creative": ["console.read", "mods.manage", "server.control", "server.view", "settings.game"]},
         "preferences": {}}
        """.utf8))

    func testEachServerHasItsOwnPermissions() {
        let survival = moderator.forServer("survival")
        XCTAssertTrue(survival.can(Permissions.SERVER_CONTROL))
        XCTAssertFalse(survival.can(Permissions.CONSOLE_READ))
        XCTAssertFalse(survival.can(Permissions.MODS_MANAGE))
        XCTAssertTrue(survival.can(Permissions.SETTINGS_VIEW))
        let creative = moderator.forServer("creative")
        XCTAssertTrue(creative.can(Permissions.MODS_MANAGE))
        XCTAssertTrue(creative.can(Permissions.SETTINGS_GAME))
        XCTAssertFalse(creative.can(Permissions.SETTINGS_SERVER))
    }

    func testAServerThatIsntListedAllowsNothingAndIsntSeen() {
        XCTAssertFalse(moderator.forServer("hidden").can(Permissions.SERVER_VIEW))
        XCTAssertFalse(moderator.sees("hidden"))
        XCTAssertTrue(moderator.sees("survival"))
        XCTAssertTrue(moderator.sees(nil))
    }

    func testAnOlderAgentsOneSettingsPermissionCoversAllThree() {
        let old = Me(user: "x", permissions: [Permissions.SETTINGS_EDIT])
        XCTAssertTrue(old.can(Permissions.SETTINGS_GAME))
        XCTAssertTrue(old.can(Permissions.PC_SETTINGS))
        XCTAssertEqual(old, old.forServer("survival"))
        XCTAssertFalse(moderator.forServer("survival").can(Permissions.SETTINGS_SERVER))
    }

    func testAlertsOfAServerTakenAwayGoWithIt() {
        func alert(_ id: Int64, _ server: String?) -> AppAlert {
            AppAlert(id: id, ts: 1, serverId: server, event: "e", title: "t", body: "", page: "p", url: "/")
        }
        let state = AlertState(alerts: [alert(1, "survival"), alert(2, "hidden"), alert(3, nil)])
        XCTAssertEqual(state.onlyFor(moderator).alerts.map { $0.id }, [1, 3])
        let owner = Me(user: "admin", serverPermissions: ["survival": []])
        XCTAssertEqual(state.onlyFor(owner).alerts.count, 3)
    }
}
