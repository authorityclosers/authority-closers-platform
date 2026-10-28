"use client";
import Link from "next/link";
import { Empty } from "@ac/ui/kit";
import { Compass } from "lucide-react";
export default function NotFound() {
  return (
    <main id="main-content">
      <Empty
        link={Link}
        icon={Compass}
        title="We couldn't find that page"
        text="Choose Today to keep learning."
        action={{ href: "/home", label: "Go to Today" }}
      />
    </main>
  );
}
