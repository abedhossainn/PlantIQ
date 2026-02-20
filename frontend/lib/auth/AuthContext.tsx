"use client";

import React, { createContext, useContext, useState, useCallback, useEffect } from "react";
import type { User } from "@/types";
import { getUserByUsername } from "@/lib/mock";

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
    const storedUser = localStorage.getItem("mockUser");
    if (storedUser) {
      try {
        setUser(JSON.parse(storedUser));
      } catch (e) {
        console.error("Failed to parse stored user", e);
        localStorage.removeItem("mockUser");
      }
    }
    setIsLoading(false);
  }, []);

  const login = useCallback(async (username: string, _password: string) => {
    // Mock authentication - in real system this would call backend API
    // For prototype, we just check if user exists and status is active
    const foundUser = getUserByUsername(username);

    if (!foundUser) {
      throw new Error("User not found");
    }

    if (foundUser.status === "disabled") {
      throw new Error("User account is disabled");
    }

    // Update last login timestamp
    const authenticatedUser = {
      ...foundUser,
      lastLogin: new Date().toISOString(),
    };

    setUser(authenticatedUser);
    localStorage.setItem("mockUser", JSON.stringify(authenticatedUser));

    // Simulate network delay
    await new Promise((resolve) => setTimeout(resolve, 500));
  }, []);

  const logout = useCallback(() => {
    setUser(null);
    localStorage.removeItem("mockUser");
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
