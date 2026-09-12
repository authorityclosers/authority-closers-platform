/** Immutable published copy. Change the version when either policy or consent changes. */
export const LEARNER_POLICY_VERSION = "ac-learner-terms-privacy-2026-09-13-v1";
export const LEARNER_POLICY_EFFECTIVE_DATE = "13 September 2026";
export const LEARNER_POLICY_CONTACT = "admin@authorityclosers.com";
export const LEARNER_CONSENT_COPY = {
  beforeTerms: "I am 18 or older and agree to the ",
  beforePrivacy: ". I have read the ",
  afterPrivacy:
    " and consent to the processing needed for my account, learning and essential service emails. This does not include marketing messages or WhatsApp automation.",
} as const;

export const LEARNER_TERMS = [
  {
    heading: "Using Authority Closers",
    paragraphs: [
      "These terms apply to the Authority Closers learning application, its free course and enabled practice features. Authority Closers is the service name. Contact us at admin@authorityclosers.com about access, these terms or a complaint. By creating an account, you agree to these terms and the processing described in the Privacy notice.",
      "The service is for adults aged 18 or older. Use accurate account information and your own authorized identity. Keep passwords and session access private. Tell us promptly if someone else may have accessed your account. An age confirmation is your declaration, not independent age verification.",
    ],
  },
  {
    heading: "Free access and learning outcomes",
    paragraphs: [
      "The published Free Course has no course fee. Account creation and course enrollment are separate steps. Access, available content and progress are shown in your account. These terms do not create a paid subscription, recurring charge or obligation to buy another service. Any future paid offer must disclose its own price, access conditions and applicable cancellation or refund terms before purchase.",
      "Course content and practice support learning. They do not guarantee employment, income, sales results, professional accreditation or any particular outcome. A completion record reflects the stated course requirements; it is not a guarantee of competence or a professional licence. Practice points and leaderboard positions are not official skill assessments.",
    ],
  },
  {
    heading: "Your work and our materials",
    paragraphs: [
      "Authority Closers and its licensors retain their rights in the platform and course materials. You may use material made available to your account for your personal learning. Do not resell, republish, redistribute or bypass access controls for those materials without permission, except where the law permits it.",
      "You retain the rights you hold in your submitted work. You give Authority Closers permission to store, display to you and authorized operators, process and back up that work as needed to provide learning, requested support and the features you choose. This does not authorize using your identity or private work as a public endorsement. Do not submit someone else's confidential information, personal data or recordings without the necessary authority and an expressly enabled, appropriate workflow.",
    ],
  },
  {
    heading: "Acceptable use",
    paragraphs: [
      "Do not impersonate another person, share accounts, harass others, submit unlawful content or malware, interfere with the service, access another person's records, manipulate progress or rewards, or defeat security and usage controls. Report suspected vulnerabilities privately through our contact address. Do not test them against other users or data you are not authorized to access.",
    ],
  },
  {
    heading: "Service messages and optional participation",
    paragraphs: [
      "We use essential email for account verification, security, password recovery and course-access administration. Registration does not subscribe you to promotional campaigns or WhatsApp automation. Optional participation, such as an enabled academy leaderboard, requires its own choice. Review the visibility described in the Privacy notice before opting in.",
    ],
  },
  {
    heading: "Availability, changes and account restrictions",
    paragraphs: [
      "Features and content may change, and interruptions can occur. A save, submission or completion is confirmed only when the service reports it as accepted. Keep a recovery copy of important unsent work where the application offers one. Contact support if your access or recorded progress appears incorrect.",
      "We may restrict access when reasonably necessary to address misuse, security, legal obligations or a material breach of these terms. Where appropriate, we will explain the restriction and how to request review. You may stop using the service and request account closure through the Privacy contact. Changes to access do not authorize us to silently rewrite the history of your accepted work.",
    ],
  },
  {
    heading: "Your legal rights and resolving concerns",
    paragraphs: [
      "Nothing in these terms excludes rights or remedies that applicable law does not allow us to exclude, or limits liability that cannot lawfully be limited. We do not require you to waive a valid consumer or privacy complaint. Contact admin@authorityclosers.com with the issue and relevant account details, without sending passwords or sensitive documents unnecessarily. You retain access to the courts, regulators and other remedies available under applicable law.",
    ],
  },
  {
    heading: "Updates to these terms",
    paragraphs: [
      "The effective date and document version identify this copy. We will publish updates here and request a new acknowledgment or consent when required for a material change. A later version does not retrospectively change what you previously agreed to or permit an undisclosed new use of your data.",
    ],
  },
] as const;

