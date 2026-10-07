import type { CSSProperties, ReactNode } from "react";
import Link from "next/link";
import { ChevronRight, type LucideIcon } from "lucide-react";

import styles from "./operational-panel.module.css";

export interface OperationalPanelAction {
  href: string;
  label: string;
  badge?: ReactNode;
  external?: boolean;
}

export interface OperationalPanelProps {
  title?: ReactNode;
  headingLevel?: "h2" | "h3" | "h4";
  id?: string;
  sub?: ReactNode;
  action?: OperationalPanelAction | ReactNode;
  tools?: ReactNode;
  foot?: ReactNode;
  children?: ReactNode;
  className?: string;
  bodyClassName?: string;
  headClassName?: string;
  style?: CSSProperties;
  "aria-label"?: string;
  "aria-labelledby"?: string;
}

export function OperationalPanel({
  title,
  headingLevel = "h3",
  id,
  sub,
  action,
  tools,
  foot,
  children,
  className,
  bodyClassName,
  headClassName,
  style,
  "aria-label": ariaLabel,
  "aria-labelledby": ariaLabelledBy,
}: OperationalPanelProps) {
  const Heading = headingLevel;
  const titleId = id && title ? `${id}-title` : undefined;
  const effectiveAriaLabelledBy = ariaLabelledBy ?? titleId;

  const renderAction = () => {
    if (!action) return null;
    if (
      typeof action === "object" &&
      action !== null &&
      "href" in action &&
      "label" in action
    ) {
      const act = action as OperationalPanelAction;
      return (
        <Link
          href={act.href}
          className={styles.panelAction}
          target={act.external ? "_blank" : undefined}
          rel={act.external ? "noopener noreferrer" : undefined}
        >
          <span>{act.label}</span>
          {act.badge ? (
            <span className={styles.actionBadge}>{act.badge}</span>
          ) : null}
          <ChevronRight
            size={14}
            aria-hidden="true"
            className={styles.actionIcon}
          />
        </Link>
      );
    }
    return <>{action}</>;
  };

  return (
    <section
      id={id}
      data-pulse-adapted="true"
      className={`${styles.panel}${className ? ` ${className}` : ""}`}
      style={style}
      aria-labelledby={effectiveAriaLabelledBy}
      aria-label={!effectiveAriaLabelledBy ? ariaLabel : undefined}
    >
      {(title || tools || action) && (
        <div
          className={`${styles.panelHead}${headClassName ? ` ${headClassName}` : ""}`}
        >
          {title ? (
            <div className={styles.titleGroup}>
              <Heading id={titleId} className={styles.panelTitle}>
                {title}
              </Heading>
              {sub !== undefined && sub !== null ? (
                typeof sub === "string" ? (
                  <p className={styles.panelSubtitle}>{sub}</p>
                ) : (
                  <div className={styles.panelSubtitle}>{sub}</div>
                )
              ) : null}
            </div>
          ) : null}
          {(tools || action) && (
            <div className={styles.panelControls}>
              {tools ? <div className={styles.toolsGroup}>{tools}</div> : null}
              {renderAction()}
            </div>
          )}
        </div>
      )}
      {children !== undefined && children !== null ? (
        <div
          className={`${styles.panelBody}${bodyClassName ? ` ${bodyClassName}` : ""}`}
        >
          {children}
        </div>
      ) : null}
      {foot ? <div className={styles.panelFoot}>{foot}</div> : null}
    </section>
  );
}

export interface OperationalEmptyProps {
  icon?: LucideIcon;
  title: ReactNode;
  headingLevel?: "h2" | "h3" | "h4";
  titleId?: string;
  description?: ReactNode;
  action?: ReactNode;
  compact?: boolean;
  className?: string;
}

export function OperationalEmpty({
  icon: Icon,
  title,
  headingLevel = "h4",
  titleId,
  description,
  action,
  compact,
  className,
}: OperationalEmptyProps) {
  const Heading = headingLevel;
  return (
    <div
      data-pulse-adapted="true"
      className={`${styles.emptyState}${compact ? ` ${styles.emptyCompact}` : ""}${className ? ` ${className}` : ""}`}
    >
      {Icon && (
        <div className={styles.emptyIconWrap}>
          <Icon size={compact ? 18 : 22} aria-hidden="true" />
        </div>
      )}
      <div className={styles.emptyContent}>
        {typeof title === "string" ? (
          <Heading id={titleId} className={styles.emptyTitle}>
            {title}
          </Heading>
        ) : (
          <div id={titleId} className={styles.emptyTitle}>
            {title}
          </div>
        )}
        {description && (
          <p className={styles.emptyDescription}>{description}</p>
        )}
      </div>
      {action && <div className={styles.emptyAction}>{action}</div>}
    </div>
  );
}
