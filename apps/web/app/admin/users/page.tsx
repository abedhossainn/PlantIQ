"use client";

/**
 * Users Administration Page
 *
 * Purpose:
 * - Displays user directory sourced from backend LDAP-backed endpoint.
 * - Supports role updates only; user creation is managed exclusively through LDAP.
 * - Provides quick team-level metrics (active users, role distribution).
 * - Merged with Directory Settings panel (right column) for unified admin workflow.
 *
 * Data source model:
 * - Users are fetched from GET /api/v1/auth/admin/users on mount.
 * - Role changes are persisted via PATCH /api/v1/auth/admin/users/{id}/role.
 * - Directory config loaded from GET /api/v1/auth/admin/directory-config.
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

import { useState, useEffect, useMemo, useRef } from "react";
import { AppLayout } from "@/components/shared/AppLayout";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  Users,
  Mail,
  Building2,
  Clock,
  ShieldCheck,
  User2,
  AlertCircle,
  Loader2,
  Shield,
  CheckCircle2,
} from "lucide-react";
import {
  getAdminDirectoryConfig,
  getAdminUsers,
  patchUserRole,
  patchUserStatus,
  ApiError,
  getDirectoryDomainLabel,
  activateAdminDirectoryConfig,
  testAdminDirectoryConfig,
  upsertAdminDirectoryConfig,
  type DirectoryConfigResponse,
} from "@/lib/api";
import type { User } from "@/types";
import {
  buildDirectoryConfigUpsertPayload,
  getDefaultDirectoryConfigHiddenValues,
  mapConfigToFormValues,
  validateDirectoryConfigForm,
  type DirectoryConfigFormErrors,
  type DirectoryConfigHiddenValues,
  type DirectoryConfigFormValues,
} from "./_helpers";

type Role = "admin" | "user";

const DEFAULT_FORM: DirectoryConfigFormValues = {
  connectionTarget: "",
  baseDn: "",
  userSearchBase: "",
  bindDn: "",
};

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

function getErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    return error.message || fallback;
  }
  if (error instanceof Error) {
    return error.message || fallback;
  }
  return fallback;
}

function getStatusAlertClass(statusTone: "success" | "error" | "info"): string {
  if (statusTone === "error") {
    return "border-red-400/30 bg-red-400/5";
  }
  if (statusTone === "success") {
    return "border-green-400/30 bg-green-400/5";
  }
  return "border-border";
}

// NOSONAR: Page coordinates async admin workflows and stateful form UX in one component by design.
export default function UsersPage() {
  // ── Users state ─────────────────────────────────────────────────────────
  const [userList, setUserList] = useState<User[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [directoryDomain, setDirectoryDomain] = useState<string | null>(null);
  // Per-user role change error (keyed by user ID)
  const [roleErrors, setRoleErrors] = useState<Record<string, string>>({});
  // Per-user status change state (keyed by user ID)
  const [statusErrors, setStatusErrors] = useState<Record<string, string>>({});
  const [statusPending, setStatusPending] = useState<Record<string, boolean>>({});

  // ── Directory config state ───────────────────────────────────────────────
  const [form, setForm] = useState<DirectoryConfigFormValues>(DEFAULT_FORM);
  const [hiddenValues, setHiddenValues] = useState<DirectoryConfigHiddenValues>(getDefaultDirectoryConfigHiddenValues());
  const [formErrors, setFormErrors] = useState<DirectoryConfigFormErrors>({});
  const [dirConfig, setDirConfig] = useState<DirectoryConfigResponse | null>(null);
  const [isDirLoading, setIsDirLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [statusTone, setStatusTone] = useState<"success" | "error" | "info">("info");
  const bindPasswordInputRef = useRef<HTMLInputElement>(null);

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

    async function loadConfig() {
      setIsDirLoading(true);
      setStatusMessage(null);
      try {
        const config = await getAdminDirectoryConfig();
        if (!cancelled) {
          setDirConfig(config);
          setDirectoryDomain(getDirectoryDomainLabel(config));
          const mapped = mapConfigToFormValues(config);
          setForm(mapped.formValues);
          setHiddenValues(mapped.hiddenValues);
          setStatusTone("info");
          setStatusMessage("Directory settings loaded.");
        }
      } catch (error) {
        if (!cancelled) {
          if (error instanceof ApiError && error.status === 404) {
            setDirConfig(null);
            setDirectoryDomain(null);
            setForm(DEFAULT_FORM);
            setHiddenValues(getDefaultDirectoryConfigHiddenValues());
            setStatusTone("info");
            setStatusMessage("No saved directory profile found yet. Fill the form and save to create one.");
          } else {
            setStatusTone("error");
            setStatusMessage(getErrorMessage(error, "Failed to load directory settings."));
          }
        }
      } finally {
        if (!cancelled) {
          setIsDirLoading(false);
        }
      }
    }

    loadUsers();
    void loadConfig();

    return () => {
      cancelled = true;
      if (bindPasswordInputRef.current) {
        bindPasswordInputRef.current.value = "";
      }
    };
  }, []);

  const admins = userList.filter((u) => u.role === "admin");
  const users = userList.filter((u) => u.role === "user");
  const totalActive = userList.filter((u) => u.status === "active").length;

  const hasFormErrors = useMemo(() => Object.keys(formErrors).length > 0, [formErrors]);
  const saveAndActivateLabel = dirConfig ? "Update & Activate" : "Save & Activate";

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

  async function toggleStatus(userId: string, currentStatus: string) {
    const newStatus = currentStatus === "active" ? "disabled" : "active";
    setStatusPending((prev) => ({ ...prev, [userId]: true }));
    setStatusErrors((prev) => { const n = { ...prev }; delete n[userId]; return n; });

    // Optimistic update
    setUserList((prev) =>
      prev.map((u) => (u.id === userId ? { ...u, status: newStatus as "active" | "disabled" } : u))
    );

    try {
      await patchUserStatus(userId, newStatus as "active" | "disabled");
    } catch (err) {
      // Revert
      setUserList((prev) =>
        prev.map((u) => (u.id === userId ? { ...u, status: currentStatus as "active" | "disabled" } : u))
      );
      let message = "Status update failed. Please try again.";
      if (err instanceof ApiError && err.status === 403) {
        message = "You cannot disable your own account.";
      }
      setStatusErrors((prev) => ({ ...prev, [userId]: message }));
    } finally {
      setStatusPending((prev) => { const n = { ...prev }; delete n[userId]; return n; });
    }
  }

  function updateField<K extends keyof DirectoryConfigFormValues>(key: K, value: DirectoryConfigFormValues[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
    setFormErrors((prev) => {
      if (!prev[key]) {
        return prev;
      }
      const next = { ...prev };
      delete next[key];
      return next;
    });
    setStatusMessage(null);
  }

  function clearBindPasswordInput(): void {
    if (bindPasswordInputRef.current) {
      bindPasswordInputRef.current.value = "";
    }
  }

  function validateCurrentForm(): boolean {
    const errors = validateDirectoryConfigForm(form);
    setFormErrors(errors);

    if (Object.keys(errors).length > 0) {
      setStatusTone("error");
      setStatusMessage("Please fix validation errors before continuing.");
      return false;
    }

    return true;
  }

  async function handleTestConnection(): Promise<void> {
    if (!validateCurrentForm()) {
      return;
    }

    setIsTesting(true);
    setStatusMessage(null);

    try {
      const bindPassword = bindPasswordInputRef.current?.value ?? "";
      const payload = buildDirectoryConfigUpsertPayload(form, hiddenValues, bindPassword);
      const response = await testAdminDirectoryConfig({ config: payload });

      setStatusTone(response.success ? "success" : "error");
      setStatusMessage(response.message);
    } catch (error) {
      setStatusTone("error");
      setStatusMessage(getErrorMessage(error, "Directory connectivity test failed."));
    } finally {
      clearBindPasswordInput();
      setIsTesting(false);
    }
  }

  async function handleSaveAndActivate(): Promise<void> {
    if (!validateCurrentForm()) {
      return;
    }

    setIsSaving(true);
    setStatusMessage(null);

    try {
      const bindPassword = bindPasswordInputRef.current?.value ?? "";
      const payload = buildDirectoryConfigUpsertPayload(form, hiddenValues, bindPassword);
      const saved = await upsertAdminDirectoryConfig(payload);

      setDirConfig(saved);
      const mapped = mapConfigToFormValues(saved);
      setForm(mapped.formValues);
      setHiddenValues(mapped.hiddenValues);

      try {
        const activated = await activateAdminDirectoryConfig();
        setDirConfig(activated);
        const activatedMapped = mapConfigToFormValues(activated);
        setForm(activatedMapped.formValues);
        setHiddenValues(activatedMapped.hiddenValues);
        setStatusTone("success");
        setStatusMessage("Directory settings saved and activated successfully.");
      } catch (error) {
        setStatusTone("error");
        setStatusMessage(getErrorMessage(error, "Directory settings saved, but activation failed."));
      }
    } catch (error) {
      setStatusTone("error");
      setStatusMessage(getErrorMessage(error, "Failed to save directory settings."));
    } finally {
      clearBindPasswordInput();
      setIsSaving(false);
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
          <Badge
            variant="outline"
            className="border-green-400/30 bg-green-400/10 text-green-300 shrink-0 whitespace-nowrap"
          >
            {directoryDomain ? `Connected domain: ${directoryDomain}` : "Domain not connected"}
          </Badge>
        </div>

        {/* Body: 2-column split layout */}
        <div className="grid grid-cols-3 gap-6 flex-1 min-h-0">
          {/* Left column (2/3): user management */}
          <div className="col-span-2 overflow-y-auto h-full p-6 space-y-6">
            <Card className="p-4 border border-amber-400/30 bg-amber-400/5">
              <p className="text-sm font-semibold text-amber-300">Users are managed through the identity directory</p>
              <p className="text-xs text-muted-foreground mt-1">
                Accounts are provisioned via LDAP. Role assignments and local access status can be changed from this page.
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

                          {/* Status toggle */}
                          <TableCell className="py-4 text-center">
                            <div className="flex flex-col items-center gap-1">
                              <button
                                onClick={() => toggleStatus(u.id, u.status)}
                                disabled={statusPending[u.id]}
                                aria-label={u.status === "active" ? `Disable ${u.fullName}` : `Enable ${u.fullName}`}
                                className="focus:outline-none focus:ring-2 focus:ring-ring rounded"
                              >
                                <Badge
                                  variant="outline"
                                  className={
                                    statusPending[u.id]
                                      ? "text-zinc-400 bg-zinc-400/10 border-zinc-400/30 text-xs cursor-wait"
                                      : u.status === "active"
                                      ? "text-green-400 bg-green-400/10 border-green-400/30 text-xs cursor-pointer hover:bg-green-400/20 transition-colors"
                                      : "text-zinc-500 bg-zinc-500/10 border-zinc-500/30 text-xs cursor-pointer hover:bg-zinc-500/20 transition-colors"
                                  }
                                >
                                  {statusPending[u.id] ? "…" : u.status === "active" ? "Active" : "Disabled"}
                                </Badge>
                              </button>
                              {statusErrors[u.id] && (
                                <p className="text-xs text-red-400 flex items-center gap-1">
                                  <AlertCircle className="h-3 w-3 shrink-0" />
                                  {statusErrors[u.id]}
                                </p>
                              )}
                            </div>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </Card>
              </>
            )}
          </div>

          {/* Right column (1/3): directory settings */}
          <div className="col-span-1 overflow-y-auto h-full p-6 border-l border-border space-y-4">
            <div className="flex items-center gap-2">
              <Shield className="h-4 w-4 text-primary" />
              <h2 className="text-sm font-semibold">Directory Settings</h2>
            </div>

            <Card className="p-4 border border-amber-400/30 bg-amber-400/5">
              <p className="text-sm font-semibold text-amber-300">Bind password is write-only</p>
              <p className="text-xs text-muted-foreground mt-1">
                For security, this field is never returned from the API and always starts blank.
                Enter it only when rotating or setting credentials.
              </p>
            </Card>

            {statusMessage && (
              <Alert className={getStatusAlertClass(statusTone)}>
                {statusTone === "error" ? (
                  <AlertCircle className="h-4 w-4 text-red-400" />
                ) : (
                  <CheckCircle2 className="h-4 w-4 text-green-400" />
                )}
                <AlertTitle>{statusTone === "error" ? "Action failed" : "Status"}</AlertTitle>
                <AlertDescription>{statusMessage}</AlertDescription>
              </Alert>
            )}

            <Card className="p-6 space-y-5 border-border">
              {isDirLoading ? (
                <div className="py-10 flex items-center justify-center gap-2 text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Loading directory settings...
                </div>
              ) : (
                <>
                  <div className="grid grid-cols-1 gap-4">
                    <div className="space-y-1.5">
                      <Label htmlFor="connection-target">Server URL or Host</Label>
                      <Input
                        id="connection-target"
                        value={form.connectionTarget}
                        onChange={(e) => updateField("connectionTarget", e.target.value)}
                        placeholder="ldap://ldap.example.com:389"
                      />
                      {formErrors.connectionTarget && <p className="text-xs text-red-400">{formErrors.connectionTarget}</p>}
                    </div>

                    <div className="space-y-1.5">
                      <Label htmlFor="base-dn">Base DN</Label>
                      <Input
                        id="base-dn"
                        value={form.baseDn}
                        onChange={(e) => updateField("baseDn", e.target.value)}
                        placeholder="dc=example,dc=com"
                      />
                      {formErrors.baseDn && <p className="text-xs text-red-400">{formErrors.baseDn}</p>}
                    </div>

                    <div className="space-y-1.5">
                      <Label htmlFor="user-search-base">User Search Base</Label>
                      <Input
                        id="user-search-base"
                        value={form.userSearchBase}
                        onChange={(e) => updateField("userSearchBase", e.target.value)}
                        placeholder="ou=users,dc=example,dc=com"
                      />
                      {formErrors.userSearchBase && <p className="text-xs text-red-400">{formErrors.userSearchBase}</p>}
                    </div>

                    <div className="space-y-1.5">
                      <Label htmlFor="bind-dn">Bind DN</Label>
                      <Input
                        id="bind-dn"
                        value={form.bindDn}
                        onChange={(e) => updateField("bindDn", e.target.value)}
                        placeholder="cn=svc-account,dc=example,dc=com"
                      />
                      {formErrors.bindDn && <p className="text-xs text-red-400">{formErrors.bindDn}</p>}
                    </div>

                    <div className="space-y-1.5">
                      <Label htmlFor="bind-password">Bind Password (write-only)</Label>
                      <Input
                        id="bind-password"
                        type="password"
                        ref={bindPasswordInputRef}
                        autoComplete="new-password"
                        placeholder="Enter only when changing credentials"
                      />
                      <p className="text-xs text-muted-foreground">
                        Current value is never shown. Leave blank to keep existing stored password.
                      </p>
                    </div>
                  </div>

                  {hasFormErrors && (
                    <p className="text-xs text-red-400 flex items-center gap-1">
                      <AlertCircle className="h-3 w-3" />
                      Please resolve form errors before testing or saving & activating.
                    </p>
                  )}

                  <div className="flex flex-wrap gap-2 pt-2">
                    <Button type="button" variant="outline" onClick={() => void handleTestConnection()} disabled={isTesting || isSaving}>
                      {isTesting ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : null}
                      Test Connection
                    </Button>

                    <Button type="button" onClick={() => void handleSaveAndActivate()} disabled={isSaving || isTesting}>
                      {isSaving ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : null}
                      {saveAndActivateLabel}
                    </Button>
                  </div>
                </>
              )}
            </Card>
          </div>
        </div>
      </div>
    </AppLayout>
  );
}
