"use client";

/**
 * Users Administration Page
 *
 * Purpose:
 * - Displays user directory sourced from backend LDAP-backed endpoint.
 * - Supports role updates only; user creation is managed exclusively through LDAP.
 * - Provides quick team-level metrics (active users, role distribution).
 *
 * Data source model:
 * - Users are fetched from GET /api/v1/auth/admin/users on mount.
 * - Role changes are persisted via PATCH /api/v1/auth/admin/users/{id}/role.
 *
 * LDAP policy:
 * - No user creation from the PlantIQ web UI.
 * - No status toggling — account activation is managed in the identity directory.
 * - Only role assignment is writable from this page.
 *
 * Security note:
 * - Authoritative access control is enforced server-side.
 * - Backend rejects self-role-escalation with 403.
 */

import { useState, useEffect } from "react";
import { AppLayout } from "@/components/shared/AppLayout";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Users, Mail, Building2, Clock, ShieldCheck, User2, AlertCircle, Loader2 } from "lucide-react";
import { getAdminUsers, patchUserRole, ApiError } from "@/lib/api";
import type { User } from "@/types";

type Role = "admin" | "user";

function mapApiUserToUser(u: {
  id: string;
  username: string;
  email: string;
  full_name: string;
  role: string;
  department: string | null;
  status: string;
}): User {
  return {
    id: u.id,
    username: u.username,
    email: u.email,
    fullName: u.full_name,
    role: u.role as User["role"],
    department: u.department ?? "",
    status: u.status as "active" | "disabled",
    lastLogin: null,
  };
}

