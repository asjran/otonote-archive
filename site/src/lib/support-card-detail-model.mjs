export function createSupportCardDetailModel({ cardId, skillSummaries }) {
  const gekisouEffect = skillSummaries.find((summary) =>
    summary.slot.startsWith("gekisou")
  );
  const normalEffect = skillSummaries.find((summary) =>
    !summary.slot.startsWith("gekisou")
  );

  return {
    aspectRatio: "16:9",
    normalEffect,
    gekisouEffect,
    primaryAction: {
      logicalPath: `/tools/deck-builder/?support=${cardId}`,
      label: "装备到编成"
    },
    imageSidebarTopics: [
      { id: "growth", href: "?panel=growth", label: "成长" },
      { id: "materials", href: "?panel=materials", label: "材料" },
      { id: "resources", href: "?panel=resources", label: "资源" }
    ]
  };
}
