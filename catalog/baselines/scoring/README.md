# Golden Replay evidence intake

This directory contains release-bound, anonymized scoring samples. Only files
ending in `.json` are loaded by `tools/scoring_replay.py`; the template remains
inactive until it is copied to a real sample and every placeholder is replaced.

## Required capture

One client play must provide all of the following from the same result:

- the client/content release identifier and the rule-set identifier;
- the exact five-card formation and final integer total power;
- the chart identifier and ordered scoring events;
- the ordered judgement timeline;
- the ordered skill, Leader, fixed-score, and mode command timeline;
- the client final score and, when observable, per-note scores;
- stable evidence references such as a redacted log hash, screenshot hash, or
  exported result identifier.

Never commit account IDs, access tokens, device identifiers, or raw private
logs. Keep the original evidence outside the repository and commit only
redacted values plus hashes sufficient to prove that the inputs and result came
from the same play.

## Status promotion

- `observed`: the client result is attributable, but one or more intermediate
  values are unavailable.
- `reconciled`: the local engine matches the client final integer exactly and
  the first-difference trace is complete.
- `rejected`: the inputs and result cannot be shown to belong to the same play.

`observed` is not formal scoring evidence. The public calculator and optimizer
remain closed until at least one representative sample is `reconciled`.

Validate a captured sample with:

```sh
python3 tools/scoring_replay.py \
  --root catalog/baselines/scoring \
  --output output/readiness/scoring-replays.json

python3 tools/scoring_evidence.py \
  --master-root phone_dump/crypto/all-encrypted-json/Master \
  --metadata phone_dump/crypto/global-metadata.paged.v39.dat \
  --binary phone_dump/native/lib/arm64-v8a/libil2cpp.so \
  --code-registration 0x964A480 \
  --release-id jp-staging-6521695fc2fd2dfc \
  --replay-root catalog/baselines/scoring \
  --output site/src/data/scoring-evidence-report.json
```

The metadata, binary, registration address, and release ID above belong to the
current checked-in evidence set. Replace all four together when validating a
new client package; never reuse the native address across releases.
