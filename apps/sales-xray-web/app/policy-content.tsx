import Link from "next/link";

import { PolicyFooter } from "./policy-footer";
import { PricingCatalogue } from "./pricing-catalogue";
import type { Plan } from "./billing/contract";
import styles from "./policy-pages.module.css";

export type PolicySlug =
  | "pricing"
  | "terms"
  | "privacy"
  | "refunds"
  | "delivery"
  | "contact";

const TITLES: Record<PolicySlug, string> = {
  pricing: "Pricing",
  terms: "Terms of service",
  privacy: "Privacy policy",
  refunds: "Refund and cancellation policy",
  delivery: "Delivery policy",
  contact: "Contact us",
};

type Section = {
  title: string;
  paragraphs?: string[];
  bullets?: string[];
};

const SECTIONS: Partial<Record<PolicySlug, Section[]>> = {
  delivery: [
    {
      title: "Online service",
      paragraphs: [
        "Sales Xray is an online software service. Nothing is shipped.",
        "Your plan and analysis minutes are added to your account after our server receives payment confirmation from Razorpay.",
        "You use the service in your browser at the Sales Xray website. Reports are delivered in your account, and you can download them where your plan allows.",
        "If your plan minutes do not appear after a successful payment, email us with your order number so we can investigate.",
      ],
    },
  ],
  refunds: [
    {
      title: "Cancellation",
      paragraphs: [
        "You can cancel at any time to stop the next renewal. Your plan stays active until the end of the period you have paid for. We do not charge a cancellation fee.",
      ],
    },
    {
      title: "Subscription refunds",
      paragraphs: [
        "If you ask within 7 days of a new subscription payment and have not used any minutes from it, we refund the full amount.",
        "After you use minutes, that period's payment is not refundable. Unused minutes do not turn into money.",
      ],
    },
    {
      title: "Top-up refunds",
      paragraphs: [
        "Top-up packs are refundable within 7 days only if none of the pack's minutes have been used.",
      ],
    },
    {
      title: "Failed, duplicate, or incorrect charges",
      paragraphs: [
        "Failed, duplicate or wrongly charged payments are refunded in full. To report a problem, email marketing@estateautopilots.com from your account email and include the order number.",
      ],
    },
    {
      title: "How refunds are paid",
      paragraphs: [
        "Refunds are paid to the original payment method through Razorpay. The provider and your bank control when the credit appears.",
      ],
    },
    {
      title: "How to ask",
      paragraphs: [
        "Email marketing@estateautopilots.com from your account email and include your order number.",
      ],
    },
    {
      title: "Organisation plans",
      paragraphs: [
        "Only the organisation owner can cancel or ask for a refund.",
      ],
    },
  ],
  terms: [
    {
      title: "1. Who we are",
      paragraphs: [
        'Sales Xray is provided by Vikriya Solutions LLP, trading as Estate Autopilots, Pune, India ("we"). By creating an account or paying for a plan, you agree to these terms.',
      ],
    },
    {
      title: "2. The service",
      paragraphs: [
        "Sales Xray analyses sales-call recordings that you upload and produces written reports and coaching suggestions. Reports use automated analysis and may contain mistakes. Use them as guidance, not as the only basis for employment, legal or financial decisions.",
      ],
    },
    {
      title: "3. Your account",
      paragraphs: [
        "Keep your sign-in secure. You are responsible for activity in your account. Organisation owners decide who joins their organisation and what members can see.",
      ],
    },
    {
      title: "4. Recordings and consent",
      paragraphs: [
        "Upload only recordings you are allowed to use. You must have every participant's consent to record and analyse the call, as the law that applies to you requires. Do not upload recordings of minors or special-category personal data unless the law allows it.",
      ],
    },
    {
      title: "5. Acceptable use",
      paragraphs: [
        "Do not misuse the service, try to break its security, resell it without our written agreement, or upload unlawful content.",
      ],
    },
    {
      title: "6. Plans and payment",
      bullets: [
        "Plan prices, billing intervals, and included details are shown in the current catalogue and at checkout. Review the amount shown before you confirm payment.",
        "Monthly and yearly subscriptions continue under the payment authorization and provider rules for the selected plan. A later charge may require approval from your bank or payment method. We do not promise a separate Sales Xray reminder before each renewal.",
        "You can cancel at any time to stop the next renewal. Your current paid period remains active until it ends.",
        "Usage is based on the duration processed for each analysed recording. Minutes expire or roll over as shown in the plan details.",
        "Plan payments use Razorpay hosted checkout. Razorpay handles payment credentials entered there. Sales Xray receives payment status and transaction references needed to provide the service, not complete card credentials.",
      ],
    },
    {
      title: "7. Cancellation and refunds",
      paragraphs: ["See the Refund and cancellation policy at /refunds."],
    },
    {
      title: "8. Your content",
      paragraphs: [
        "You own your recordings and reports. We use them to provide the service for the retention period shown in the applicable plan and processing notice. You may request deletion from your account. A deletion request queues removal from active Sales Xray stores. Audit records remain, and this process does not delete backups or provider-held copies; separate retention periods for those copies are not stated here.",
      ],
    },
    {
      title: "9. Our service",
      paragraphs: [
        "The software, report designs and analysis methods belong to us. We may change features. We will tell you before a change that reduces what a paid plan includes.",
      ],
    },
    {
      title: "10. Liability",
      paragraphs: [
        'The service is provided "as is". To the extent the law allows, our total liability for any claim is limited to the amount you paid us in the 3 months before the claim. We are not liable for indirect or consequential loss.',
      ],
    },
    {
      title: "11. Ending",
      paragraphs: [
        "You may close your account at any time. We may suspend accounts that break these terms, after notice where reasonable.",
      ],
    },
    {
      title: "12. Law",
      paragraphs: [
        "These terms are governed by the laws of India. The courts at Pune, Maharashtra have jurisdiction.",
      ],
    },
    {
      title: "13. Changes and contact",
      paragraphs: [
        "We may update these terms and will show the date of the latest version. For questions, see /contact.",
      ],
    },
  ],
  privacy: [
    {
      title: "Who is responsible",
      paragraphs: [
        "Sales Xray is a product of Authority Closers. Subscriptions are sold and invoiced by Vikriya Solutions LLP, trading as Estate Autopilots, Pune. Contact: marketing@estateautopilots.com.",
      ],
    },
    {
      title: "What we collect",
      bullets: [
        "Account details: name, email address, and mobile number.",
        "Your recordings, transcripts, and reports.",
        "Usage and billing records, including plan, minutes, and orders.",
        "If you use Google sign-in, the Google account identifier and basic profile information needed to authenticate or link your identity. We do not receive your Google password. We keep your first and last name, language setting, Google Workspace email domain when supplied, and a small copy of your Google profile photo.",
        "Razorpay processes payment credentials entered in its hosted checkout. Sales Xray receives payment status and transaction references, not complete card credentials.",
      ],
    },
    {
      title: "Why we use it",
      bullets: [
        "To provide analysis and reports.",
        "To run your account, plan, and billing.",
        "To keep the service secure.",
        "To meet legal and tax duties.",
      ],
    },
    {
      title: "Who we share with",
      bullets: [
        "Hosting and analysis service providers needed to operate Sales Xray. Before an analysis starts, the processing plan shows the analysis provider and purpose and asks you to accept that processing.",
        "Razorpay for payments made through its hosted checkout.",
        "Sales Xray does not use your recordings or reports to target advertising.",
      ],
    },
    {
      title: "How long we keep it",
      paragraphs: [
        "The plan and accepted processing plan show the retention period for recordings and reports. You may request deletion from your account. A deletion request queues removal from active Sales Xray stores. Audit records remain. This deletion path does not delete backups or provider-held copies; their separate retention periods are not stated here. Transaction and audit records may remain after account closure.",
      ],
    },
    {
      title: "Your rights",
      paragraphs: [
        "You may contact us about access, correction, or deletion of your personal data, or to raise a grievance. Email marketing@estateautopilots.com. We handle requests under applicable law.",
      ],
    },
    {
      title: "People in your calls",
      paragraphs: [
        "You confirm that you have the required consent from people in your calls, as set out in section 4 of the Terms of service.",
      ],
    },
  ],
};

