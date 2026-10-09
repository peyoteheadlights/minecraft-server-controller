"""make-update-key.cmd and scripts/make_update_key.py --github: the private key
goes to the GitHub secret through stdin only, the public key into
agent/signing.py, an existing key is never replaced without REPLACE, and the
release scripts name the batch file when the key is missing. gh is faked:
no test touches the network."""

import subprocess
from pathlib import Path

import pytest

from agent import signing
from scripts import make_update_key, release_check, sign_release

ROOT = Path(__file__).resolve().parent.parent
REPO = "owner/repo"


class FakeGh:
    def __init__(self, *, signed_in=True, can_list=True, has_secret=False, set_ok=True):
        self.signed_in = signed_in
        self.can_list = can_list
        self.has_secret = has_secret
        self.set_ok = set_ok
        self.calls: list[tuple[list[str], str | None]] = []

    def __call__(self, args, stdin=None):
        self.calls.append((args, stdin))
        if args[0] == "auth":
            return subprocess.CompletedProcess(args, 0 if self.signed_in else 1, "", "")
        if args[:2] == ["secret", "list"]:
            if not self.can_list:
                return subprocess.CompletedProcess(args, 1, "", "HTTP 404: Not Found")
            listed = (
                f"{make_update_key.GITHUB_NAME}\t2026-10-09T12:00:00Z\n" if self.has_secret else ""
            )
            return subprocess.CompletedProcess(args, 0, "OTHER\t2026-01-01\n" + listed, "")
        if args[:2] == ["secret", "set"]:
            return subprocess.CompletedProcess(args, 0 if self.set_ok else 1, "", "set failed")
        raise AssertionError(f"unexpected gh call {args}")

    def stored(self):
        return [stdin for args, stdin in self.calls if args[:2] == ["secret", "set"]]


@pytest.fixture
def signing_copy(tmp_path):
    copy = tmp_path / "signing.py"
    copy.write_text(Path(signing.__file__).read_text(encoding="utf-8"), encoding="utf-8")
    make_update_key.write_public_key("", copy)
    return copy


def answers(*replies):
    queue = list(replies)
    return lambda _prompt: queue.pop(0) if queue else ""


def has_gh(_name):
    return "gh"


def run(signing_copy, gh, ask=None, which=has_gh):
    return make_update_key.to_github(
        REPO, signing_file=signing_copy, run=gh, which=which, ask=ask or answers("")
    )


def test_saves_the_private_half_on_github_and_the_public_half_in_the_file(
    signing_copy, tmp_path, capsys
):
    gh = FakeGh()
    assert run(signing_copy, gh) == 0
    [private] = gh.stored()
    public = make_update_key.built_in_key(signing_copy)
    assert public and signing.public_key_of(private) == public
    # through stdin only: never on the command line, never in a file
    for args, _stdin in gh.calls:
        assert private not in " ".join(args)
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert private not in path.read_text(encoding="utf-8", errors="ignore")
    out = capsys.readouterr().out
    assert private not in out
    assert "git add agent/signing.py" in out


def test_shows_the_private_key_only_when_asked(signing_copy, capsys):
    gh = FakeGh()
    assert run(signing_copy, gh, ask=answers("y")) == 0
    [private] = gh.stored()
    assert private in capsys.readouterr().out


@pytest.mark.parametrize(
    "which, gh, says",
    [
        (lambda _name: None, FakeGh(), "isn't installed"),
        (has_gh, FakeGh(signed_in=False), "gh auth login"),
        (has_gh, FakeGh(can_list=False), "HTTP 404"),
    ],
)
def test_says_what_to_do_when_gh_cant_save_it(signing_copy, capsys, which, gh, says):
    before = signing_copy.read_text(encoding="utf-8")
    assert run(signing_copy, gh, which=which) == 1
    out = capsys.readouterr().out
    assert says in out and "Nothing was changed" in out
    assert gh.stored() == []
    assert signing_copy.read_text(encoding="utf-8") == before


@pytest.mark.parametrize("built_in, on_github", [(True, False), (False, True), (True, True)])
def test_an_existing_key_is_kept_unless_replace_is_typed(signing_copy, capsys, built_in, on_github):
    if built_in:
        make_update_key.write_public_key(signing.new_key()[1], signing_copy)
    before = signing_copy.read_text(encoding="utf-8")
    gh = FakeGh(has_secret=on_github)
    assert run(signing_copy, gh, ask=answers("yes")) == 1
    assert "Nothing was changed" in capsys.readouterr().out
    assert gh.stored() == []
    assert signing_copy.read_text(encoding="utf-8") == before

    assert run(signing_copy, gh, ask=answers("REPLACE", "")) == 0
    [private] = gh.stored()
    assert signing.public_key_of(private) == make_update_key.built_in_key(signing_copy)


def test_the_file_is_untouched_when_github_refuses_the_secret(signing_copy, capsys):
    before = signing_copy.read_text(encoding="utf-8")
    assert run(signing_copy, FakeGh(set_ok=False)) == 1
    assert "didn't take the secret" in capsys.readouterr().out
    assert signing_copy.read_text(encoding="utf-8") == before


def test_the_batch_file_runs_the_script_with_github():
    text = (ROOT / "make-update-key.cmd").read_text(encoding="utf-8")
    assert r"scripts\make_update_key.py --github" in text
    assert "pause" in text  # a double-clicked window stays open to be read


def test_the_batch_file_installs_only_what_the_key_needs():
    """Not the whole lock: some of it has no build for the newest Python."""
    text = (ROOT / "make-update-key.cmd").read_text(encoding="utf-8")
    assert "--requirements" in text
    assert "--require-hashes" in text and "--only-binary=:all:" in text
    assert "-r requirements.lock" not in text


def test_the_needed_requirements_are_pinned_and_hashed_from_the_lock():
    text = make_update_key.needed_requirements()
    names = {line.split("==")[0] for line in text.splitlines() if not line[0].isspace()}
    assert names == set(make_update_key.NEEDS)
    lock = (ROOT / "requirements.lock").read_text(encoding="utf-8")
    for line in text.splitlines():
        assert line in lock.splitlines()
    assert text.count("--hash=sha256:") >= 3
    assert "# via" not in text


def test_what_signing_imports_is_all_in_the_needed_requirements():
    """If agent/signing.py starts using another library, NEEDS must grow."""
    import ast

    tree = ast.parse(Path(signing.__file__).read_text(encoding="utf-8"))
    imported = {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0
    } | {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    import sys

    outside = {name for name in imported if name not in sys.stdlib_module_names}
    assert outside <= set(make_update_key.NEEDS)


def test_the_repository_is_read_without_importing_the_downloader():
    from agent import downloads

    assert make_update_key.repository() == downloads.REPO


def test_release_check_names_the_batch_file_when_there_is_no_key(monkeypatch):
    from agent import __version__

    monkeypatch.setattr(signing, "UPDATE_PUBLIC_KEY", "")
    found = release_check.problems(f"v{__version__}")
    assert any("make-update-key.cmd" in line for line in found)


def test_signing_names_the_batch_file_when_the_secret_is_missing(monkeypatch, capsys):
    monkeypatch.delenv("MCSC_UPDATE_SIGNING_KEY", raising=False)
    assert sign_release.main(["setup.exe"]) == 1
    assert "make-update-key.cmd" in capsys.readouterr().out
