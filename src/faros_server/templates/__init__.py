"""HTML template loading for server-rendered pages."""

from __future__ import annotations

from pathlib import Path
from string import Template

_TEMPLATE_DIR = Path(__file__).parent


def load_template(name: str) -> Template:
    """Read a template file and return a string.Template for safe substitution.

    Uses $variable syntax (string.Template) so JS curly braces are not
    misinterpreted as format placeholders.

    Args:
        name: Filename relative to the templates directory (e.g. "approval.html").

    Raises:
        FileNotFoundError: If the template does not exist.
    """
    return Template((_TEMPLATE_DIR / name).read_text())
