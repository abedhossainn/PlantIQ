"use client";

/**
 * AppLayout - Global Shell for Authenticated Experience
 *
 * Responsibilities:
 * - Enforces auth gate and route protection at layout boundary.
 * - Applies role-based navigation visibility (admin vs user routes).
 * - Hosts shared sidebar/header composition used across app pages.
 * - Centralizes logout behavior and identity display (avatar, role badge).
 *
 * Route guards:
 * - Unauthenticated users are redirected to `/login`.
 * - Users with `user` role are blocked from `/admin/*` and redirected to `/chat`.
 * - Guards run client-side for UX; backend authorization remains source of truth.
 *
 * Navigation model:
 * - Admin nav includes document pipeline + user management areas.
 * - Standard user nav focuses on chat-centric workflows.
 * - Optional `sidebarContent` lets pages inject contextual panels (e.g., conversation list).
 *
 * Developer ergonomics:
 * - Applies Next.js portal style tweak to avoid toast overlap with sidebar profile section.
 * - Keeps cross-page shell concerns out of individual page components.
 */

import { useEffect, useState } from "react";
import Image from "next/image";
import { useAuth } from "@/lib/auth/AuthContext";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { RoleBadge } from "./RoleBadge";
import { Separator } from "@/components/ui/separator";
import { ProfileDialog } from "./ProfileDialog";
import {
  FileText,
  Upload,
  MessageSquare,
  Users,
  LogOut,
  CheckCircle2,
  UserCircle,
} from "lucide-react";

interface AppLayoutProps {
  children: React.ReactNode;
  /** Optional sidebar content rendered below the logo for non-admin users (e.g. conversation list). When provided the standard nav items are hidden. */
  sidebarContent?: React.ReactNode;
  /** When true, fully collapses the left sidebar container so main content spans full width. */
  hideSidebar?: boolean;
}

export function AppLayout({ children, sidebarContent, hideSidebar = false }: AppLayoutProps) {
  const { user, logout, isAuthenticated } = useAuth();
  const [showProfileDialog, setShowProfileDialog] = useState(false);
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const viewParam = searchParams?.get("view") ?? "";

  useEffect(() => {
    if (!isAuthenticated && pathname !== "/login") {
      router.replace("/login");
    }
  }, [isAuthenticated, pathname, router]);

  // RBAC route guard — prevent 'user' role from accessing admin pages (US-3.2)
  useEffect(() => {
    if (isAuthenticated && user?.role === "user" && pathname?.startsWith("/admin")) {
      router.replace("/chat");
    }
  }, [isAuthenticated, user, pathname, router]);

  // Reposition Next.js dev toolbar so it doesn't overlap the sidebar user section
  useEffect(() => {
    const portal = document.querySelector("nextjs-portal");
    if (portal?.shadowRoot) {
      const style = document.createElement("style");
      style.textContent = ".nextjs-toast { bottom: 110px !important; }";
      portal.shadowRoot.appendChild(style);
    }
  }, []);

  if (!isAuthenticated || !user) {
    return null;
  }

  const isAdmin = user.role === "admin";

  const handleLogout = () => {
    logout();
    router.replace("/login");
  };

  const getInitials = (name: string) => {
    return name
      .split(" ")
      .map((n) => n[0])
      .join("")
      .toUpperCase();
  };

  // Navigation items based on role
  const adminNav = [
    {
      label: "Documents",
      icon: FileText,
      href: "/admin/documents",
      active: pathname === "/admin/documents" && viewParam === "",
    },
    {
      label: "Pending Documents",
      icon: CheckCircle2,
      href: "/admin/documents?view=pending-documents",
      active: pathname === "/admin/documents" && viewParam === "pending-documents",
    },
    {
      label: "Upload Document",
      icon: Upload,
      href: "/admin/documents/upload",
      active: pathname === "/admin/documents/upload",
    },
    {
      label: "Chat",
      icon: MessageSquare,
      href: "/chat",
      active: pathname === "/chat",
    },
    {
      label: "Users",
      icon: Users,
      href: "/admin/users",
      active: pathname === "/admin/users",
    },
  ];

  const userNav = [
    {
      label: "Chat",
      icon: MessageSquare,
      href: "/chat",
      active: pathname === "/chat",
    },
  ];

  const navItems = isAdmin ? adminNav : userNav;

  return (
    <div className="flex h-screen bg-background">
      {/* Sidebar */}
      <div
        className={`relative shrink-0 overflow-hidden transition-[width] duration-300 ease-in-out ${hideSidebar ? "w-0 border-r-0" : "w-64 border-r border-border"}`}
      >
      <div
        className={`absolute inset-0 w-64 bg-sidebar flex flex-col transition-transform duration-300 ease-in-out ${hideSidebar ? "-translate-x-full pointer-events-none" : "translate-x-0"}`}
        aria-hidden={hideSidebar}
      >
        {/* Header */}
        <div className="p-4 border-b border-sidebar-border">
          <div className="flex flex-col items-center gap-2">
            <Image
              src="/PlantIQ/BHE-logo.png"
              alt="BHE GT&S"
              width={140}
              height={70}
              className="object-contain"
            />
            <div className="text-center">
              <h1 className="text-sm font-bold text-sidebar-foreground">
                PlantIQ
              </h1>
              <p className="text-xs text-sidebar-foreground/70">
                Cove Point LNG
              </p>
            </div>
          </div>
        </div>

        {/* Sidebar main content:
            - When sidebarContent is provided (user-role chat view): render it directly, taking up all remaining space.
            - Otherwise: render the standard role-based navigation. */}
        {sidebarContent ? (
          <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
            {sidebarContent}
          </div>
        ) : (
          <nav className="flex-1 p-4 space-y-2">
            {navItems.map((item) => (
              <Button
                key={item.href + item.label}
                variant={item.active ? "default" : "ghost"}
                className={`w-full justify-start ${
                  item.active
                    ? "bg-sidebar-primary text-sidebar-primary-foreground"
                    : "text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
                }`}
                onClick={() => router.push(item.href)}
              >
                <item.icon className="mr-2 h-4 w-4" />
                {item.label}
              </Button>
            ))}
          </nav>
        )}

        <Separator className="bg-sidebar-border" />

        {/* User Profile — only shown for admin role; user role has profile in header */}
        {isAdmin && (
          <div className="p-4 pb-8">
            <button
              type="button"
              className="w-full flex items-center gap-3 mb-3 rounded-lg p-2 -mx-2 hover:bg-sidebar-accent transition-colors text-left"
              onClick={() => setShowProfileDialog(true)}
              aria-label="View your profile"
            >
              <Avatar className="h-10 w-10 border-2 border-primary shrink-0">
                <AvatarFallback className="bg-primary text-primary-foreground text-sm font-medium">
                  {getInitials(user.fullName)}
                </AvatarFallback>
              </Avatar>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-sidebar-foreground truncate">
                  {user.fullName}
                </p>
                <RoleBadge role={user.role} className="text-xs" />
              </div>
              <UserCircle className="h-4 w-4 text-sidebar-foreground/50 shrink-0" />
            </button>
            <Button
              variant="ghost"
              size="sm"
              className="w-full justify-start text-sidebar-foreground hover:bg-sidebar-accent"
              onClick={handleLogout}
            >
              <LogOut className="mr-2 h-4 w-4" />
              Sign Out
            </Button>
          </div>
        )}
      </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex flex-col overflow-hidden">{children}</div>
      {user && (
        <ProfileDialog
          user={user}
          open={showProfileDialog}
          onOpenChange={setShowProfileDialog}
        />
      )}
    </div>
  );
}
