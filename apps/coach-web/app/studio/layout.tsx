import { CoachShell } from "../components/coach-shell";
export default function StudioLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <CoachShell>{children}</CoachShell>;
}
