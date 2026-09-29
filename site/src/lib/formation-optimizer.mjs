const entityId = (value) => String(value?.id ?? "");
const cheapValue = (value) => Number(value?.cheapScore ?? 0);

function formationId(slots) {
  return slots
    .map((slot) => `${entityId(slot.member)}+${entityId(slot.support)}`)
    .join("|");
}

function compareCandidate(left, right) {
  return right.cheapScore - left.cheapScore || left.id.localeCompare(right.id);
}

function permutationCount(length, size) {
  let count = 1n;
  for (let index = 0; index < size; index += 1) count *= BigInt(length - index);
  return count;
}

function insertShortlist(shortlist, candidate, limit) {
  let low = 0;
  let high = shortlist.length;
  while (low < high) {
    const middle = (low + high) >> 1;
    if (compareCandidate(candidate, shortlist[middle]) < 0) high = middle;
    else low = middle + 1;
  }
  if (low >= limit) return;
  shortlist.splice(low, 0, candidate);
  if (shortlist.length > limit) shortlist.pop();
}

function generateCandidates({
  members,
  supports,
  ruleProfile,
  prefilterLimit,
  maxGeneratedCandidates,
  cheapPairScore,
  signal
}) {
  if (ruleProfile.allowMemberDuplicates || ruleProfile.allowSupportDuplicates) {
    throw new Error("Duplicate-enabled formation profiles require an explicit candidate adapter");
  }
  const slotCount = ruleProfile.slotCount;
  const orderedMembers = [...members].sort((a, b) => entityId(a).localeCompare(entityId(b)));
  const orderedSupports = [...supports].sort((a, b) => entityId(a).localeCompare(entityId(b)));
  const usedMembers = new Set();
  const usedSupports = new Set();
  const slots = [];
  const shortlist = [];
  let generatedCount = 0;
  let cancelled = false;

  const visit = (cheapScore) => {
    if (signal?.aborted) {
      cancelled = true;
      return;
    }
    if (generatedCount >= maxGeneratedCandidates) return;
    if (slots.length === slotCount) {
      generatedCount += 1;
      insertShortlist(shortlist, {
        id: formationId(slots),
        slots: slots.map((slot) => ({ ...slot })),
        cheapScore
      }, prefilterLimit);
      return;
    }
    for (const member of orderedMembers) {
      if (usedMembers.has(entityId(member))) continue;
      usedMembers.add(entityId(member));
      for (const support of orderedSupports) {
        if (usedSupports.has(entityId(support))) continue;
        usedSupports.add(entityId(support));
        const slot = { member, support };
        slots.push(slot);
        visit(cheapScore + (cheapPairScore
          ? cheapPairScore(slot, slots.length - 1)
          : cheapValue(member) + cheapValue(support)));
        slots.pop();
        usedSupports.delete(entityId(support));
        if (cancelled || generatedCount >= maxGeneratedCandidates) break;
      }
      usedMembers.delete(entityId(member));
      if (cancelled || generatedCount >= maxGeneratedCandidates) break;
    }
  };
  visit(0);
  return { shortlist, generatedCount, cancelled };
}

export async function optimizeFormations({
  members = [],
  supports = [],
  ruleProfile,
  exactScore,
  cheapPairScore,
  prefilterLimit = 200,
  maxGeneratedCandidates = 100_000,
  topN = 10,
  signal,
  onProgress
}) {
  if (ruleProfile?.verificationStatus !== "reconciled") {
    return {
      status: "blocked",
      reason: "formation_rules_not_reconciled",
      results: []
    };
  }
  if (typeof exactScore !== "function") throw new TypeError("exactScore adapter is required");
  const slotCount = Number(ruleProfile.slotCount);
  if (!Number.isInteger(slotCount) || slotCount < 1) {
    throw new RangeError("slotCount must be a positive integer");
  }
  for (const [name, value] of Object.entries({ prefilterLimit, maxGeneratedCandidates, topN })) {
    if (!Number.isSafeInteger(value) || value < 1) {
      throw new RangeError(`${name} must be a positive safe integer`);
    }
  }
  for (const [name, pool] of [["members", members], ["supports", supports]]) {
    if (new Set(pool.map(entityId)).size !== pool.length || pool.some((entity) => !entityId(entity))) {
      throw new RangeError(`${name} must have unique nonempty ids`);
    }
  }
  if (cheapPairScore !== undefined && typeof cheapPairScore !== "function") {
    throw new TypeError("cheapPairScore must be a function");
  }
  if (signal?.aborted) return { status: "cancelled", results: [] };
  if (members.length < slotCount || supports.length < slotCount) {
    return {
      status: "completed",
      ruleSetVersion: ruleProfile.id,
      totalCandidateCount: "0",
      generatedCount: 0,
      exactCount: 0,
      results: []
    };
  }

  const totalCandidateCount = (
    permutationCount(members.length, slotCount)
    * permutationCount(supports.length, slotCount)
  ).toString();
  const { shortlist, generatedCount, cancelled } = generateCandidates({
    members,
    supports,
    ruleProfile: { ...ruleProfile, slotCount },
    prefilterLimit,
    maxGeneratedCandidates,
    cheapPairScore,
    signal
  });
  if (cancelled) return { status: "cancelled", results: [] };

  const scored = [];
  for (const [index, candidate] of shortlist.entries()) {
    if (signal?.aborted) return { status: "cancelled", results: [] };
    const score = await exactScore(candidate);
    if (!Number.isSafeInteger(score)) {
      throw new RangeError(`Exact score must be a safe integer: ${candidate.id}`);
    }
    scored.push({ ...candidate, score });
    onProgress?.({ completed: index + 1, total: shortlist.length, candidateId: candidate.id });
  }
  scored.sort((left, right) =>
    right.score - left.score
    || right.cheapScore - left.cheapScore
    || left.id.localeCompare(right.id)
  );
  const complete = BigInt(generatedCount) === BigInt(totalCandidateCount)
    && shortlist.length === generatedCount;
  return {
    status: complete ? "completed" : "budget_exhausted",
    ruleSetVersion: ruleProfile.id,
    totalCandidateCount,
    generatedCount,
    exactCount: scored.length,
    results: scored.slice(0, topN)
  };
}
