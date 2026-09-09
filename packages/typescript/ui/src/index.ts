export {
  ACADEMY_ARTWORK,
  INSTRUCTOR_PORTRAIT,
  COMPANY_BRAND,
  FIRST_ACADEMY_BRAND,
  PLATFORM_BRAND,
} from "./brand-presentation";
export type { BrandPresentation } from "./brand-presentation";
export {
  ActionButton,
  actionClassName,
  ChoiceOption,
  FocusSession,
  SessionStep,
} from "./interaction-primitives";
export type { ActionVariant } from "./interaction-primitives";
export { AcademyMark, BrandMark, PlatformMark } from "./mark";
export { LearningSymbol, ProgressOrbit } from "./learning-symbol";
export { RewardReveal } from "./reward-reveal";
export {
  PracticeCompanion,
  PRACTICE_COMPANIONS,
  normalizePracticeCompanion,
} from "./practice-companion";
export type {
  PracticeCompanionKind,
  PracticeCompanionMood,
} from "./practice-companion";
export type { LearningSymbolKind } from "./learning-symbol";
export {
  ActivityRow,
  ModuleCard,
  NextActionCard,
  ProgramCard,
  ProgressMeter,
  RouteHeader,
  StatusBanner,
} from "./learning-primitives";
export type {
  ActivityRowProps,
  ModuleCardProps,
  NextActionCardProps,
  ProgramCardProps,
  ProgressMeterProps,
  RouteHeaderProps,
  StatusBannerProps,
  StatusBannerState,
} from "./learning-primitives";
export { SidebarBadge } from "./sidebar-badge";
export type {
  BadgeVariant,
  SidebarBadgeConfig,
  SidebarBadgeProps,
} from "./sidebar-badge";
export { SidebarTooltip } from "./sidebar-tooltip";
export type { SidebarTooltipProps } from "./sidebar-tooltip";
export type {
  TenantIdentityConfig,
  TenantInfo,
  TenantSwitcherConfig,
} from "./tenant-contracts";