export default function UsersPage() {
  const [userList, setUserList] = useState<User[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  // Per-user role change error (keyed by user ID)
  const [roleErrors, setRoleErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    let cancelled = false;

    async function loadUsers() {
      setIsLoading(true);
      setFetchError(null);
      try {
        const response = await getAdminUsers();
        if (!cancelled) {
          setUserList(response.items.map(mapApiUserToUser));
        }
      } catch {
        if (!cancelled) {
          setFetchError("Failed to load users. Please refresh the page.");
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    loadUsers();
    return () => { cancelled = true; };
  }, []);

  const admins = userList.filter((u) => u.role === "admin");
  const users = userList.filter((u) => u.role === "user");
  const totalActive = userList.filter((u) => u.status === "active").length;

  async function changeRole(userId: string, newRole: Role) {
    // Capture previous role for rollback on error.
    const prevUser = userList.find((u) => u.id === userId);
    const prevRole = prevUser?.role as Role | undefined;

    // Optimistic update
    setUserList((prev) =>
      prev.map((u) => (u.id === userId ? { ...u, role: newRole } : u))
    );
    setRoleErrors((prev) => {
      const next = { ...prev };
      delete next[userId];
      return next;
    });

    try {
      await patchUserRole(userId, newRole);
    } catch (err) {
      // Revert optimistic update
      if (prevRole) {
        setUserList((prev) =>
          prev.map((u) => (u.id === userId ? { ...u, role: prevRole } : u))
        );
      }
      let message = "Role update failed. Please try again.";
      if (err instanceof ApiError) {
        if (err.status === 403) {
          message = "You cannot change your own role.";
        } else if (err.status === 404) {
          message = "User not found.";
        }
      }
      setRoleErrors((prev) => ({ ...prev, [userId]: message }));
    }
  }

  return (
    <AppLayout>
      <div className="flex-1 flex flex-col h-full min-h-0">
        {/* Header */}
        <div className="border-b border-border px-6 py-5 flex items-center justify-between bg-card/50">
          <div>
            <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
              <Users className="h-6 w-6 text-primary" />
              User Management
            </h1>
            <p className="text-sm text-muted-foreground mt-0.5">
              Manage role-based access for Cove Point LNG
            </p>
          </div>
        </div>


        <div className="flex-1 overflow-y-auto min-h-0">
          <div className="p-6 max-w-5xl mx-auto space-y-6">
            <Card className="p-4 border border-amber-400/30 bg-amber-400/5">
              <p className="text-sm font-semibold text-amber-300">Users are managed through the identity directory</p>
              <p className="text-xs text-muted-foreground mt-1">
                Accounts are provisioned and deactivated via LDAP. Only role assignments can be changed from this page.
                Upload and chat access remain governed by server-side scope rules.
              </p>
            </Card>

            {/* Fetch error */}
            {fetchError && (
              <Card className="p-4 border border-red-400/30 bg-red-400/5 flex items-center gap-3">
                <AlertCircle className="h-5 w-5 text-red-400 shrink-0" />
                <p className="text-sm text-red-400">{fetchError}</p>
              </Card>
            )}

            {/* Loading state */}
            {isLoading && (
              <div className="flex items-center justify-center py-12 text-muted-foreground gap-2">
                <Loader2 className="h-5 w-5 animate-spin" />
                <span className="text-sm">Loading users…</span>
              </div>
            )}

            {!isLoading && !fetchError && (
              <>
                {/* Role distribution stats */}
                <div className="grid grid-cols-3 gap-4">
                  {[
                    { label: "Admins", count: admins.length, color: "text-primary", bg: "bg-primary/10 border-primary/30", icon: <ShieldCheck className="h-5 w-5 text-primary" /> },
                    { label: "Users", count: users.length, color: "text-zinc-300", bg: "bg-zinc-400/10 border-zinc-400/30", icon: <User2 className="h-5 w-5 text-zinc-400" /> },
                    { label: "Active", count: totalActive, color: "text-green-400", bg: "bg-green-400/10 border-green-400/30", icon: <Users className="h-5 w-5 text-green-400" /> },
                  ].map(({ label, count, color, bg, icon }) => (
                    <Card key={label} className={`p-4 border ${bg}`}>
                      <div className="flex items-center gap-3">
                        <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-card border border-border shrink-0">
                          {icon}
                    </div>
                    <div>
                      <p className={`text-2xl font-bold leading-none ${color}`}>{count}</p>
                      <p className="text-xs text-muted-foreground mt-0.5">{label}</p>
                    </div>
                  </div>
                </Card>
              ))}
            </div>

            {/* Users table */}
            <Card className="overflow-hidden border-border">
              <div className="px-4 py-3 border-b border-border bg-muted/40">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                  All Users ({userList.length})
                </h2>
              </div>
              <Table>
                <TableHeader>
                  <TableRow className="bg-muted/30 hover:bg-muted/30 border-border">
                    <TableHead className="font-semibold text-foreground">User</TableHead>
                    <TableHead className="font-semibold text-foreground w-48">Role</TableHead>
                    <TableHead className="font-semibold text-foreground">Department</TableHead>
                    <TableHead className="font-semibold text-foreground">Last Login</TableHead>
                    <TableHead className="font-semibold text-foreground w-24 text-center">Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {userList.map((u) => (
                    <TableRow key={u.id} className={`border-border hover:bg-muted/20 transition-colors ${u.status === "disabled" ? "opacity-60" : ""}`}>
                      {/* User */}
                      <TableCell className="py-4">
                        <div className="flex items-center gap-3">
                          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-primary/10 border border-primary/20 shrink-0">
                            <span className="text-xs font-bold text-primary">
                              {u.fullName.split(" ").map((n) => n[0]).join("").toUpperCase()}
                            </span>
                          </div>
                          <div>
                            <p className="font-semibold text-sm">{u.fullName}</p>
                            <p className="text-xs text-muted-foreground flex items-center gap-1 mt-0.5">
                              <Mail className="h-2.5 w-2.5" />
                              {u.email}
                            </p>
                          </div>
                        </div>
                      </TableCell>

                      {/* Role — inline dropdown */}
                      <TableCell className="py-4">
                        <div className="space-y-1">
                          <Select
                            value={u.role === "admin" || u.role === "user" ? u.role : "user"}
                            onValueChange={(val) => changeRole(u.id, val as Role)}
                          >
                            <SelectTrigger className="h-8 text-xs w-[130px] bg-card border-border" aria-label={`Role for ${u.fullName}`}>
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="admin">
                                <span className="text-primary font-medium">Admin</span>
                              </SelectItem>
                              <SelectItem value="user">
                                <span className="text-zinc-300 font-medium">User</span>
                              </SelectItem>
                            </SelectContent>
                          </Select>
                          {roleErrors[u.id] && (
                            <p className="text-xs text-red-400 flex items-center gap-1">
                              <AlertCircle className="h-3 w-3 shrink-0" />
                              {roleErrors[u.id]}
                            </p>
                          )}
                        </div>
                      </TableCell>

                      {/* Department */}
                      <TableCell className="py-4">
                        <span className="text-sm flex items-center gap-1.5">
                          <Building2 className="h-3 w-3 text-muted-foreground shrink-0" />
                          {u.department}
                        </span>
                      </TableCell>

                      {/* Last login */}
                      <TableCell className="py-4">
                        <span className="text-xs text-muted-foreground flex items-center gap-1">
                          <Clock className="h-3 w-3 shrink-0" />
                          {u.lastLogin ? new Date(u.lastLogin).toLocaleDateString() : "Never"}
                        </span>
                      </TableCell>

                      {/* Status (read-only) */}
                      <TableCell className="py-4 text-center">
                        <Badge
                          variant="outline"
                          className={
                            u.status === "active"
                              ? "text-green-400 bg-green-400/10 border-green-400/30 text-xs"
                              : "text-zinc-500 bg-zinc-500/10 border-zinc-500/30 text-xs"
                          }
                        >
                          {u.status === "active" ? "Active" : "Disabled"}
                        </Badge>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Card>
          </>
          )}
          </div>
        </div>
      </div>
    </AppLayout>
  );
}

