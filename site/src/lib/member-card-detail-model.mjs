export function createMemberCardDetailModel({
  cardId,
  skillSummaries,
  resolveSkill
}) {
  const primarySkillSummary = skillSummaries[0];
  const primarySkill = primarySkillSummary
    ? resolveSkill(primarySkillSummary.skillId)
    : undefined;

  return {
    primarySkill,
    primarySkillSummary,
    detailSkillIds: skillSummaries
      .slice(primarySkill ? 1 : 0)
      .map((summary) => summary.skillId),
    primaryAction: {
      logicalPath: `/tools/deck-builder/?member=${cardId}`,
      label: "加入编成"
    }
  };
}
