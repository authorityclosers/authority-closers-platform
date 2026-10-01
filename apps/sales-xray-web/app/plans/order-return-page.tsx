"use client";

import { useSearchParams } from "next/navigation";

import { OrderReturn } from "./order-return";

export function OrderReturnPage() {
  const params = useSearchParams();
  return <OrderReturn orderId={params.get("order")} />;
}
