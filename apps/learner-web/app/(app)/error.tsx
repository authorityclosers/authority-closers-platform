"use client";
import { Empty } from "@ac/ui/kit";
import { CloudOff } from "lucide-react";
export default function ErrorPage({ reset }: { reset: () => void }) {
  return (
    <Empty
      icon={CloudOff}
      title="This page couldn't load"
      text="Please try again. Your saved work is still here."
      action={{ label: "Retry", onClick: reset }}
    />
  );
}
