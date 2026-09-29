#!/usr/bin/env python3
"""Build a publishable, release-bound scoring evidence manifest.

The manifest records what the local Master tables and IL2CPP method structures
prove. It intentionally omits native addresses and never infers a score formula.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


SCORING_RULE_SET_ID = "scoring-research-v1"
SCORING_TYPES = (
    "App.LiveLogic.Score.LiveScoreCalculator",
    "App.LiveLogic.Score.LiveScoreController",
    "App.UI.BattleLiveLog.PlayerFormationPowerCalculator",
    "App.AutoEditFormation.DeckAutoBuilder",
)

MECHANISM_METHODS = {
    "note_score_core": {"CalcNoteScore", "CalcNoteScoreCore", "CalcNoteScoreWithoutFactor"},
    "factor_commands": {"AddFactorCommand", "ApplyFactorCommand"},
    "fixed_score_commands": {"AddFixedScoreCommand", "AddFixedScore"},
    "combo_bonus": {"AddComboBonus", "GetComboBonusFactor"},
    "judgement_factor": {"GetJudgementScoreUpFactor", "AddJudgementNoteScoreUpFactor"},
    "gekisou_combo": {"GetGekisouComboBonusFactor"},
    "owner_contributions": {"GetOwnerContributions", "CalculateAllOwnerContributions"},
    "leader_power_bonus": {"CalculateLeaderSkillBonuses"},
    "auto_deck_constraints": {"BuildDeck", "SelectBestMemberSet", "FilterBySkillCondition"},
}

STATIC_METHOD_AUDITS = {
    ("App.LiveLogic.Score.LiveScoreCalculator", "CalcNoteScoreCore", 0x060000B1): {
        "knownMechanisms": [
            "percentage_divisor_100",
            "two_stage_floor_rounding",
        ],
        "observations": {
            "percentageDivisor": 100.0,
            "floorStageCount": 2,
            "roundingInstruction": "FRINTM/FCVTMS",
            "arithmeticPrecision": "float32",
            "multiplicationOrderVisible": True,
        },
        "limitations": [
            "caller-resolved factors and score-level constant are not fully verified",
            "callers and mode-specific branches are not fully audited",
        ],
    },
}

UNKNOWN_MECHANISMS = (
    "note_score_parameter_semantics",
    "rounding_outside_audited_note_score_core",
    "command_application_order",
    "skill_trigger_and_stack_semantics",
    "leader_target_and_slot_semantics",
    "official_slot_and_duplicate_constraints",
    "mode_specific_score_modifiers",
    "reconciled_official_replay_samples",
)


class ScoringEvidenceError(ValueError):
    """Raised when the evidence inputs are malformed."""


def _load_rows(root: Path, name: str) -> list[dict[str, Any]]:
    path = root / f"{name}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ScoringEvidenceError(f"missing Master table: {path}") from error
    except json.JSONDecodeError as error:
        raise ScoringEvidenceError(f"invalid JSON in {path}: {error}") from error
    rows = payload.get("_allData") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ScoringEvidenceError(f"{name} must contain an _allData array")
    return rows


def _combo_bonus_evidence(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[int(row.get("_comboBonusType") or 0)].append(row)
    return {
        "sourceTable": "MasterLiveComboScoreBonus",
        "rowCount": len(rows),
        "types": [
            {
                "typeCode": type_code,
                "rowCount": len(group),
                "requiredComboMin": min(
                    (int(row.get("_requiredComboCount") or 0) for row in group),
                    default=0,
                ),
                "requiredComboMax": max(
                    (int(row.get("_requiredComboCount") or 0) for row in group),
                    default=0,
                ),
                "factors": sorted(
                    {float(row.get("_bonusFactor") or 0) for row in group}
                ),
            }
            for type_code, group in sorted(groups.items())
        ],
        "interpretationStatus": "identified_values_unverified_application",
    }


def _score_rank_evidence(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups = {int(row.get("_group") or 0) for row in rows}
    ranks = sorted({int(row.get("_liveScoreRank") or 0) for row in rows})
    return {
        "sourceTable": "MasterLiveScoreRank",
        "rowCount": len(rows),
        "groupCount": len(groups),
        "rankCodes": ranks,
        "interpretationStatus": "threshold_archive_only",
    }


def _skill_effect_evidence(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(str(int(row.get("_skillEffectType") or 0)) for row in rows)
    return {
        "sourceTable": "MasterLiveSkillEffect",
        "rowCount": len(rows),
        "effectTypeCounts": dict(sorted(counts.items(), key=lambda item: int(item[0]))),
        "interpretationStatus": "effect_values_available_trigger_semantics_partial",
    }


def _native_evidence(methods: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    assemblies: dict[str, str] = {}
    for method in methods:
        type_name = str(method.get("typeName") or "")
        if type_name not in SCORING_TYPES:
            continue
        name = str(method.get("methodName") or "")
        if not name:
            continue
        assemblies[type_name] = str(method.get("assembly") or "")
        grouped[type_name].append(
            {
                "methodName": name,
                "parameterCount": int(method.get("parameterCount") or 0),
                "token": f"0x{int(method.get('token') or 0):08x}",
            }
        )
    return [
        {
            "typeName": type_name,
            "assembly": assemblies.get(type_name, ""),
            "methodCount": len(grouped.get(type_name, [])),
            "methods": sorted(
                grouped.get(type_name, []),
                key=lambda method: (method["token"], method["methodName"]),
            ),
            "interpretationStatus": (
                "method_structure_available" if grouped.get(type_name) else "missing"
            ),
        }
        for type_name in SCORING_TYPES
    ]


def _static_analysis(methods: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    matched = []
    for method in methods:
        key = (
            str(method.get("typeName") or ""),
            str(method.get("methodName") or ""),
            int(method.get("token") or 0),
        )
        audit = STATIC_METHOD_AUDITS.get(key)
        if not audit:
            continue
        matched.append(
            {
                "typeName": key[0],
                "methodName": key[1],
                "token": f"0x{key[2]:08x}",
                "status": "partial_token_matched_disassembly_audit",
                "observations": dict(audit["observations"]),
                "limitations": list(audit["limitations"]),
            }
        )
    return sorted(matched, key=lambda entry: (entry["typeName"], entry["token"]))


def build_scoring_evidence(
    master_root: Path,
    client_methods: Iterable[Mapping[str, Any]],
    release_id: str,
    replay_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return deterministic evidence without claiming an unverified formula."""

    methods = list(client_methods)
    method_names = {str(method.get("methodName") or "") for method in methods}
    static_analysis = _static_analysis(methods)
    static_mechanisms = {
        mechanism
        for method in methods
        for key, audit in STATIC_METHOD_AUDITS.items()
        if (
            str(method.get("typeName") or ""),
            str(method.get("methodName") or ""),
            int(method.get("token") or 0),
        ) == key
        for mechanism in audit["knownMechanisms"]
    }
    known_mechanisms = sorted(
        static_mechanisms.union(
        mechanism
        for mechanism, required_names in MECHANISM_METHODS.items()
        if method_names.intersection(required_names)
        )
    )
    replay_summary = replay_summary or {
        "sampleCount": 0,
        "statusCounts": {
            "fixture": 0,
            "observed": 0,
            "reconciled": 0,
            "rejected": 0,
        },
        "formalCapability": "external_gate",
        "gate": "client_replay_sample_missing",
    }
    replay_counts = replay_summary.get("statusCounts", {})
    reconciled_count = int(replay_counts.get("reconciled", 0))
    sample_count = int(replay_summary.get("sampleCount", 0))
    return {
        "schemaVersion": 1,
        "sourceReleaseId": release_id,
        "ruleSet": {
            "id": SCORING_RULE_SET_ID,
            "status": "research_contract",
            "producesScore": False,
        },
        "capability": {
            "status": "blocked",
            "producesFormalScore": False,
            "optimizerSearchEnabled": False,
            "reason": "exact_integer_reconciliation_not_completed",
        },
        "masterEvidence": {
            "comboBonus": _combo_bonus_evidence(
                _load_rows(master_root, "MasterLiveComboScoreBonus")
            ),
            "scoreRank": _score_rank_evidence(
                _load_rows(master_root, "MasterLiveScoreRank")
            ),
            "skillEffect": _skill_effect_evidence(
                _load_rows(master_root, "MasterLiveSkillEffect")
            ),
        },
        "nativeEvidence": _native_evidence(methods),
        "staticAnalysis": static_analysis,
        "knownMechanisms": known_mechanisms,
        "unknownMechanisms": list(UNKNOWN_MECHANISMS),
        "validationGate": {
            "replaySampleCount": reconciled_count,
            "fixtureReplayCount": int(replay_counts.get("fixture", 0)),
            "observedReplayCount": int(replay_counts.get("observed", 0)),
            "inputSnapshotReplayable": sample_count > 0,
            "exactIntegerReconciliation": False,
            "differenceTraceComplete": False,
            "formalCapability": replay_summary.get(
                "formalCapability", "external_gate"
            ),
            "gate": replay_summary.get("gate", "client_replay_sample_missing"),
        },
        "publicationPolicy": {
            "showEvidence": True,
            "showInputSnapshot": True,
            "showEstimatedScore": False,
            "showFormalScore": False,
            "showOptimizerResults": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--master-root", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--code-registration", type=lambda value: int(value, 0), required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--replay-root",
        type=Path,
        default=REPO_ROOT / "catalog/baselines/scoring",
    )
    args = parser.parse_args()

    from analysis.crypto.inspect_il2cpp import inspect_method_structures

    methods = inspect_method_structures(
        args.metadata,
        args.binary,
        args.code_registration,
        included_types=set(SCORING_TYPES),
    )
    from tools.scoring_replay import load_replays, summarize_replays

    replay_summary = summarize_replays(load_replays(args.replay_root))
    result = build_scoring_evidence(
        args.master_root,
        [method.to_dict() for method in methods],
        args.release_id,
        replay_summary,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
