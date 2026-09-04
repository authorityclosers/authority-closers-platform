import type React from "react";
import type {
  BadgeVariant as SharedBadgeVariant,
  SidebarBadgeConfig as SharedSidebarBadgeConfig,
  TenantIdentityConfig as SharedTenantIdentityConfig,
  TenantInfo as SharedTenantInfo,
  TenantSwitcherConfig as SharedTenantSwitcherConfig,
} from "@ac/ui";

export type BadgeVariant = SharedBadgeVariant;
export type SidebarBadgeConfig = SharedSidebarBadgeConfig;

export type SidebarNavItemConfig = {
  id: string;
  label: string;
  href: string;
  icon?: React.ReactNode;
  current?: boolean;
  disabled?: boolean;
  disabledReason?: string;
  badge?: SidebarBadgeConfig;
  visible?: boolean;
  children?: SidebarNavItemConfig[];
  external?: boolean;
  title?: string;
  density?: "comfortable" | "compact";
  onClick?: () => void;
};

export type SidebarNavSection = {
  id: string;
  label?: string;
  items: SidebarNavItemConfig[];
};

export type TenantIdentityConfig = SharedTenantIdentityConfig;
export type TenantInfo = SharedTenantInfo;
export type TenantSwitcherConfig = SharedTenantSwitcherConfig;

export type CommandPaletteItem = {
  id: string;
  label: string;
  description?: string;
  href?: string;
  icon?: React.ReactNode;
  category: "Navigation" | "Actions" | "Help";
  keywords?: string[];
  shortcut?: string;
  onSelect?: () => void;
};
