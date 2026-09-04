import type React from "react";

export type TenantIdentityConfig = {
  tenantName: string;
  academyName: string;
  attribution?: string;
  homeHref?: string;
  mark?: React.ReactNode;
  logo?: React.ReactNode;
};

export type TenantInfo = {
  id: string;
  name: string;
  academyName?: string;
  icon?: React.ReactNode;
};

export type TenantSwitcherConfig = {
  currentTenantId: string;
  tenants: TenantInfo[];
  onSelectTenant?: (tenantId: string) => void;
};
