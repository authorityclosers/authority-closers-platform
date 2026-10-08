import { headers } from "next/headers";
import { notFound, redirect } from "next/navigation";
import Link from "next/link";
import { GetApps } from "./get-apps";
import { readDownloads } from "./downloads";
import { sessionStatus } from "./session";

export default async function GetAppsPage() {
  if (process.env.AC_SALES_XRAY_STATIC_PREVIEW === "1") notFound();
  const status = await sessionStatus((await headers()).get("cookie"));
  if (status === 401) redirect("/login?next=%2Fget-apps");
  if (status === 503)
    return (
      <main>
        <h1>Get the apps</h1>
        <p role="status">We couldn’t check your account. Please try again.</p>
        <Link href="/get-apps">Try again</Link>
      </main>
    );
  return <GetApps downloads={await readDownloads()} />;
}
