"""Load a per-site profile module from sites/<name>/site.py.

Used by pipeline/analyze_selectors.py and pipeline/analyze_untrusted_elements.py
to import the site's clean_html / sanitize / prompt / page-ready definitions.
"""
import importlib.util
import sys
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parent.parent  # src/automatic_boundary_detection/


def load_site(name):
    site_path = REPO_DIR / "sites" / name / "site.py"
    if not site_path.exists():
        raise SystemExit(f"Site module not found: {site_path}")
    spec = importlib.util.spec_from_file_location(f"sites.{name}.site", site_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    # Expose the site directory so callers can find cached HTML / configs.
    module.SITE_DIR = site_path.parent
    module.SITE_NAME = name
    return module


def available_sites():
    return sorted(p.name for p in (REPO_DIR / "sites").iterdir()
                  if (p / "site.py").exists())
