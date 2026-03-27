"use client";

import { useEffect } from "react";
import Image from "next/image";
import { useAuth } from "@/lib/auth/AuthContext";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { RoleBadge } from "./RoleBadge";
import { Separator } from "@/components/ui/separator";
import {
  FileText,
  Upload,
  MessageSquare,
  Bookmark,
  Users,
  LogOut,
  CheckCircle2,
  AlertCircle,
  BarChart3,
} from "lucide-react";

interface AppLayoutProps {
  children: React.ReactNode;
}

export function AppLayout({ children }: AppLayoutProps) {
  const { user, logout, isAuthenticated } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const viewParam = searchParams?.get("view") ?? "";

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

  const isAdmin = user.role === "admin" || user.role === "reviewer";

  const handleLogout = () => {
    logout();
    router.push("/login");
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
      label: "Upload Document",
      icon: Upload,
      href: "/admin/documents/upload",
      active: pathname === "/admin/documents/upload",
    },
    {
      label: "Review Queue",
      icon: CheckCircle2,
      href: "/admin/documents?view=review-queue",
      active: pathname === "/admin/documents" && viewParam === "review-queue",
    },
    {
      label: "QA Gates",
      icon: BarChart3,
      href: "/admin/documents?view=qa-gates",
      active: pathname === "/admin/documents" && viewParam === "qa-gates",
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
    {
      label: "Saved Answers",
      icon: Bookmark,
      href: "/chat/bookmarks",
      active: pathname === "/chat/bookmarks",
    },
  ];

  const navItems = isAdmin ? adminNav : userNav;

  return (
    <div className="flex h-screen bg-background">
      {/* Sidebar */}
      <div className="w-64 border-r border-border bg-sidebar flex flex-col">
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

        {/* Navigation */}
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

        <Separator className="bg-sidebar-border" />

        {/* User Profile */}
        <div className="p-4 pb-8">
          <div className="flex items-center gap-3 mb-3">
            <Avatar className="h-10 w-10 border-2 border-primary">
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
          </div>
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
      </div>

      {/* Main Content */}
      <div className="flex-1 flex flex-col overflow-hidden">{children}</div>
    </div>
  );
}
