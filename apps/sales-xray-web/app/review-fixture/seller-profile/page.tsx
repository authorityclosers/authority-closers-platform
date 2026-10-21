import { notFound } from "next/navigation";

import { SellerProfilePreview } from "./seller-profile-preview";

/** Local visual review of a salesperson's profile with fictional people. Never in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <SellerProfilePreview />;
}
