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
            } catch {
                let failure = model.client?.translateFailure(error) ?? AgentError.unreachable
                model.note(failure)
                problem = failure.message(model.strings)
            }
            working = false
        }
    }
}

/// An invite opened: the name the owner chose is filled in; the moderator
/// chooses the password, and the phone signs in as them.
struct InviteAccountView: View {
    @Environment(AppModel.self) private var model
    @State private var password = ""
    @State private var repeated = ""
    @State private var checked = false
    @State private var working = false
    @State private var problem: String?
    /// The invite can't be used (used, cancelled, run out): only starting over helps.
    @State private var ended = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text(model.t("mobile.invite.lead"))
                    if let host = model.pairing?.host {
                        Text(model.t("mobile.signin.pc", ["host": host]))
                            .foregroundStyle(.secondary)
                    }
                }
                if let problem = problem {
                    Section {
                        Text(problem).foregroundStyle(.red)
                    }
                }
                if !checked && !ended {
                    Section {
                        ProgressView(model.t("mobile.invite.checking"))
                    }
                } else if !ended {
                    Section {
                        LabeledContent(model.t("mobile.invite.name"), value: model.pendingInvite?.username ?? "")
                        SecureField(model.t("mobile.invite.password"), text: $password)
                            .textContentType(.newPassword)
                            .frame(minHeight: 44)
                        if !password.isEmpty && password.count < Moderators.minPassword {
                            Text(model.t("mobile.invite.too_short")).foregroundStyle(.red)
                        }
                        SecureField(model.t("mobile.invite.repeat"), text: $repeated)
                            .textContentType(.newPassword)
                            .frame(minHeight: 44)
                        if !repeated.isEmpty && repeated != password {
                            Text(model.t("mobile.invite.mismatch")).foregroundStyle(.red)
                        }
                    } footer: {
                        Text(model.t("mobile.invite.hint"))
                    }
                    Section {
                        Button {
                            submit()
                        } label: {
                            Text(model.t(working ? "mobile.invite.going" : "mobile.invite.go"))
                                .fontWeight(.semibold)
                                .frame(maxWidth: .infinity, minHeight: 44)
                        }
                        .disabled(working || password.count < Moderators.minPassword || password != repeated)
                    } footer: {
                        Text(model.t("mobile.signin.stays"))
                    }
                }
                Section {
                    if model.inviteOverSignIn {
                        Button(model.t("mobile.common.cancel")) { model.cancelInvite() }
                            .frame(minHeight: 44)
                    } else {
                        Button(model.t("mobile.pair.start_over"), role: .destructive) {
                            Task { await model.forgetPC() }
                        }
                        .frame(minHeight: 44)
                    }
                }
            }
            .navigationTitle(model.t("mobile.invite.title"))
            .task { await check() }
        }
    }

    /// Asks the PC who the invite is for; a used, cancelled or run-out one says so.
    private func check() async {
        guard let client = model.client, let invite = model.pendingInvite else { return }
        do {
            _ = try await client.checkInvite(token: invite.token)
            checked = true
        } catch {
            let failure = client.translateFailure(error)
            model.note(failure)
            problem = failure.message(model.strings)
            ended = true
        }
    }

    private func submit() {
        guard !working, password.count >= Moderators.minPassword, password == repeated else { return }
        working = true
        problem = nil
        let secret = password
        Task {
            do {
                try await model.acceptInvite(password: secret)
            } catch {
                let failure = model.client?.translateFailure(error) ?? AgentError.unreachable
                model.note(failure)
                problem = failure.message(model.strings)
            }
            working = false
        }
    }
}
