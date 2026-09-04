"use client";

import { Check, ChevronDown } from "lucide-react";
import React, { useEffect, useRef, useState } from "react";
import type { TenantInfo } from "./sidebar-types";

function initialsForName(name: string): string {
  const parts = name.trim().split(/\s+/);
  if (parts.length >= 2) {
    return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
  }
  return name.slice(0, 2).toUpperCase();
}

export type TenantSwitcherProps = {
  currentTenantId?: string;
  tenants?: TenantInfo[];
  onSelectTenant?: (tenantId: string) => void;
  collapsed?: boolean;
  className?: string;
};

export function TenantSwitcher({
  currentTenantId,
  tenants,
  onSelectTenant,
  collapsed = false,
  className = "",
}: TenantSwitcherProps) {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isOpen) return;

    const handlePointerDown = (event: PointerEvent) => {
      if (
        event.target instanceof Node &&
        !containerRef.current?.contains(event.target)
      ) {
        setIsOpen(false);
      }
    };

    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [isOpen]);

  // Guardrail: With one configured tenant or fewer, do not render a fake switcher.
  if (!tenants || tenants.length <= 1) {
    return null;
  }

  // Switching organizations is an authenticated application action. Do not
  // expose an enabled control unless the host provides the real handler.
  if (!onSelectTenant) {
    return null;
  }

  const currentTenant =
    tenants.find((t) => t.id === currentTenantId) ?? tenants[0];

  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "Escape") {
      event.preventDefault();
      setIsOpen(false);
      buttonRef.current?.focus();
      return;
    }

    if (!isOpen) {
      if (
        event.key === "ArrowDown" ||
        event.key === "Enter" ||
        event.key === " "
      ) {
        event.preventDefault();
        setIsOpen(true);
      }
      return;
    }

    const items = menuRef.current
      ? Array.from(
          menuRef.current.querySelectorAll<HTMLButtonElement>(
            '[role="menuitemradio"]',
          ),
        )
      : [];

    if (!items.length) return;

    const currentIndex = items.indexOf(
      document.activeElement as HTMLButtonElement,
    );

    if (event.key === "ArrowDown") {
      event.preventDefault();
      const nextIndex = currentIndex < items.length - 1 ? currentIndex + 1 : 0;
      items[nextIndex]?.focus();
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      const prevIndex = currentIndex > 0 ? currentIndex - 1 : items.length - 1;
      items[prevIndex]?.focus();
    }
  };

  const handleSelect = (tenantId: string) => {
    setIsOpen(false);
    onSelectTenant(tenantId);
    buttonRef.current?.focus();
  };

  return (
    <div
      ref={containerRef}
      className={`tenant-switcher${collapsed ? " is-collapsed" : ""}${
        className ? ` ${className}` : ""
      }`}
      onKeyDown={handleKeyDown}
    >
      <button
        ref={buttonRef}
        type="button"
        className="tenant-switcher__trigger"
        onClick={() => setIsOpen((prev) => !prev)}
        aria-haspopup="menu"
        aria-expanded={isOpen}
        aria-controls="tenant-switcher-menu"
        aria-label={
          collapsed
            ? `Organization: ${currentTenant.name}. Switch organization`
            : `Current organization: ${currentTenant.name}`
        }
        title={collapsed ? currentTenant.name : undefined}
      >
        <span className="tenant-switcher__icon" aria-hidden="true">
          {currentTenant.icon ?? (
            <span className="tenant-switcher__initials">
              {initialsForName(currentTenant.name)}
            </span>
          )}
        </span>
        {!collapsed ? (
          <>
            <span className="tenant-switcher__name">{currentTenant.name}</span>
            <ChevronDown
              size={14}
              className={`tenant-switcher__chevron${isOpen ? " is-open" : ""}`}
              aria-hidden="true"
            />
          </>
        ) : null}
      </button>

      {isOpen ? (
        <div
          id="tenant-switcher-menu"
          ref={menuRef}
          role="menu"
          className="tenant-switcher__dropdown"
          aria-label="Switch organization"
        >
          <div className="tenant-switcher__menu-header">
            <span>Switch organization</span>
          </div>
          <div className="tenant-switcher__menu-items">
            {tenants.map((tenant) => {
              const isSelected = tenant.id === currentTenant.id;
              return (
                <button
                  key={tenant.id}
                  type="button"
                  role="menuitemradio"
                  aria-checked={isSelected}
                  className={`tenant-switcher__option${
                    isSelected ? " is-selected" : ""
                  }`}
                  onClick={() => handleSelect(tenant.id)}
                >
                  <span className="tenant-switcher__option-name">
                    {tenant.name}
                  </span>
                  {isSelected ? (
                    <Check
                      size={14}
                      className="tenant-switcher__check"
                      aria-hidden="true"
                    />
                  ) : null}
                </button>
              );
            })}
          </div>
        </div>
      ) : null}
    </div>
  );
}
