"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import Image from "next/image";

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const { login } = useAuth();
  const router = useRouter();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setIsLoading(true);
    try {
      await login(username, password);
      router.push("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed");
    } finally {
      setIsLoading(false);
    }
  };

  const quickAccessAccounts = [
    { username: "user", password: "user123", role: "user" as const, label: "Field User", color: "bg-zinc-500/10 hover:bg-zinc-500/20 border-zinc-500/40 hover:border-zinc-500/60 text-zinc-300" },
    { username: "reviewer", password: "review123", role: "reviewer" as const, label: "Reviewer", color: "bg-blue-500/10 hover:bg-blue-500/20 border-blue-500/40 hover:border-blue-500/60 text-blue-300" },
    { username: "admin", password: "admin123", role: "admin" as const, label: "Admin", color: "bg-primary/10 hover:bg-primary/20 border-primary/40 hover:border-primary/60 text-primary" },
  ];

  const roleDot: Record<string, string> = {
    user: "bg-zinc-400",
    reviewer: "bg-blue-400",
    admin: "bg-primary",
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <Card className="w-full max-w-md border-border">
        <CardHeader className="space-y-1 text-center pb-4">
          <div className="mb-3 flex justify-center">
            <Image src="/PlantIQ/BHE-logo.png" alt="BHE GT&S" width={180} height={90} className="object-contain" />
          </div>
          <CardTitle className="text-3xl font-bold tracking-tight">PlantIQ</CardTitle>
          <CardDescription className="text-sm">
            BHE GT&amp;S · Cove Point LNG Facility
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="username">Username</Label>
              <Input
                id="username"
                type="text"
                placeholder="Enter your username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                autoFocus
                className="bg-card"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                placeholder="Enter your password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                className="bg-card"
              />
            </div>

            {error && (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

            <Button 
              type="submit" 
              className="w-full font-semibold h-11 border-2 border-primary/20 hover:border-primary/30 shadow-lg shadow-primary/20 hover:shadow-primary/30 transition-all" 
              disabled={isLoading}
            >
              {isLoading ? (
                <>
                  <div className="mr-2 h-4 w-4 animate-spin rounded-full border-2 border-primary-foreground border-t-transparent" />
                  Authenticating...
                </>
              ) : (
                "Sign In"
              )}
            </Button>
          </form>

          {/* Authentication notice */}
          <div className="mt-4 rounded-lg border border-border bg-muted/20 p-3 text-xs text-muted-foreground">
            <p className="font-semibold text-foreground/80 mb-0.5">🔒 Production Authentication</p>
            <p>
              Production instances authenticate via{" "}
              <strong className="text-foreground/70">Active Directory / LDAP (SAML 2.0)</strong>.
              Session events are audit-logged with user, role, timestamp, and IP.
            </p>
          </div>

          {/* Quick access accounts */}
          <div className="mt-6 rounded-lg border border-border bg-muted/20 overflow-hidden">
            <div className="px-4 py-2.5 border-b border-border bg-muted/40">
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                Quick Access Accounts
              </p>
            </div>
            <div className="p-3 grid grid-cols-3 gap-2">
              {quickAccessAccounts.map((u) => (
                <button
                  key={u.username}
                  className={`rounded-lg border px-3 py-3 text-left transition-all active:scale-95 ${u.color}`}
                  onClick={() => {
                    setUsername(u.username);
                    setPassword(u.password);
                  }}
                >
                  <div className="flex items-center gap-1.5 mb-1">
                    <span className={`h-2 w-2 rounded-full ${roleDot[u.role]}`} />
                    <span className="text-xs font-semibold">{u.username}</span>
                  </div>
                  <span className="text-xs opacity-75">{u.label}</span>
                </button>
              ))}
            </div>
            <div className="px-4 py-3 border-t border-border bg-muted/30 text-xs text-muted-foreground space-y-1">
              <p><span className="font-semibold text-foreground/80">Admin:</span> admin / admin123</p>
              <p><span className="font-semibold text-foreground/80">Reviewer:</span> reviewer / review123</p>
              <p><span className="font-semibold text-foreground/80">User:</span> user / user123</p>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
