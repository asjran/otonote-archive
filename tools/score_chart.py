"""Compatibility imports for the runtime music-score compiler.

New code must use :mod:`tools.music_score_runtime`.  This module intentionally
contains no independent Combo-generation rules.
"""

from tools.music_score_runtime import (  # noqa: F401
    RuntimeScoreCompileError as ScoreChartError,
    compile_music_score as parse_score_payload,
)
