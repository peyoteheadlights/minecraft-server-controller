import Core
import SwiftUI

/// Servers, Notifications and Settings.
struct MainTabView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        @Bindable var model = model
        TabView(selection: $model.tab) {
            ServersListView()
                .tabItem {
                    Label(model.t("mobile.tab.servers"), systemImage: "server.rack")
                }
                .tag(AppTab.servers)
            NotificationsView()
                .tabItem {
                    Label(model.t("mobile.tab.notifications"), systemImage: "bell")
                }
                .badge(model.alertState.unread)
                .tag(AppTab.notifications)
            SettingsView()
                .tabItem {
                    Label(model.t("mobile.tab.settings"), systemImage: "gearshape")
                }
                .tag(AppTab.settings)
        }
        .task(id: model.locked) {
            if !model.locked {
                await model.afterSignIn()
            }
        }
    }
}
