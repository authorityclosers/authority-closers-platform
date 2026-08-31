import { ArrowLeft, Check, KeyRound } from "lucide-react";
import Link from "next/link";
import Image from "next/image";
import type { ReactNode } from "react";

import { BrandMark } from "@ac/ui";

import { ROUTES } from "../lib/routes";

type AuthFlowPageProps = {
  eyebrow: string;
  heading: string;
  emphasis: string;
  copy: string;
  backHref?: string;
  backLabel?: string;
  children: ReactNode;
};

export function AuthFlowPage({
  eyebrow,
  heading,
  emphasis,
  copy,
  backHref = ROUTES.login,
  backLabel = "Back to sign in",
  children,
}: AuthFlowPageProps) {
  return (
    <div className="site-frame site-frame--auth">
      <a className="skip-link" href="#main-content">
        Skip to authentication
      </a>
      <main id="main-content" className="auth-main clarity-auth-main">
        <div className="auth-layout clarity-auth-layout">
          <div className="auth-context clarity-auth-context">
            <Link className="text-link clarity-auth-back" href={backHref}>
              <ArrowLeft size={15} aria-hidden="true" /> {backLabel}
            </Link>
            <div className="clarity-auth-brand-panel">
              <Image
                className="clarity-auth-brand-media"
                src="/auth-workspace-lake-v1.png"
                alt="A quiet workspace overlooking a mountain lake"
                width={1122}
                height={1402}
                priority
              />
              <div className="clarity-auth-brand-kicker">
                <span className="clarity-auth-brand-mark">
                  <BrandMark aria-hidden="true" />
                </span>
                <span>Authority LMS v0.1</span>
              </div>
              <p className="eyebrow">
                <span aria-hidden="true" /> {eyebrow}
              </p>
              <h1>
                {heading} <br />
                <em>{emphasis}</em>
              </h1>
              <p className="auth-context__copy">{copy}</p>
              <ul
                className="clarity-auth-proof"
                aria-label="Learner account benefits"
              >
                <li>
                  <Check size={15} aria-hidden="true" />
                  <span>One verified identity for your learning record</span>
                </li>
                <li>
                  <Check size={15} aria-hidden="true" />
                  <span>
                    Progress and workbook evidence stay server-authoritative
                  </span>
                </li>
                <li>
                  <Check size={15} aria-hidden="true" />
                  <span>Secure recovery when you need to return</span>
                </li>
              </ul>
              <div className="auth-principle clarity-auth-principle">
                <KeyRound size={18} aria-hidden="true" />
                <span>Opaque sessions · bounded learner identity</span>
              </div>
            </div>
          </div>
          <div className="auth-panel clarity-auth-panel">{children}</div>
        </div>
      </main>
    </div>
  );
}
