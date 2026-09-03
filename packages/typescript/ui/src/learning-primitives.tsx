import type { ReactNode } from "react";

function joinClasses(...classes: Array<string | undefined | false>) {
  return classes.filter(Boolean).join(" ");
}

export type StatusBannerState =
  | "info"
  | "success"
  | "warning"
  | "error"
  | "offline";

export type RouteHeaderProps = {
  title: ReactNode;
  titleId?: string;
  titleClassName?: string;
  eyebrow?: ReactNode;
  breadcrumbs?: ReactNode;
  description?: ReactNode;
  descriptionClassName?: string;
  aside?: ReactNode;
  actions?: ReactNode;
  className?: string;
};

/**
 * Shared page-header geometry for route-owned copy and actions.
 *
 * It deliberately accepts rendered content instead of knowing about routes,
 * enrollment, or any other business state.
 */
export function RouteHeader({
  title,
  titleId,
  titleClassName,
  eyebrow,
  breadcrumbs,
  description,
  descriptionClassName,
  aside,
  actions,
  className,
}: RouteHeaderProps) {
  return (
    <header
      className={joinClasses("ac-route-header", className)}
      aria-labelledby={titleId}
    >
      {breadcrumbs ? (
        <div className="ac-route-header__breadcrumbs">{breadcrumbs}</div>
      ) : null}
      <div className="ac-route-header__layout">
        <div className="ac-route-header__copy">
          {eyebrow ? (
            <div className="ac-route-header__eyebrow">{eyebrow}</div>
          ) : null}
          <h1
            id={titleId}
            className={joinClasses("ac-route-header__title", titleClassName)}
          >
            {title}
          </h1>
          {description ? (
            <p
              className={joinClasses(
                "ac-route-header__description",
                descriptionClassName,
              )}
            >
              {description}
            </p>
          ) : null}
        </div>
        {aside ? <div className="ac-route-header__aside">{aside}</div> : null}
      </div>
      {actions ? (
        <div className="ac-route-header__actions">{actions}</div>
      ) : null}
    </header>
  );
}

export type StatusBannerProps = {
  state: StatusBannerState;
  title?: ReactNode;
  children: ReactNode;
  action?: ReactNode;
  role?: "alert" | "status";
  className?: string;
};

/** A semantic state surface; the caller owns the actual state decision. */
export function StatusBanner({
  state,
  title,
  children,
  action,
  role = state === "error" ? "alert" : "status",
  className,
}: StatusBannerProps) {
  return (
    <div
      className={joinClasses(
        `ac-status-banner ac-status-banner--${state}`,
        className,
      )}
      role={role}
      aria-live={role === "alert" ? "assertive" : "polite"}
    >
      {title ? (
        <strong className="ac-status-banner__title">{title}</strong>
      ) : null}
      <div className="ac-status-banner__body">{children}</div>
      {action ? <div className="ac-status-banner__action">{action}</div> : null}
    </div>
  );
}

export type ProgressMeterProps = {
  /** `null` represents a known-but-unavailable projection, not zero. */
  value: number | null;
  label: string;
  detail: string;
  className?: string;
};

/** A bounded progress presentation. The caller supplies the canonical value. */
export function ProgressMeter({
  value,
  label,
  detail,
  className,
}: ProgressMeterProps) {
  const safeValue =
    typeof value === "number" && Number.isFinite(value)
      ? Math.min(100, Math.max(0, value))
      : null;
  const valueLabel = safeValue === null ? "Unavailable" : `${safeValue}%`;

  return (
    <div className={joinClasses("progress-meter", className)}>
      <div className="progress-meter__labels">
        <span>{label}</span>
        <strong className="progress-meter__value">{valueLabel}</strong>
        <span className="progress-meter__detail">{detail}</span>
      </div>
      <div
        className={joinClasses(
          "progress-meter__track",
          safeValue === null ? "progress-meter__track--unknown" : undefined,
        )}
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        {...(safeValue === null
          ? { "aria-valuetext": `${label}: ${detail}` }
          : {
              "aria-valuenow": safeValue,
              "aria-valuetext": `${valueLabel} · ${detail}`,
            })}
      >
        <span style={{ width: `${safeValue ?? 0}%` }} />
      </div>
    </div>
  );
}

export type ProgramCardProps = {
  title: ReactNode;
  titleId?: string;
  titleAs?: "h2" | "h3";
  eyebrow?: ReactNode;
  badges?: ReactNode;
  description?: ReactNode;
  meta?: ReactNode;
  media?: ReactNode;
  action?: ReactNode;
  children?: ReactNode;
  className?: string;
};

