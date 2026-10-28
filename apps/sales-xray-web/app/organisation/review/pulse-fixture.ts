/** Browser-only fictional Pulse answers. No provider, credential or customer data is contacted. */
export function pulseFixture(connected: boolean, origin: string) {
  let linked = connected;
  let sharing = { directory: "read", photos: "off", signals: "off" };
  let invited = false;
  const state = () => ({
    schema: "sx-pulse/1",
    configured: true,
    issuer: "https://pulse.example.test",
    link: linked
      ? {
          status: "active",
          pulse_org_id: "fictional-org",
          pulse_org_name: "Sample Office",
          linked_at: "2026-10-28T10:00:00Z",
          linked_by: "Mira Fictional",
          scopes: ["openid", "pulse.org.read", "pulse.org.webhooks"],
          sharing,
          webhooks: true,
          last_sync_at: "2026-10-28T10:01:00Z",
          last_sync: { seen: 2, matched: 1, missing: 1 },
        }
      : null,
    members: linked
      ? [
          {
            id: "mira",
            name: "Mira Fictional",
            email: "mira@example.test",
            title: "Sales manager",
            team: "Sales",
            status: "active",
            person_id: "sample-mira",
            matched_by: "email",
            can_invite: false,
          },
          {
            id: "tali",
            name: "Tali Example",
            email: "tali@example.test",
            title: "Seller",
            team: "Sales",
            status: "active",
            person_id: null,
            matched_by: null,
            can_invite: !invited,
            invited_at: invited ? "2026-10-28T10:02:00Z" : null,
          },
        ]
      : [],
    pulse_access: [],
  });
  return (path: string, init?: RequestInit): unknown => {
    const base = "/v1/sales-xray/pulse";
    if (path === base) return state();
    if (path === `${base}/connect`)
      return { redirect_url: `${origin}/organisation/review/pulse-consent` };
    if (path === `${base}/sync`) return state();
    if (path === `${base}/sharing`) {
      sharing = { ...sharing, ...JSON.parse(String(init?.body ?? "{}")) };
      return state();
    }
    if (path === `${base}/invite`) {
      invited = true;
      return state();
    }
    if (path === `${base}/unlink`) {
      linked = false;
      return state();
    }
    if (path === `${base}/people`) return { people: {} };
    return undefined;
  };
}
