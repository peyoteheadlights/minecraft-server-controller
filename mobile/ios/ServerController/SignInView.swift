import Core
import SwiftUI

/// The dashboard's own username and password. The sign-in is kept on the
/// phone (in the Keychain), behind the app's unlock.
struct SignInView: View {
    private enum Field {
        case username
        case password
    }

    @Environment(AppModel.self) private var model
    @State private var username = ""
    @State private var password = ""
    @State private var working = false
    @State private var problem: String?
    @State private var confirmForget = false
    @FocusState private var focus: Field?

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text(model.t("mobile.signin.lead"))
                    if let host = model.pairing?.host {
                        Text(model.t("mobile.signin.pc", ["host": host]))
                            .foregroundStyle(.secondary)
                    }
                    if let notice = model.signInNotice {
                        Text(notice)
                            .foregroundStyle(.orange)
                    }
                }
                Section {
                    TextField(model.t("login.username"), text: $username)
                        .textContentType(.username)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled(true)
                        .focused($focus, equals: .username)
                        .submitLabel(.next)
                        .onSubmit { focus = .password }
                        .frame(minHeight: 44)
                    SecureField(model.t("login.password"), text: $password)
                        .textContentType(.password)
                        .focused($focus, equals: .password)
                        .submitLabel(.go)
                        .onSubmit { submit() }
                        .frame(minHeight: 44)
                } footer: {
                    Text(model.t("mobile.signin.stays"))
                }
                if let problem = problem {
                    Section {
                        Text(problem)
                            .foregroundStyle(.red)
                    }
                }
                Section {
                    Button {
                        submit()
                    } label: {
                        HStack {
                            Spacer()
                            Text(working ? model.t("login.signing_in") : model.t("login.sign_in"))
                                .fontWeight(.semibold)
                            Spacer()
                        }
                        .frame(minHeight: 44)
                    }
                    .disabled(working || username.isEmpty || password.isEmpty)
                }
                Section {
                    Button(model.t("mobile.pair.start_over"), role: .destructive) {
                        confirmForget = true
                    }
                    .frame(minHeight: 44)
                }
            }
            .navigationTitle(model.t("mobile.signin.title"))
            .alert(model.t("mobile.settings.forget_pc_title"), isPresented: $confirmForget) {
                Button(model.t("mobile.settings.forget_pc"), role: .destructive) {
                    Task { await model.forgetPC() }
                }
                Button(model.t("mobile.common.cancel"), role: .cancel) {}
            } message: {
                Text(model.t("mobile.settings.forget_pc_body"))
            }
        }
    }

    private func submit() {
        guard !working, !username.isEmpty, !password.isEmpty else { return }
        working = true
        problem = nil
        let name = username
        let secret = password
        Task {
            do {
                try await model.signIn(username: name, password: secret)
                password = ""
            } catch let error as AgentError {
                problem = error.message(model.strings)
            } catch {
                problem = AgentError.unreachable.message(model.strings)
            }
            working = false
        }
    }
}