/** Presentational program card for public catalog and learner-owned surfaces. */
export function ProgramCard({
  title,
  titleId,
  titleAs = "h3",
  eyebrow,
  badges,
  description,
  meta,
  media,
  action,
  children,
  className,
}: ProgramCardProps) {
  const Title = titleAs;

  return (
    <article
      className={joinClasses("ac-program-card", className)}
      aria-labelledby={titleId}
    >
      {media ? <div className="ac-program-card__media">{media}</div> : null}
      <div className="ac-program-card__body">
        {eyebrow ? <p className="ac-program-card__eyebrow">{eyebrow}</p> : null}
        {badges ? (
          <div className="ac-program-card__badges">{badges}</div>
        ) : null}
        <Title id={titleId} className="ac-program-card__title">
          {title}
        </Title>
        {description ? (
          <p className="ac-program-card__description">{description}</p>
        ) : null}
        {meta ? <div className="ac-program-card__meta">{meta}</div> : null}
        {children ? (
          <div className="ac-program-card__content">{children}</div>
        ) : null}
        {action ? (
          <div className="ac-program-card__action">{action}</div>
        ) : null}
      </div>
    </article>
  );
}

export type NextActionCardProps = {
  eyebrow?: ReactNode;
  title: ReactNode;
  detail?: ReactNode;
  action: ReactNode;
  className?: string;
};

/** A single dominant action slot; the caller owns action authorization. */
export function NextActionCard({
  eyebrow,
  title,
  detail,
  action,
  className,
}: NextActionCardProps) {
  return (
    <article className={joinClasses("ac-next-action-card", className)}>
      <div className="ac-next-action-card__copy">
        {eyebrow ? (
          <p className="ac-next-action-card__eyebrow">{eyebrow}</p>
        ) : null}
        <h2 className="ac-next-action-card__title">{title}</h2>
        {detail ? (
          <p className="ac-next-action-card__detail">{detail}</p>
        ) : null}
      </div>
      <div className="ac-next-action-card__action">{action}</div>
    </article>
  );
}

export type ModuleCardProps = {
  title: ReactNode;
  titleId?: string;
  position?: ReactNode;
  status?: ReactNode;
  header?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  className?: string;
};

/** Shared module container; interactive expansion remains route-owned. */
export function ModuleCard({
  title,
  titleId,
  position,
  status,
  header,
  children,
  footer,
  className,
}: ModuleCardProps) {
  return (
    <article
      className={joinClasses("ac-module-card", className)}
      aria-labelledby={titleId}
    >
      <div className="ac-module-card__header">
        {header ?? (
          <div className="ac-module-card__header-content">
            <div>
              {position ? (
                <p className="ac-module-card__position">{position}</p>
              ) : null}
              <h2 id={titleId}>{title}</h2>
            </div>
            {status ? (
              <div className="ac-module-card__status">{status}</div>
            ) : null}
          </div>
        )}
      </div>
      {children ? <div className="ac-module-card__body">{children}</div> : null}
      {footer ? <div className="ac-module-card__footer">{footer}</div> : null}
    </article>
  );
}

export type ActivityRowProps = {
  position: ReactNode;
  icon?: ReactNode;
  eyebrow?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  status?: ReactNode;
  action?: ReactNode;
  href?: string;
  disabled?: boolean;
  ariaLabel?: string;
  className?: string;
};

/** Ordered activity row with an explicit non-navigable state boundary. */
export function ActivityRow({
  position,
  icon,
  eyebrow,
  title,
  description,
  status,
  action,
  href,
  disabled = false,
  ariaLabel,
  className,
}: ActivityRowProps) {
  const content = (
    <>
      <span className="ac-activity-row__position">{position}</span>
      {icon ? <span className="ac-activity-row__icon">{icon}</span> : null}
      <span className="ac-activity-row__copy">
        {eyebrow ? (
          <span className="ac-activity-row__eyebrow">{eyebrow}</span>
        ) : null}
        <strong className="ac-activity-row__title">{title}</strong>
        {description ? (
          <span className="ac-activity-row__description">{description}</span>
        ) : null}
      </span>
      {status || action ? (
        <span className="ac-activity-row__actions">
          {status ? (
            <span className="ac-activity-row__status">{status}</span>
          ) : null}
          {action ? (
            <span className="ac-activity-row__action">{action}</span>
          ) : null}
        </span>
      ) : null}
    </>
  );

  return (
    <li
      className={joinClasses(
        "ac-activity-row",
        disabled ? "is-disabled" : undefined,
        className,
      )}
    >
      {href && !disabled && !action ? (
        <a href={href} aria-label={ariaLabel}>
          {content}
        </a>
      ) : (
        <div
          role={ariaLabel ? "group" : undefined}
          aria-label={ariaLabel}
          aria-disabled={disabled || undefined}
        >
          {content}
        </div>
      )}
    </li>
  );
}
