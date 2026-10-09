import { AppSession } from "../app-session";
import { readSessionSeed } from "../session-server";
export default async function SessionLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <AppSession initial={await readSessionSeed()}>{children}</AppSession>;
}
