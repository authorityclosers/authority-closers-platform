import { ArrowLeft, ArrowUpRight, BookOpen, Home, Medal } from "lucide-react";
import Link from "next/link";

import { BrandMark } from "@ac/ui";

import { ROUTES } from "../lib/routes";

type PublicCurrent = "home" | "program";
type LearnerCurrent = "home" | "course" | "certificate";

function BrandLink({ href = ROUTES.home }: { href?: string }) {
  return (
    <Link className="brand" href={href} aria-label="Authority Closers home">
      <BrandMark className="brand-mark" />
      <span>Authority Closers</span>
    </Link>
  );
}

export function PublicShell({
  children,
  current = "home",
}: {
  children: React.ReactNode;
  current?: PublicCurrent;
}) {
  return (
    <div className="site-frame">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <header className="site-header">
        <div className="site-header__inner">
          <BrandLink />
          <nav className="public-nav" aria-label="Public navigation">
            <Link
              href="/#method"
              aria-current={current === "home" ? "page" : undefined}
            >
              The method
            </Link>
            <Link href={ROUTES.login}>Sign in</Link>
            <Link
              className="button button--small button--outline"
              href={ROUTES.programDetail("free-course")}
            >
              Explore the course <ArrowUpRight size={15} aria-hidden="true" />
            </Link>
          </nav>
        </div>
      </header>
      {children}
      <footer className="site-footer">
        <div className="site-footer__inner">
          <BrandLink />
          <p>Preview surface · learning primitives for deliberate practice.</p>
          <Link href={ROUTES.login}>
            Sign in <ArrowUpRight size={14} aria-hidden="true" />
          </Link>
        </div>
      </footer>
    </div>
  );
}

function LearnerNavLink({
  href,
  label,
  current,
  icon,
}: {
  href: string;
  label: string;
  current: boolean;
  icon: React.ReactNode;
}) {
  return (
    <Link
      className={`learner-nav__link${current ? " is-current" : ""}`}
      href={href}
      aria-current={current ? "page" : undefined}
    >
      {icon}
      <span>{label}</span>
    </Link>
  );
}

export function LearnerShell({
  children,
  current = "home",
}: {
  children: React.ReactNode;
  current?: LearnerCurrent;
}) {
  return (
    <div className="site-frame site-frame--learner">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <header className="learner-header">
        <div className="learner-header__inner">
          <BrandLink href={ROUTES.learnerHome} />
          <nav className="learner-nav" aria-label="Learner navigation">
            <LearnerNavLink
              href={ROUTES.learnerHome}
              label="Home"
              current={current === "home"}
              icon={<Home size={17} aria-hidden="true" />}
            />
            <LearnerNavLink
              href={ROUTES.programLearning("free-course")}
              label="Course"
              current={current === "course"}
              icon={<BookOpen size={17} aria-hidden="true" />}
            />
            <LearnerNavLink
              href={ROUTES.certificate("preview-certificate")}
              label="Certificate"
              current={current === "certificate"}
              icon={<Medal size={17} aria-hidden="true" />}
            />
          </nav>
          <div className="learner-identity" aria-label="Current identity">
            <span className="learner-identity__initials" aria-hidden="true">
              PV
            </span>
            <span className="learner-identity__name">Preview identity</span>
          </div>
        </div>
      </header>
      {children}
    </div>
  );
}

export function Breadcrumbs({
  items,
}: {
  items: Array<{ label: string; href?: string }>;
}) {
  return (
    <nav className="breadcrumbs" aria-label="Breadcrumb">
      <ol>
        <li>
          <Link href={ROUTES.learnerHome} aria-label="Back to learner home">
            <ArrowLeft size={14} aria-hidden="true" />
            <span>Home</span>
          </Link>
        </li>
        {items.map((item, index) => (
          <li key={item.label}>
            <span className="breadcrumbs__separator" aria-hidden="true">
              /
            </span>
            {item.href ? (
              <Link href={item.href}>{item.label}</Link>
            ) : (
              <span
                aria-current={index === items.length - 1 ? "page" : undefined}
              >
                {item.label}
              </span>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}
