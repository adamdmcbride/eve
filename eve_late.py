"""Late-binding proxy for the ``eve`` facade (program task 0.3).

Modules extracted out of ``eve.py`` must not ``import eve`` at module load:
``eve.py`` imports them, so the import would be circular, and a module-level
``from eve import name`` would freeze one binding and silently escape every
``patch.object(eve, name)`` in the test-suite. Instead they write::

    from eve_late import core

    def something():
        return core.utc_now()

``core.<name>`` resolves ``getattr(sys.modules["eve"], name)`` at call time,
importing ``eve`` lazily when it is not loaded yet, so the binding that is
current on the facade at the moment of the call is the one used.

Python 3.9 compatible; stdlib only; importing this module never imports ``eve``.
"""
import importlib
import sys

FACADE_MODULE = "eve"

__all__ = ["core", "facade_module", "FACADE_MODULE"]


def facade_module():
    """Return the live ``eve`` module, importing it if it is not loaded."""
    module = sys.modules.get(FACADE_MODULE)
    if module is None:
        module = importlib.import_module(FACADE_MODULE)
    return module


class _LateCore(object):
    """Attribute access proxy onto the ``eve`` module, resolved per access."""

    __slots__ = ()

    def __getattr__(self, name):
        if name.startswith("__") and name.endswith("__"):
            # Never forward dunder probes (copy, pickle, inspect, mock): they
            # would trigger an import of eve as a side effect of introspection.
            raise AttributeError(name)
        try:
            return getattr(facade_module(), name)
        except AttributeError:
            raise AttributeError("eve facade has no attribute %r" % (name,))

    def __dir__(self):
        module = sys.modules.get(FACADE_MODULE)
        return sorted(dir(module)) if module is not None else []

    def __repr__(self):
        loaded = FACADE_MODULE in sys.modules
        return "<eve_late.core -> %s (%s)>" % (FACADE_MODULE, "loaded" if loaded else "not loaded")


core = _LateCore()
