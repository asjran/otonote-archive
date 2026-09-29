import policy from "../config/site-product.json" with { type: "json" };

const profile = import.meta.env?.PUBLIC_SITE_PROFILE
  ?? (typeof process !== "undefined" ? process.env.OURNOTES_SITE_PROFILE : undefined)
  ?? policy.profile;
if (profile !== "v1") throw new Error(`Unknown site profile: ${profile}`);
export { policy, profile };
