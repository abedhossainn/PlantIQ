"use client";

import React, { createContext, useContext, useState, useCallback, useEffect } from "react";
import type { User } from "@/types";

const AUTH_DISABLED = process.env.NEXT_PUBLIC_AUTH_DISABLED !== "false";
const FASTAPI_URL = process.env.NEXT_PUBLIC_FASTAPI_URL || "http://localhost:8000";
const AUTH_STORAGE_KEY = "authUser";
const TOKEN_STORAGE_KEY = "auth_token";

const AUTH_DISABLED_USER: User = {
  id: "00000000-0000-0000-0000-000000000001",
  username: "admin",
  email: "auth-disabled@plantiq.local",
  fullName: "Pipeline Test User",
  role: "admin",
  lastLogin: null,
  status: "active",
  department: "Development",
};

interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

interface BackendUserInfo {
  id: string;
  username: string;
  email: string;
  full_name: string;
  role: "admin" | "reviewer" | "user";
  department?: string | null;
  scope: string[];
}

function toFrontendUser(user: BackendUserInfo): User {
  return {
    id: user.id,
    username: user.username,
    email: user.email,
    fullName: user.full_name,
    role: user.role,
    lastLogin: new Date().toISOString(),
    status: "active",
    department: user.department ?? "Unknown",
  };
}

interface AuthContextType {
  user: User | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  isAuthenticated: boolean;
  isAdmin: boolean;
  isReviewer: boolean;
  isUser: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Load user from localStorage on mount
  useEffect(() => {
    if (AUTH_DISABLED) {
      const authenticatedUser = {
        ...AUTH_DISABLED_USER,
        lastLogin: new Date().toISOString(),
      };
      setUser(authenticatedUser);
      localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(authenticatedUser));
      localStorage.setItem("mockUser", JSON.stringify(authenticatedUser));
      // Store the dev JWT so PostgREST can identify the user via plantig_uid().
      // NEXT_PUBLIC_DEV_JWT is a pre-signed HS256 token for the auth-disabled admin,
      // verified by PostgREST using PGRST_JWT_SECRET.
      if (process.env.NEXT_PUBLIC_DEV_JWT) {
        localStorage.setItem(TOKEN_STORAGE_KEY, process.env.NEXT_PUBLIC_DEV_JWT);
      } else {
        localStorage.removeItem(TOKEN_STORAGE_KEY);
      }
      setIsLoading(false);
      return;
    }

    const storedUser = localStorage.getItem(AUTH_STORAGE_KEY) ?? localStorage.getItem("mockUser");
    const storedToken = localStorage.getItem(TOKEN_STORAGE_KEY);

    if (storedUser && storedToken) {
      try {
        setUser(JSON.parse(storedUser));
      } catch (e) {
        console.error("Failed to parse stored user", e);
        localStorage.removeItem(AUTH_STORAGE_KEY);
        localStorage.removeItem("mockUser");
        localStorage.removeItem(TOKEN_STORAGE_KEY);
      }
    } else {
      localStorage.removeItem(AUTH_STORAGE_KEY);
      localStorage.removeItem("mockUser");
      localStorage.removeItem(TOKEN_STORAGE_KEY);
    }

    setIsLoading(false);
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    if (AUTH_DISABLED) {
      const authenticatedUser = {
        ...AUTH_DISABLED_USER,
        username: username || AUTH_DISABLED_USER.username,
        lastLogin: new Date().toISOString(),
      };
      setUser(authenticatedUser);
      localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(authenticatedUser));
      localStorage.setItem("mockUser", JSON.stringify(authenticatedUser));
      if (process.env.NEXT_PUBLIC_DEV_JWT) {
        localStorage.setItem(TOKEN_STORAGE_KEY, process.env.NEXT_PUBLIC_DEV_JWT);
      } else {
        localStorage.removeItem(TOKEN_STORAGE_KEY);
      }
      return;
    }

    const loginResponse = await fetch(`${FASTAPI_URL}/api/v1/auth/login`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      credentials: "include",
      body: JSON.stringify({
        request: {
          username,
          password,
        },
      }),
    });

    if (!loginResponse.ok) {
      let message = "Authentication failed";

      try {
        const errorData = await loginResponse.json();
        message = errorData?.detail ?? message;
      } catch {
        // Ignore JSON parse errors and keep fallback message.
      }

      throw new Error(message);
    }

    const tokenData = (await loginResponse.json()) as LoginResponse;
    localStorage.setItem(TOKEN_STORAGE_KEY, tokenData.access_token);

    const meResponse = await fetch(`${FASTAPI_URL}/api/v1/auth/me`, {
      headers: {
        Authorization: `Bearer ${tokenData.access_token}`,
      },
      credentials: "include",
    });

    if (!meResponse.ok) {
      localStorage.removeItem(TOKEN_STORAGE_KEY);
      throw new Error("Authenticated, but failed to load user profile");
    }

    const meData = (await meResponse.json()) as BackendUserInfo;
    const authenticatedUser = toFrontendUser(meData);

    setUser(authenticatedUser);
    localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(authenticatedUser));
    localStorage.setItem("mockUser", JSON.stringify(authenticatedUser));
  }, []);

  const logout = useCallback(() => {
    if (AUTH_DISABLED) {
      const authenticatedUser = {
        ...AUTH_DISABLED_USER,
        lastLogin: new Date().toISOString(),
      };
      setUser(authenticatedUser);
      localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(authenticatedUser));
      localStorage.setItem("mockUser", JSON.stringify(authenticatedUser));
      localStorage.removeItem(TOKEN_STORAGE_KEY);
      return;
    }

    setUser(null);
    localStorage.removeItem(AUTH_STORAGE_KEY);
    localStorage.removeItem("mockUser");
    localStorage.removeItem(TOKEN_STORAGE_KEY);
  }, []);

  const value: AuthContextType = {
    user,
    login,
    logout,
    isAuthenticated: !!user,
    isAdmin: user?.role === "admin",
    isReviewer: user?.role === "reviewer",
    isUser: user?.role === "user",
  };

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <div className="text-center">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent mx-auto mb-4" />
          <p className="text-muted-foreground">Loading...</p>
        </div>
      </div>
    );
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
