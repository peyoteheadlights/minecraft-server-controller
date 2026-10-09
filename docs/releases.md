# Making a release

A release is a tag like `v1.2.0`. Pushing it runs
`.github/workflows/release.yml`, which builds the setup file on Windows,
signs the update file, records where the files were built, and publishes a
GitHub release. The app's in-app updater installs only from these
releases, and only what this key signed.

## Once: the update-signing key

The app checks every update it installs against an Ed25519 public key built
into it (`agent/signing.py`). The private half signs each release. Make the
pair once, on your own PC, before the first release:

```powershell
python scripts/make_update_key.py
```

It prints the private key once and writes nothing private to disk. Save it
in two places:

1. **GitHub**: the repository's Settings > Secrets and variables > Actions >
   New repository secret. Name `MCSC_UPDATE_SIGNING_KEY`, value the printed
   line. Only the release workflow reads it.
2. **Offline**, somewhere only you can open (a password manager). If GitHub
   ever loses the secret, this is the only copy; without it, installed
   copies can't update themselves until the new version is installed by
   hand.

3. **Optional, recommended**: Settings > Environments > `release` (the
   first release run makes it) > Deployment branches and tags > Selected,
   add the tag rule `v*`. Then only a version tag's run can use the key.
   You can also move the secret there (Environment secrets) and delete the
   repository one.

Then commit the change it made to `agent/signing.py` (the public key). A
copy built without a public key never installs updates by itself, and the
release workflow refuses to run.

Never paste the private key into an issue, a chat, a commit or a log.

**If it leaks or is lost**: `python scripts/make_update_key.py --replace`,
replace the GitHub secret, release, and tell people to install that release
by hand once ([security](security.md#the-signing-key)).

## Every release

1. **Version.** Set `__version__` in `agent/__init__.py`. Bump the middle
   number for new features, the last for fixes.
2. **API version.** If a change means a client (the dashboard or the phone
   app) must behave differently, bump `API_VERSION` in `agent/__init__.py`.
   Adding routes or fields doesn't need it.
3. **CHANGELOG.md.** Add a `## <version>` section in plain words, with
   anything clients must know under `### API`. It becomes the release page
   and the dashboard's "What's new".
4. **Save the API.** `python scripts/api_contract.py save`. It writes
   `docs/api/openapi-<version>.json` and points `docs/api/released.txt` at
   it. From then on, `tests/test_api_contract.py` fails if a later change
   removes a route or a field without deprecating it first.
5. **Commit, merge to main, then tag**:

   ```powershell
   git tag v1.2.0
   git push origin v1.2.0
   ```

The workflow then:

- refuses if the tag isn't `v` + the version, if CHANGELOG.md has no
  section for it, if the saved API copy isn't this code's API, or if no
  public key is built in (`scripts/release_check.py`);
- runs the tests on the Python in `.python-version`, which is the Python
  the setup file packs;
- builds `MinecraftServerController-Setup-<version>.exe` and its `.sha256`;
- attests the setup file with GitHub's artifact attestations
  (`gh attestation verify <file> --repo <repo>` checks it);
- signs `update.json` (version, file name, size, SHA-256) into
  `update.json.sig` with the secret, in a job of its own that installs only
  the app's own hash-locked libraries, so none of the build and test tools
  ever run next to the key; it refuses if the secret's public half isn't
  the one built in;
- publishes the release with those four files and the notes. Only this
  last job can write to the repository.

Every action in the workflows is pinned to a full commit SHA, with its
version in a comment. To update one, look up the new tag's commit
(`git ls-remote https://github.com/actions/checkout refs/tags/v4.4.0`) and
change the SHA and the comment together.

## Code signing

The setup file isn't Authenticode-signed yet, so SmartScreen warns
"Unknown publisher". [Installation](installation.md#code-signing-the-way-to-remove-the-warning-not-set-up-yet)
has the options, prices and steps; nothing is set up until you choose.
