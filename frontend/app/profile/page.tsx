"use client";

import { useState } from "react";
import { AppLayout } from "@/components/shared/AppLayout";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { RoleBadge } from "@/components/shared/RoleBadge";
import { useAuth } from "@/lib/auth/AuthContext";
import {
  User,
  Mail,
  Building2,
  ShieldCheck,
  Clock,
  KeyRound,
  ArrowLeft,
} from "lucide-react";
import { useRouter } from "next/navigation";

function getInitials(name: string): string {
  return name
    .split(" ")
    .map((n) => n[0])
    .join("")
    .toUpperCase();
}

function formatLastLogin(value: string | null): string {
  if (!value) return "Never";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unknown";
  return new Intl.DateTimeFormat("en-US", {
    month: "long",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

interface ProfileFieldProps {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
}

function ProfileField({ icon, label, value }: ProfileFieldProps) {
  return (
    <div className="flex items-start gap-4 py-4">
      <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 border border-primary/20">
        {icon}
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-0.5">
          {label}
        </p>
        <div className="text-sm font-medium text-foreground">{value}</div>
      </div>
    </div>
  );
}

export default function ProfilePage() {
  const { user } = useAuth();
  const router = useRouter();
  const [showPasswordPlaceholder, setShowPasswordPlaceholder] = useState(false);

  if (!user) return null;

  return (
    <AppLayout>
      <div className="flex-1 overflow-y-auto">
        {/* Page header */}
        <div className="border-b border-border px-6 py-4 bg-card/40 flex items-center gap-3">
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={() => router.back()}
            aria-label="Go back"
          >
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div>
            <h1 className="text-lg font-bold">My Profile</h1>
            <p className="text-xs text-muted-foreground">
              View and manage your account information
            </p>
          </div>
        </div>

        <div className="max-w-2xl mx-auto px-6 py-8 space-y-6">
          {/* Avatar + name hero */}
          <div className="flex flex-col items-center gap-4 py-6 rounded-xl border border-border bg-card/50">
            <Avatar className="h-24 w-24 border-4 border-primary/30 shadow-lg">
              <AvatarFallback className="bg-primary text-primary-foreground text-2xl font-bold">
                {getInitials(user.fullName)}
              </AvatarFallback>
            </Avatar>
            <div className="text-center">
              <h2 className="text-xl font-bold">{user.fullName}</h2>
              <p className="text-sm text-muted-foreground mt-0.5">
                @{user.username}
              </p>
              <div className="flex items-center justify-center gap-2 mt-2">
                <RoleBadge role={user.role} />
                <Badge
                  variant="outline"
                  className={
                    user.status === "active"
                      ? "border-green-500/40 text-green-500 bg-green-500/5 text-xs"
                      : "border-destructive/40 text-destructive text-xs"
                  }
                >
                  {user.status}
                </Badge>
              </div>
            </div>
          </div>

          {/* Profile details */}
          <div className="rounded-xl border border-border bg-card/50 px-6 divide-y divide-border">
            <ProfileField
              icon={<User className="h-4 w-4 text-primary" />}
              label="Full Name"
              value={user.fullName}
            />
            <ProfileField
              icon={<Mail className="h-4 w-4 text-primary" />}
              label="Email"
              value={user.email}
            />
            <ProfileField
              icon={<Building2 className="h-4 w-4 text-primary" />}
              label="Department"
              value={user.department || "—"}
            />
            <ProfileField
              icon={<ShieldCheck className="h-4 w-4 text-primary" />}
              label="Role"
              value={<RoleBadge role={user.role} />}
            />
            <ProfileField
              icon={<Clock className="h-4 w-4 text-primary" />}
              label="Last Login"
              value={formatLastLogin(user.lastLogin)}
            />
          </div>

          {/* Security section */}
          <div className="rounded-xl border border-border bg-card/50 px-6 py-5">
            <div className="flex items-center gap-2 mb-4">
              <KeyRound className="h-4 w-4 text-primary" />
              <h3 className="text-sm font-semibold">Security</h3>
            </div>
            <Separator className="mb-4" />

            {showPasswordPlaceholder ? (
              <div className="rounded-lg border border-border bg-muted/30 p-4 text-sm text-muted-foreground">
                <p className="font-medium text-foreground mb-1">
                  Password change
                </p>
                <p className="text-xs">
                  Password management requires backend integration. This feature
                  will be available once the profile API endpoint is connected.
                </p>
                <Button
                  variant="ghost"
                  size="sm"
                  className="mt-3 text-xs"
                  onClick={() => setShowPasswordPlaceholder(false)}
                >
                  Cancel
                </Button>
              </div>
            ) : (
              <Button
                variant="outline"
                size="sm"
                className="gap-2"
                onClick={() => setShowPasswordPlaceholder(true)}
              >
                <KeyRound className="h-3.5 w-3.5" />
                Change Password
              </Button>
            )}
          </div>

          <p className="text-center text-xs text-muted-foreground pb-4">
            To update your profile details, contact your system administrator.
          </p>
        </div>
      </div>
    </AppLayout>
  );
}
