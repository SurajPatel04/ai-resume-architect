"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "@/context/AuthContext";

/**
 * Auth guard layout for protected pages.
 * Redirects unauthenticated users to /signin.
 */
export default function ProtectedLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { isAuthenticated, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !isAuthenticated) {
      router.replace("/signin");
    }
  }, [isAuthenticated, loading, router]);

  if (loading) {
    return (
      <div className="min-h-screen w-full flex items-center justify-center bg-black">
        <div className="flex flex-col items-center gap-4">
          <div className="h-6 w-6 border-2 border-neutral-700 border-t-white rounded-full animate-spin" />
          <p className="text-sm text-neutral-500">Loading…</p>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) return null;

  return (
    <div className="min-h-screen bg-black text-white">{children}</div>
  );
}
