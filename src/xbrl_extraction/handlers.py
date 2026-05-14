"""
handlers.py — Helpers for loading, filtering, and visualizing extracted JSON.

V2 placeholder. The intended public surface:

  load(path) -> Document
      Round-trip a .facts.json back into a Document.

  Document.filter(concept=..., period=..., has_dimensions=..., unit=...)
      Return a subset Document.

  Document.to_dataframe()
      Flatten facts to a pandas DataFrame, denormalising period/unit.

  Document.summary()
      Print counts: facts by namespace, by period, dimensional vs not.

For now this file is intentionally empty — kept as a clear v2 home so
the public package surface stays stable.
"""

from __future__ import annotations

# v2: see module docstring above.
