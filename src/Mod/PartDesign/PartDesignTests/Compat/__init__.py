# SPDX-License-Identifier: LGPL-2.1-or-later

"""The CI reopen gate (FreeCAD-CH, ops#323, notes/beta-compatibility.md 3): purpose-built models
saved once per generation (`gen<k>/`), reopened on every PR. `models` builds them,
`make_generation` saves a generation, `TestCompatCorpus` is the gate. The record and the
comparison are Part's `CompatRecord`."""
