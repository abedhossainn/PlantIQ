"use client";

/**
 * Login Page
 *
 * Purpose:
 * - Captures user credentials and initiates authentication flow via AuthContext.
 * - Provides clear loading/error feedback during async auth attempts.
 *
 * Flow:
 * 1. User submits username/password.
 * 2. `login()` in AuthContext performs backend/dev-mode auth logic.
 * 3. On success, router redirects to app root.
 * 4. On failure, user-facing error message is displayed.
 *
 * QA notes:
 * - Loading state should disable submit controls to prevent duplicate requests.
 * - Error text should clear on subsequent attempts.
 * - Redirect should only occur after successful auth context update.
 * - Keep credential fields controlled to avoid stale form state.
 */

import { useState, useEffect } from "react";
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
  const { login, user, isAdmin } = useAuth();
  const router = useRouter();

  // If already authenticated, skip the login page.
  useEffect(() => {
    if (user) {
      router.replace(isAdmin ? "/admin/documents" : "/chat");
    }
  }, [user, isAdmin, router]);

  function getPostLoginRoute(): string {
    if (typeof window === "undefined") {
      return "/chat";
    }

    try {
      const raw = localStorage.getItem("authUser") ?? localStorage.getItem("mockUser");
      if (raw) {
        const parsed = JSON.parse(raw) as { role?: string };
        return parsed.role === "admin" ? "/admin/documents" : "/chat";
      }
    } catch {
      // Fall through to safe default.
    }

    return "/chat";
  }

  const handleSubmit = async (e: { preventDefault: () => void }) => {
    e.preventDefault();
    setError("");
    setIsLoading(true);
    try {
      await login(username, password);
      router.push(getPostLoginRoute());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Authentication failed");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-background px-4 py-8">
      <div className="mx-auto grid min-h-[calc(100vh-4rem)] w-full max-w-6xl items-center gap-10 md:grid-cols-2">
        <section className="flex flex-col items-center justify-center p-8 md:p-12">
          <Image
            src="/PlantIQ/BHE GT&S_Logo.png"
            alt="BHE GT&S"
            width={420}
            height={420}
            className="h-auto w-full max-w-[420px] object-contain"
            priority
          />
        </section>

        <section className="flex items-center justify-center">
          <Card className="w-full max-w-md border-border">
            <CardHeader className="space-y-1 pb-4 text-center">
              <div className="mb-3 flex justify-center">
                <Image
                  src="/PlantIQ/BHE-logo.png"
                  alt="BHE GT&S"
                  width={180}
                  height={90}
                  className="object-contain"
                  priority
                />
              </div>
              <CardTitle className="text-3xl font-bold tracking-tight">PlantIQ</CardTitle>
              <CardDescription className="text-sm">BHE GT&amp;S · Cove Point LNG Facility</CardDescription>
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
                  className="h-11 w-full border-2 border-primary/20 font-semibold shadow-lg shadow-primary/20 transition-all hover:border-primary/30 hover:shadow-primary/30"
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
                <p>Please log in using your <strong className="text-foreground/70">organization domain account</strong> credentials.</p>
              </div>
            </CardContent>
          </Card>
        </section>
      </div>
    </div>
  );
}
