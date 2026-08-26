"""Small explicit registry for specialization comparison analyzers."""

from __future__ import annotations

from importlib import import_module


SPEC_ANALYZERS = {
    ("Paladin", "Holy"): "spec_plugins.paladin.holy:analyze_comparison",
}


def get_spec_analyzer(class_name: str, spec_name: str):
    target = SPEC_ANALYZERS.get((str(class_name), str(spec_name)))
    if not target:
        from spec_plugins.stub import analyze_comparison

        return analyze_comparison
    module_name, attribute = target.split(":", 1)
    return getattr(import_module(module_name), attribute)
