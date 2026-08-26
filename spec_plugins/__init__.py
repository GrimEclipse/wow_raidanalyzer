"""Per-specialization comparison plugins.

Boss plugins answer encounter-mechanic questions.  Spec plugins answer rotation,
buff, resource, and burst-window questions for one player in one Fight.
"""

from spec_plugins.registry import get_spec_analyzer

__all__ = ["get_spec_analyzer"]
