export const ROUTES = {
  home: "/",
  login: "/login",
  callback: "/auth/callback",
  onboarding: "/onboarding",
  learnerHome: "/home",
  programDetail: (slug: string) => `/programs/${slug}`,
  programLearning: (slug: string) => `/learn/${slug}`,
  module: (slug: string, moduleId: string) =>
    `/learn/${slug}/module/${moduleId}`,
  activity: (activityId: string) => `/activity/${activityId}`,
  completion: (slug: string) => `/learn/${slug}/complete`,
  certificate: (certificateId: string) => `/certificates/${certificateId}`,
} as const;
