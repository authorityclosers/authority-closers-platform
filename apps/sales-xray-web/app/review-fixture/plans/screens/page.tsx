import { notFound } from "next/navigation";
import { PurchaseScreensFixture } from "./purchase-screens-fixture";

export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <PurchaseScreensFixture />;
}
