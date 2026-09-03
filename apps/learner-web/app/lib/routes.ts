const routeSegment = (value: string) => encodeURIComponent(value);

export const ROUTES = {
  home: "/",
  privacy: "/privacy",
  terms: "/terms",
  login: "/login",
  register: "/register",
  forgotPassword: "/forgot-password",
  verifyEmail: "/verify-email",
  resetPassword: "/reset-password",
  callback: "/auth/callback",
  sessionExpired: "/session-expired",
  onboarding: "/onboarding",
  learnerHome: "/home",
  dashboard: "/home",
  learning: "/learning",
  myLearning: "/learning",
  discover: "/discover",
  progress: "/progress",
  calendar: "/calendar",
  notifications: "/notifications",
  profile: "/profile",
  settings: "/settings",
  practice: "/home#practice",
  programDetail: (slug: string) => `/programs/${routeSegment(slug)}`,
  programLearning: (slug: string) => `/learn/${routeSegment(slug)}`,
  module: (slug: string, moduleId: string) =>
    `/learn/${routeSegment(slug)}/module/${routeSegment(moduleId)}`,
  activity: (activityId: string) => `/activity/${routeSegment(activityId)}`,
  completion: (slug: string) => `/learn/${routeSegment(slug)}/complete`,
  certificate: (certificateId: string) =>
    `/certificates/${routeSegment(certificateId)}`,
} as const;
