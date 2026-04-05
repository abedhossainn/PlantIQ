"use client";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface RoleBadgeProps {
  role: "admin" | "user";
  className?: string;
}

export function RoleBadge({ role, className }: RoleBadgeProps) {
  const variants = {
    admin: "bg-primary/20 text-primary border-primary/30",
    user: "bg-zinc-500/20 text-zinc-400 border-zinc-500/30",
  };

  const labels = {
    admin: "Admin",
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
