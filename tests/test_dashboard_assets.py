"""The dashboard is plain ES modules with no build step and no inline styles."""

import re
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "agent" / "web"


def modules():
    return sorted((WEB / "js").rglob("*.js"))


def test_index_loads_one_module_entry_point():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    scripts = re.findall(r"<script[^>]*>", html)
    assert '<script type="module" src="/assets/js/main.js">' in scripts
    assert all("type=\"module\"" in s or "theme.js" in s for s in scripts)


def test_every_import_points_at_a_real_file():
    for module in modules():
        for target in re.findall(r'^import .*?"(\.[^"]+)";', module.read_text(encoding="utf-8"), re.M):
            assert (module.parent / target).resolve().is_file(), f"{module.name} imports {target}"


def test_no_inline_style_attributes():
    """The CSP has no 'unsafe-inline' for styles, so a style attribute would
    be silently ignored by the browser. Use a class, or a style object
    (applied through the CSSOM) for computed values."""
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert "style=" not in html
    assert "<style" not in html
    for module in modules():
        source = module.read_text(encoding="utf-8")
        assert not re.search(r"style:\s*[\"'`]", source), module.name
        assert 'setAttribute("style"' not in source, module.name
        assert ".cssText" not in source, module.name


def test_dashboard_does_not_use_window_globals_between_modules():
    for module in modules():
        assert "window.MCSC" not in module.read_text(encoding="utf-8"), module.name
