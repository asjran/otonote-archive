# Update detection and scheduling, first delivery

This implements the first part of section D of the October 10 reliability plan.
The storage draft is kept on a separate local branch and is not part of this work.

Scheduling policy updated on 2026-10-19 at the user's request: both editions use
Beijing 09:00 (before the usual 10:00 maintenance), 14:00 (usual reopening) and
19:00. These are three workflow triggers per day, each checking both enabled
editions. Extra or shifted updates are manual; there is no maintenance retry loop.

## Behavior

- Preserve the verified light gate and all existing publication checks. A single
  UTC cron, `0 1,6,11 * * *`, starts a matrix containing both enabled editions.
  Remove the legacy four-hour and fast fifteen-minute cron entries and their
  `CONTENT_R2_FAST_POLL_*` switches; old repository values no longer affect cadence.
  `CONTENT_R2_ENABLED_*` still disables the edition completely; automatic
  promotion still follows the existing `CONTENT_R2_AUTO_PROMOTE_*` setting.
- Manual and scheduled runs share the same per-edition concurrency group.
  A manual dispatch checks only the selected edition. One edition failing does
  not cancel the other edition's matrix job.
  Running production/upload/checkpoint/promotion is not cancelled. Pending runs
  can be coalesced by GitHub; each admitted run probes the source again.
- Keep all new/unclassified tools in the producer fingerprint by default.
  Exclude only the exact reviewed operational leaves declared in
  `tools.jp_update.NON_PRODUCTION_FILES`. This applies consistently to JP
  candidate reuse and both regions' gate receipts. Decoder, converter, scoring,
  configuration, image build inputs and the production workflow remain bound.
  A dependency regression guards the exclusions against Python imports and
  literal subprocess/importlib calls from included sources. This is deliberately
  not an exhaustive cross-language/dynamic dependency resolver.
- Report full-path reasons with an explicit public allowlist. Distinguish
  producer source, package, resource-version and pointer changes. Failed probes
  leave a bounded JSON result, return nonzero and stop the workflow; they never
  become an unchanged result. Generic protocol/transport failures are not labelled
  as confirmed maintenance without an authoritative upstream signal.
- Record the actual selection-step UTC timestamp and the daily Beijing schedule
  in the Actions summary. This does not measure the original intended cron fire
  time or prove missing schedules were detected.
- Health sampling compares receipts with the latest expected slot after one hour
  of scheduling grace, using `tools/r2_schedule.py`. The expected overnight gap
  from 19:00 to 09:00 does not raise stale alerts. Manual success does not replace
  the native schedule timestamp. CI checks workflow, health and optional external
  timer templates against the same three slots.

## Rollout and acceptance

1. Test workflow eligibility/region/concurrency and execute the actual selection
   shell under scheduled, manual and disabled combinations. Test production
   dependency invalidation, private-input binding, corrupt pointers and probe
   failures; retain the no-full-download unchanged tests for both regions.
2. Merge only after CI. The changed fingerprint/workflow requires fresh receipts;
   the first run may need the full path even when upstream data is unchanged.
   Verify each edition obtains a new receipt and a
   subsequent unchanged run skips restore/production/upload/checkpoint/promotion.
3. Merge the workflow to the default branch to activate the three daily triggers
   (six edition checks/day). Deploy the matching health sampler and schedule
   module together so the old one-hour stale rule cannot create false alerts.
   Unchanged runtime still includes image pull, private manifest reads and source
   requests. No external scheduler is enabled by this source change.
4. Scheduled starts can be delayed or dropped by GitHub; the times are intended
   check slots, not publication deadlines. If maintenance ends later or an event
   shifts, manually dispatch the affected edition with `mode=auto`.
5. Roll back by reverting the reviewed schedule/health change together. Changing
   producer workflow code invalidates receipts conservatively; do not cancel an
   upload or promotion in progress.

Remaining D work: actual scheduling-delay/missed-run observability and a measured
case for a separate lightweight image. Restore optimization,
functional freshness and peak delivery stay in their own work packages.

Platform constraints: [GitHub schedule behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
and [concurrency behavior](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency).

## Local validation of the 2026-10-19 schedule change

- 67 tests passed across schedule selection, update health, run records, external
  dispatch, production gates, run summaries and documentation status.
- Official actionlint v1.7.7 validated the workflow structure and expressions;
  optional shellcheck/pyflakes integrations were disabled. YAML parsing and
  `git diff --check` also passed.
- An additional state-reuse suite passed 22 tests, but two SDK-specific tests
  could not run because local `botocore` is absent. Installing the repository's
  pinned `boto3==1.43.105` failed because that version was unavailable from the
  configured package source. No dependency pins were changed.
- No push, merge, server deployment or production update was performed. Native
  scheduled execution and deployed health acceptance remain after publication.
