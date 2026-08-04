"""Compatibility package for pipeline tools retained at the component root.

The original production tests import modules as ``tools.<module>``. Public
BacklotOS archives keep the executable modules one directory above this
package, so extend the package search path instead of duplicating them.
"""

from pathlib import Path

_component_root = str(Path(__file__).resolve().parents[1])
if _component_root not in __path__:
    __path__.append(_component_root)