function ContentSections({
  slug,
}: {
  slug: Exclude<PolicySlug, "pricing" | "contact">;
}) {
  return (
    <div className={styles.sections}>
      {(SECTIONS[slug] ?? []).map((section) => (
        <section className={styles.section} key={section.title}>
          <h2>{section.title}</h2>
          {section.bullets ? (
            <ul>
              {section.bullets.map((bullet) => (
                <li key={bullet}>{bullet}</li>
              ))}
            </ul>
          ) : null}
          {section.paragraphs?.map((paragraph) => (
            <p key={paragraph}>{paragraph}</p>
          ))}
        </section>
      ))}
    </div>
  );
}

function ContactDetails() {
  return (
    <div className={styles.sections}>
      <section className={styles.section}>
        <h2>Sales Xray and seller</h2>
        <p>
          Sales Xray is a product of Authority Closers. Subscriptions are sold
          and invoiced by Vikriya Solutions LLP, trading as Estate Autopilots.
        </p>
        <dl className={styles.details}>
          <div>
            <dt>Registered office</dt>
            <dd>
              Office 102, Manorath Apartment, Plot No. 26, Sr. No. 94, Lane No.
              10, Bhusari Colony (Right), Near Kothrud Depot, Kothrud, Pune
              411038, Maharashtra, India.
            </dd>
          </div>
          <div>
            <dt>Email</dt>
            <dd>
              <a href="mailto:marketing@estateautopilots.com">
                marketing@estateautopilots.com
              </a>
            </dd>
          </div>
          <div>
            <dt>Phone</dt>
            <dd>
              <a href="tel:+919156281682">+91 91562 81682</a>
              {" · "}
              <a href="tel:+918668515406">+91 86685 15406</a>
            </dd>
          </div>
        </dl>
        <p>
          For account, payment, refund, or privacy requests, email us with your
          account email and order number where relevant.
        </p>
      </section>
    </div>
  );
}

export function PolicyPage({
  slug,
  pricingPlans,
}: {
  slug: PolicySlug;
  pricingPlans?: Plan[];
}) {
  return (
    <main className={styles.page} data-policy-page={slug}>
      <header className={styles.top}>
        <Link className={styles.brand} href="/">
          Sales Xray
        </Link>
      </header>
      <article className={styles.content}>
        <p className={styles.eyebrow}>Sales Xray</p>
        <h1>{TITLES[slug]}</h1>
        <p className={styles.updated}>
          Last updated <time dateTime="2026-10-03">3 October 2026</time>
        </p>
        {slug === "pricing" ? (
          <>
            <p className={styles.intro}>
              Plan details and prices below come from the current catalogue.
              Prices are in Indian rupees.
            </p>
            <PricingCatalogue initialPlans={pricingPlans} />
          </>
        ) : slug === "contact" ? (
          <ContactDetails />
        ) : (
          <ContentSections slug={slug} />
        )}
      </article>
      <PolicyFooter />
    </main>
  );
}
