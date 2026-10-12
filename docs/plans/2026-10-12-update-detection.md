# Update detection and scheduling, first delivery

This implements the first part of section D of the October 10 reliability plan.
The storage draft is kept on a separate local branch and is not part of this work.

## Behavior

- Preserve the verified light gate and all existing publication checks. Add staggered
  15-minute schedules, opt-in independently with repository variables
  `CONTENT_R2_FAST_POLL_GLOBAL=true` and `CONTENT_R2_FAST_POLL_JP=true`.
  Empty/false retains the existing four-hour schedule. Enabling fast polling
  disables that edition's legacy schedule, rather than adding duplicate jobs.
  `CONTENT_R2_ENABLED_*` still disables the edition completely; automatic
  promotion still follows the existing `CONTENT_R2_AUTO_PROMOTE_*` setting.
- Manual, fast and legacy runs share the same per-edition concurrency group.
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
- Record the actual selection-step UTC timestamp and the nominal poll interval
  in the Actions summary. This does not measure the original intended cron fire
  time or prove missing schedules were detected.

## Rollout and acceptance

1. Test workflow eligibility/region/concurrency and execute the actual selection
   shell under legacy, fast, manual and disabled combinations. Test production
   dependency invalidation, private-input binding, corrupt pointers and probe
   failures; retain the no-full-download unchanged tests for both regions.
2. Merge only after CI. The changed fingerprint/workflow requires fresh receipts;
   the first run may need the full path even when upstream data is unchanged.
   Keep fast polling off until each edition has a new verified receipt and a
   subsequent unchanged run skips restore/production/upload/checkpoint/promotion.
3. Enable fast polling per edition after reviewing that acceptance and current
   runner/origin capacity. Nominal volume rises from 6 to 96 eligible runs/day
   per edition; unchanged runtime still includes image pull, private manifest
   reads and source requests. It is not a free or image-free probe.
4. Evaluate actual admitted-run gaps, failures and stage durations before adding
   activity-window acceleration or a separate scheduler. A 15-minute cron is
   not a promise that content will publish within 15 minutes.
5. Roll back frequency by clearing the corresponding fast-poll variable. This
   restores legacy admission without changing source fingerprints or cancelling
   running jobs. Reverting producer code also invalidates receipts conservatively.

Remaining D work: actual scheduling-delay/missed-run observability, activity-window
policy and a measured case for a separate lightweight image. Restore optimization,
functional freshness and peak delivery stay in their own work packages.

Platform constraints: [GitHub schedule behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
and [concurrency behavior](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency).
