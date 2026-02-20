"use client";

import { useState, useEffect } from "react";
import { AppLayout } from "@/components/shared/AppLayout";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Users, UserPlus, Mail, Building2, Clock, ShieldCheck, User2, Eye } from "lucide-react";
import { mockUsers } from "@/lib/mock";
import { RoleBadge } from "@/components/shared/RoleBadge";
import type { User } from "@/types";

type Role = "admin" | "reviewer" | "user";

export default function UsersPage() {
  const [userList, setUserList] = useState<User[]>(mockUsers);
  const [changedRoles, setChangedRoles] = useState<Record<string, Role>>({});
  const [toggledStatuses, setToggledStatuses] = useState<Record<string, "active" | "disabled">>({});

  // Load persisted role / status overrides from localStorage on mount
  useEffect(() => {
    if (typeof window !== "undefined") {
      const roles = JSON.parse(localStorage.getItem("plantiq-role-overrides") ?? "{}");
      const statuses = JSON.parse(localStorage.getItem("plantiq-status-overrides") ?? "{}");
      const hasOverrides = Object.keys(roles).length > 0 || Object.keys(statuses).length > 0;
      if (hasOverrides) {
        setUserList((prev) =>
          prev.map((u) => ({
            ...u,
            ...(roles[u.id] ? { role: roles[u.id] as Role } : {}),
            ...(statuses[u.id] ? { status: statuses[u.id] as "active" | "disabled" } : {}),
          }))
        );
        setChangedRoles(roles);
      }
    }
  }, []);

  const admins = userList.filter((u) => u.role === "admin");
  const reviewers = userList.filter((u) => u.role === "reviewer");
  const users = userList.filter((u) => u.role === "user");

  const totalActive = userList.filter((u) => u.status === "active").length;

  function changeRole(userId: string, newRole: Role) {
    setChangedRoles((prev) => ({ ...prev, [userId]: newRole }));
    setUserList((prev) =>
      prev.map((u) => (u.id === userId ? { ...u, role: newRole } : u))
    );
    // Persist to localStorage
    if (typeof window !== "undefined") {
      const stored = JSON.parse(localStorage.getItem("plantiq-role-overrides") ?? "{}");
      stored[userId] = newRole;
      localStorage.setItem("plantiq-role-overrides", JSON.stringify(stored));
    }
  }

  function toggleStatus(userId: string) {
    setUserList((prev) =>
      prev.map((u) =>
        u.id === userId
          ? { ...u, status: u.status === "active" ? "disabled" : "active" }
          : u
      )
    );
    // Persist to localStorage
    if (typeof window !== "undefined") {
      const stored = JSON.parse(localStorage.getItem("plantiq-status-overrides") ?? "{}");
      const current = userList.find((u) => u.id === userId);
      stored[userId] = current?.status === "active" ? "disabled" : "active";
      localStorage.setItem("plantiq-status-overrides", JSON.stringify(stored));
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
              Manage accounts and role-based access for Cove Point LNG
            </p>
          </div>
          <Button className="gap-2 font-semibold">
            <UserPlus className="h-4 w-4" />
            Add User
          </Button>
        </div>

        <div className="flex-1 overflow-y-auto min-h-0">
          <div className="p-6 max-w-5xl mx-auto space-y-6">
            {/* Role distribution stats */}
            <div className="grid grid-cols-4 gap-4">
              {[
                { label: "Admins", count: admins.length, color: "text-primary", bg: "bg-primary/10 border-primary/30", icon: <ShieldCheck className="h-5 w-5 text-primary" /> },
                { label: "Reviewers", count: reviewers.length, color: "text-blue-400", bg: "bg-blue-400/10 border-blue-400/30", icon: <Eye className="h-5 w-5 text-blue-400" /> },
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
              <div className="px-4 py-3 border-b border-border bg-muted/40 flex items-center justify-between">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
                  All Users ({userList.length})
                </h2>
                {Object.keys(changedRoles).length > 0 && (
                  <Badge variant="outline" className="text-xs text-amber-400 border-amber-400/30 bg-amber-400/10">
                    {Object.keys(changedRoles).length} role(s) changed
                  </Badge>
                )}
              </div>
              <Table>
                <TableHeader>
                  <TableRow className="bg-muted/30 hover:bg-muted/30 border-border">
                    <TableHead className="font-semibold text-foreground">User</TableHead>
                    <TableHead className="font-semibold text-foreground w-36">Role</TableHead>
                    <TableHead className="font-semibold text-foreground">Department</TableHead>
                    <TableHead className="font-semibold text-foreground">Last Login</TableHead>
                    <TableHead className="font-semibold text-foreground w-24 text-center">Status</TableHead>
                    <TableHead className="font-semibold text-foreground text-right">Actions</TableHead>
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

                      {/* Role — inline dropdown (US-3.2) */}
                      <TableCell className="py-4">
                        <Select
                          value={u.role}
                          onValueChange={(val) => changeRole(u.id, val as Role)}
                        >
                          <SelectTrigger className="h-8 text-xs w-[130px] bg-card border-border">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="admin">
                              <span className="text-primary font-medium">Admin</span>
                            </SelectItem>
                            <SelectItem value="reviewer">
                              <span className="text-blue-400 font-medium">Reviewer</span>
                            </SelectItem>
                            <SelectItem value="user">
                              <span className="text-zinc-300 font-medium">User</span>
                            </SelectItem>
                          </SelectContent>
                        </Select>
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

                      {/* Status */}
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

                      {/* Actions */}
                      <TableCell className="py-4 text-right">
                        <Button
                          variant="outline"
                          size="sm"
                          className={`text-xs h-8 px-3 ${
                            u.status === "active"
                              ? "text-red-400 border-red-400/30 hover:bg-red-400/10"
                              : "text-green-400 border-green-400/30 hover:bg-green-400/10"
                          }`}
                          onClick={() => toggleStatus(u.id)}
                        >
                          {u.status === "active" ? "Disable" : "Enable"}
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Card>
          </div>
        </div>
      </div>
    </AppLayout>
  );
}
