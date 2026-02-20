"use client";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface RoleBadgeProps {
  role: "admin" | "reviewer" | "user";
  className?: string;
}

export function RoleBadge({ role, className }: RoleBadgeProps) {
  const variants = {
    admin: "bg-primary/20 text-primary border-primary/30",
    reviewer: "bg-blue-500/20 text-blue-400 border-blue-500/30",
    user: "bg-zinc-500/20 text-zinc-400 border-zinc-500/30",
  };

  const labels = {
    admin: "Admin",
    reviewer: "Reviewer",
    user: "User",
  };

  return (
    <Badge
      variant="outline"
      className={cn(variants[role], className)}
    >
      {labels[role]}
    </Badge>
  );
}
