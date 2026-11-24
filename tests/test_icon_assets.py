"""Static deployment checks; no database or internet required."""
import re
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / 'static/vendor/fontawesome'

def test_all_icon_classes_have_local_css():
    css = (VENDOR / 'css/all.min.css').read_text()
    sources = list((ROOT/'templates').glob('*.html')) + list((ROOT/'static/js').glob('*.js'))
    classes = {name for path in sources for name in re.findall(r'\bfa-[a-z][a-z0-9-]+', path.read_text())}
    assert not {name for name in classes if '.' + name not in css}
    for path in sources:
        if path.suffix == '.html' and re.search(r'\bfa-solid\b', path.read_text()):
            assert 'vendor/fontawesome/css/all.min.css' in path.read_text(), path

def test_local_font_and_svg_paths():
    for path in [VENDOR/'css/all.min.css', ROOT/'static/css/icon_fallback.css']:
        for url in re.findall(r'url\(["\']?([^\)"\']+)', path.read_text()):
            assert (path.parent/url).is_file(), url

def test_font_csp_is_explicit_and_restricted():
    policy = (ROOT/'utils/runtime_guard.py').read_text()
    assert "font-src 'self' https://fonts.gstatic.com;" in policy
