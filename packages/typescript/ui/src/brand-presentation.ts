/**
 * Trusted, serializable artwork and display labels for the alpha shell.
 * These descriptors are not tenant records, lookup keys, access decisions,
 * publication approval, or a substitute for server-provided academy identity.
 * Brand colours describe the supplied artwork, not semantic UI state tokens.
 */
export type BrandPresentation = {
  readonly name: string;
  readonly role: "company" | "academy" | "platform";
  readonly releaseStatus: "proposal" | "starter-concept" | "provisional-name";
  readonly color: string;
  readonly assets: {
    readonly wordmark: string;
    readonly symbol: string;
    readonly icon: string;
  };
};

export const COMPANY_BRAND = {
  name: "Authority Closers",
  role: "company",
  releaseStatus: "proposal",
  color: "#152638",
  assets: {
    wordmark: "/brand/ac-v0.1/horizontal.svg",
    symbol: "/brand/ac-v0.1/symbol.svg",
    icon: "/brand/ac-v0.1/icon.svg",
  },
} as const satisfies BrandPresentation;

/** The first academy's presentation only; never a default tenant identifier. */
export const FIRST_ACADEMY_BRAND = {
  name: "Closers Academy",
  role: "academy",
  releaseStatus: "starter-concept",
  color: "#173F43",
  assets: {
    wordmark: "/brand/closers-academy-v0.1/horizontal.svg",
    symbol: "/brand/closers-academy-v0.1/symbol.svg",
    icon: "/brand/closers-academy-v0.1/icon.svg",
  },
} as const satisfies BrandPresentation;

export const PLATFORM_BRAND = {
  name: "Cohorva",
  role: "platform",
  releaseStatus: "provisional-name",
  color: "#3155C6",
  assets: {
    wordmark: "/brand/cohorva-v0.1/horizontal.svg",
    symbol: "/brand/cohorva-v0.1/symbol.svg",
    icon: "/brand/cohorva-v0.1/icon.svg",
  },
} as const satisfies BrandPresentation;
