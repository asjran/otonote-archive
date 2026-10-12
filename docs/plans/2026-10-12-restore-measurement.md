# Restore measurements before changing the storage protocol

This is the measurement part of section E of the update reliability plan.
The existing restore downloads each unique object once, then recreates independent
copies and original hard links. A large count of small objects can dominate GET
latency even when their aggregate bytes are small. A bounded local read comparison
supports investigating concurrency, but cannot establish Actions runner performance.

## First delivery

Successful restores report aggregate object/byte counts and monotonic wall time:

- preparation: manifest retrieval/validation and destination checks;
- staging: unique-object selection and download directory creation;
- download and verification: concurrent GETs, stream validation and local rehash;
- materialization: independent copies and original hard links;
- publication and proof: destination moves, stage cleanup and verification proof;
- total: entry through proof completion, excluding final report serialization.

Counts describe successful unique object downloads, not billed requests: retries,
manifest/pointer GETs and unsuccessful attempts are not counted. Logical bytes
include all paths. Timings are wall durations, not summed worker CPU time. Failure
still raises the original error; it does not emit a successful metrics record.
Linux/macOS also report process-lifetime peak resident memory in bytes. This
includes manifest parsing and verification, not only download buffers, and does
not include other runner processes or represent total runner memory usage.

Actions saves this aggregate result for its existing always-run summary. The summary
allows only named bounded numeric fields; no object keys, paths, ETags or proof content
are copied into it. Empty results remain explicitly unavailable after a failed step.
The checkpoint protocol, verification proof and publish order stay unchanged.
Existing corruption and proof-reuse tests remain acceptance gates.

Restore concurrency defaults to 8. Repository variables
`CONTENT_R2_RESTORE_WORKERS_GLOBAL` and `CONTENT_R2_RESTORE_WORKERS_JP` independently
admit only 4, 8 or 12 workers, validated before expensive steps. Upload/checkpoint
concurrency stays at 8. This enables a controlled 8-versus-12 runner comparison
without another source release, and can be rolled back by clearing the variable.
The setting does not alter output identities or skip integrity checks. Compare
successful restored inputs, overall stage time and memory/disk headroom before
retaining a higher value; local-network timings alone are not acceptance.

## Decision and rollout

Do not introduce packs until a representative Actions measurement compares request
count, elapsed time, memory, disk and retry cost. Downloading a pack does not prove
the ETags of its constituent CAS objects for checkpoint reuse: a pack design must
preserve this evidence or measure any checkpoint readback it introduces.

The workflow/source change invalidates producer receipts conservatively. Finish
the preceding scheduling rollout before merging; then validate one full and one
unchanged run per region. The next full run supplies the stage baseline without
adding a separate synthetic production run. Rollback is a normal source revert;
there are no remote object migrations or origin services to undo.
