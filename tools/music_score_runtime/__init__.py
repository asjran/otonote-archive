"""Public boundary for runtime music-score reconstruction."""

from .compiler import (
    ScoreChartError as RuntimeScoreCompileError,
    compile_music_score,
)

__all__ = ["RuntimeScoreCompileError", "compile_music_score"]
