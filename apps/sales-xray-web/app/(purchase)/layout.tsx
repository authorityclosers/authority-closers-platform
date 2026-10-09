import { AppSession } from "../app-session";
export default function PurchaseLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <AppSession>{children}</AppSession>;
}
