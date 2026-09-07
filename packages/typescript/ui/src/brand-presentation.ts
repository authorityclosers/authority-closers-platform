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

/** Decorative supplied artwork, never a topic, completion badge or media grant. */
export const ACADEMY_ARTWORK = {
  discovery: {
    src: "/brand/learning-art-v1/discovery.webp",
    width: 960,
    height: 840,
  },
  reflection: {
    src: "/brand/learning-art-v1/reflection.webp",
    width: 960,
    height: 840,
  },
  nextMove: {
    src: "/brand/learning-art-v1/next-move.webp",
    width: 960,
    height: 840,
  },
} as const;

/** Verified supplied editorial derivative; not an instructor assignment to a program. */
export const INSTRUCTOR_PORTRAIT = {
  src: "/brand/instructor-v1/editorial.webp",
  width: 768,
  height: 960,
  alt: "Dipak Vishwakarma, your guide at Closers Academy",
} as const;
