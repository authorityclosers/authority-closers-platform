import "../../../sales-xray-web/app/styles.css";

export default function SalesXrayLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return <div className="sales-xray-route">{children}</div>;
}
