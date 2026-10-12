# Origin storage follow-up

Status: implementation prepared; production installation and destructive maintenance require separate recorded acceptance. This follows the October 10 update reliability plan and the October 12 directory audit.

## Behavior and compatibility

- Global resource revisions with an optional eight-hex-digit suffix are handled by the separate protocol fix. Client package validation remains numeric.
- Code uploads use unique `incoming/<codeId>-<uuid>` stages. The publisher verifies the installed copy and health before removing its own stage. Failed health retains the input and restores serving pointers. Legacy shared stages are not automatically removed.
- Renderer-input eviction uses plan/apply with render and materialization locks. It protects both local region pointers, current/previous/pending rendered views, cross-region library inputs and two newest materialized inputs per region. Inputs younger than one day and legacy inputs without a materialization receipt remain. Unknown pending references block cleanup. Every selected file is verified against the materialization receipt before deleting anything; changed pointers or inventories invalidate the plan.
- This store is a reproducible R2 read cache, not the Nginx content store. No remote object, served payload, code release or active HTML is deleted. The public immutable bucket must continue retaining the objects; coordinated remote garbage collection is outside this change.
- HTML archives expire after 14 days only after complete archive verification and current/previous/pending reference checks. Total local archive creation is limited to 4 GiB (512 MiB per batch). Exhausting the budget preserves HTML and reports failure. Historical rollback outside the retained window requires rematerializing pinned cloud inputs and rebuilding with the corresponding retained code.
- Before downloading, the wrapper adds simultaneous image/materialization/render budgets per filesystem plus a separate 2 GiB reserve. Materialization enforces a shared new-byte budget for both regions, including allocation rounding and receipt/directory allowance. The render budget still needs to cover measured rendering peaks; it is not an OS disk quota.

## Deployment order

1. Merge after required CI, build and verify a new pinned prerender image including `--max-new-bytes` support. Keep the prior image and wrapper.
2. Install the matching wrapper and image settings together while no prerender is running. Do not point the new wrapper at an older image. Leave code/content serving pointers unchanged.
3. Install an immutable maintenance program with `operations.py`, `render_retention.py`, `prerender_cache_retention.py` and the maintenance wrapper. Add the independent input-cache root to its external environment as `RENDER_MAINTENANCE_CONTENT_ROOT`.
4. Produce and review cache plans; verify candidate manifests are still available in the immutable remote bucket. Run apply under existing locks, then compare live pointers, representative pages and an old payload hash.
5. Code-stage cleanup becomes active only for deployments using both the updated client and reviewed publication runtime. Existing incoming duplicates require a separate quiescent, hash-verified cleanup list.
6. Keep service CPU/memory/I/O bounds; record actual free bytes and daily net growth. Roll back by restoring the old wrapper/image and immutable maintenance unit path. Evicted cache inputs are downloaded from R2 on demand; currently protected rollback inputs remain local.

## Remaining capacity boundaries

This change closes input-cache and new-upload accumulation and bounds HTML archives. It does not delete historical browser payloads or code chunks, implement an old-tab expiration contract, rotate unrelated service logs, or claim unlimited site growth fits a finite disk. Reports and all served historical assets still need a separate finite retention policy. Reserve checks stop a new publication when its measured working-space budget cannot fit; the previous website remains available. The origin-wide target remains 8 GiB free after publication, subject to a fresh production measurement.

## Validation

Regression cases cover reference closure, stale plans, unexpected files, symlinks, publisher contention, external hardlinks, zero download budget, archive expiry races, archive budget refusal and failed code health checks. Cloud fresh-run production and the following unchanged run remain separate acceptance gates.
