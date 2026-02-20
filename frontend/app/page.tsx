"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth/AuthContext";

export default function RootPage() {
  const { isAuthenticated, isAdmin, isReviewer } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isAuthenticated) {
      router.replace("/login");
    } else if (isAdmin || isReviewer) {
      router.replace("/admin/documents");
    } else {
      router.replace("/chat");
    }
  }, [isAuthenticated, isAdmin, isReviewer, router]);

  return (
    <div className="flex h-screen items-center justify-center bg-background">
      <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
    </div>
  );
}
