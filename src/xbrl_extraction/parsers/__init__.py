"""
parsers/ — Format-specific parsers for the XBRL filing zip.

Modules:
  ixbrl     — inline XBRL .htm parser (the primary document)
  linkbase  — shared XLink-based linkbase XML parser
  calc      — calculation linkbase (_cal.xml) extractor
  pres      — presentation linkbase (_pre.xml) extractor
  labs      — label linkbase (_lab.xml) extractor
  defs      — definition linkbase (_def.xml) extractor

By convention, files inside this subpackage do NOT carry a `_parser`
suffix — it's redundant given the folder name.
"""
