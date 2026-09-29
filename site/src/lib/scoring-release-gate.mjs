/** Exact content binding; reference estimates never inherit a client's audit. */
export function referenceScoringRules(rules) {
  const reference = rules?.referenceProfile;
  return rules?.verificationStatus === 'reference_compatible'
    && reference?.dataCompatibility === 'scoring_tables_matched'
    && reference.currentGameplayVerified === false
    && Boolean(reference.sourceReleaseId)
    && reference.sourceReleaseId === rules.native?.sourceReleaseId
    && reference.nativeSha256 === rules.native?.nativeSha256
    && reference.nativeSha256 === rules.nativeSha256;
}
export function scoringRulesAvailable(rules, releaseId) {
  return Boolean(releaseId && rules?.sourceReleaseId === releaseId
    && (rules.verificationStatus === "code_audited" || referenceScoringRules(rules)));
}
