"""Root conftest: ensure cloned repo directories don't shadow installed packages."""
import sys
from pathlib import Path

_ROOT = Path(__file__).parent

# Cloned repos that share names with their pip packages.
# Insert their python package directories before the project root so that
# the installed (editable) versions take precedence over the bare repo dirs.
_SHADOWED_PACKAGES = {
    "ccxt": _ROOT / "ccxt" / "python",
}

for pkg_name, pkg_path in _SHADOWED_PACKAGES.items():
    pkg_path_str = str(pkg_path)
    if pkg_path_str not in sys.path:
        sys.path.insert(0, pkg_path_str)
    # Remove cached namespace package if already loaded incorrectly
    if pkg_name in sys.modules and sys.modules[pkg_name].__file__ is None:
        del sys.modules[pkg_name]