export const LEARNER_PRIVACY = [
  {
    heading: "Who this notice covers",
    paragraphs: [
      "This notice explains how Authority Closers handles personal data in its learning application. Our privacy and account-support contact is admin@authorityclosers.com. It covers the features described below when you use them; it is not permission to activate unrelated future services. The application is intended for people aged 18 or older. Contact us if you believe a child has registered.",
    ],
  },
  {
    heading: "Account information and its purpose",
    paragraphs: [
      "Email/password registration collects your first name, email address, contact number, password, age-and-terms declaration and consent version. We use these to create and protect your account, verify email, manage access and respond to support requests. Passwords are stored as salted password hashes, not plain text. The contact number is retained in your registration profile; it is not used for automated WhatsApp or promotional messaging.",
      "If you choose Google sign-in, we receive the Google account identifier and basic profile information, including verified email and display name, needed to authenticate or link your identity. Authority Closers does not receive your Google password. Google handles its own sign-in interaction under its policies. We record session and security information, which can include IP address, browser/device details, timestamps, selected organization context and account actions, to protect access and investigate incidents.",
    ],
  },
  {
    heading: "Learning, profile and support data",
    paragraphs: [
      "We process enrollment, course and content versions, saved drafts, submitted responses, watched-video evidence, progress and any issued completion records to deliver the course and resume your work. Optional onboarding answers describe your experience, goals, practice context and available time. Profile information can include a chosen username and an uploaded profile image. Provide only information you want to use for these features.",
      "Enabled practice features store your attempts, results and earned points. Technical logs help us investigate failures. Product-use analytics operate only where enabled with the required consent and retention controls; they do not determine your access or course completion. Support requests and authorized operational actions may be retained with audit records so account or learning corrections can be explained. Authorized staff can access the information needed for their assigned support, content or review responsibilities.",
    ],
  },
  {
    heading: "Optional leaderboard visibility",
    paragraphs: [
      "Leaderboard participation is off by default. If you opt in to an enabled academy leaderboard, other authorized learners in that academy can see your chosen username, rank and confirmed practice-point total. Your email address is not a leaderboard display name. You can change the participation setting in your profile. Private course responses are not published by opting in.",
    ],
  },
  {
    heading: "Service providers and disclosures",
    paragraphs: [
      "Service providers support hosting, network delivery and security, storage and backups, email delivery, and Google authentication when selected. They receive the data needed for their function; for example, an email service handles the destination address and message, and hosting or delivery services handle requests and stored content. Authorized administrators and providers may process data in locations different from yours. We restrict access according to the service provider's role and applicable law; we do not promise that every copy stays in a particular country.",
      "We do not sell personal data or use this registration consent for advertising profiles. We may disclose information when required by law, to respond to a valid legal request or to protect the service and people's rights. A future payment, call-recording or external AI feature requires its own clear disclosures and any required permission before processing. This release does not authorize external AI processing of real conversations or autonomous official scoring.",
    ],
  },
  {
    heading: "Cookies and recovery on your device",
    paragraphs: [
      "Essential cookies maintain secure sessions and authentication. Browser storage can retain preferences, supported offline course views and a local recovery copy of supported unfinished work. Supported activity and onboarding recovery copies expire seven days after the last local save; expiry is checked when the application reads them. Offline course copies have a separate seven-day expiry. These browser copies are not all encrypted and may remain until the application or browser removes them. Avoid shared devices, use the application's sign-out control and clear site data when appropriate. Clearing browser data can remove work that has not reached the server.",
    ],
  },
  {
    heading: "Retention and protection",
    paragraphs: [
      "We retain account and learning information for the purposes described here while it is needed to operate your account and course, provide support, protect the service or meet legal obligations. Retention depends on the record and the reason it is needed. Backup, security and audit records may remain after an account-closure request and are restricted to their continuing purpose. We do not promise immediate deletion from every backup or automatic erasure on a fixed date.",
      "We use authentication, access controls, protected transport and operational safeguards to reduce unauthorized access. No service can guarantee absolute security. Report a suspected account or privacy incident promptly, and do not send passwords or unnecessary sensitive information in a support message.",
    ],
  },
  {
    heading: "Your choices and privacy requests",
    paragraphs: [
      "You can edit supported profile and participation settings in the application, skip optional onboarding and request account closure. For access to your personal data, correction, deletion, withdrawal of consent or a privacy grievance, email admin@authorityclosers.com. Tell us the account address and request; we may need to verify that it is yours. You can also ask for help understanding this notice.",
      "We review requests under applicable law, explain the outcome and any information that must be retained, and provide a way to follow up. Withdrawing processing necessary for an account or feature may mean we cannot continue providing it. A request does not erase lawful security or audit history automatically. You retain the right to raise concerns with an applicable regulator or other authority; this notice does not waive that right.",
    ],
  },
  {
    heading: "Changes and consent records",
    paragraphs: [
      "We identify this notice by its effective date and version and record the version associated with account registration. If a material change requires new consent, we will ask before applying that new use. We do not replace an earlier consent record with a later version simply because this page changes. Essential account email consent is separate from any future marketing choice.",
    ],
  },
] as const;
