"use client";
import { usePathname } from "next/navigation";
import { RouteLoading } from "../shell/route-loading";
export default function Loading() {
  return <RouteLoading path={usePathname() ?? "/home"} />;
}
