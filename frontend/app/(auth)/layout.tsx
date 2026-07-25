"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "@/context/AuthContext";

/**
 * Layout for auth pages (signin / signup).
 * Full-screen dark background matching rag project.
 * Redirects authenticated users to dashboard.
 */
export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const { isAuthenticated, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && isAuthenticated) {
      router.replace("/dashboard");
    }
  }, [isAuthenticated, loading, router]);

  if (loading) {
    return (
      <div className="min-h-screen w-full flex items-center justify-center bg-black">
        <div className="h-6 w-6 border-2 border-neutral-700 border-t-white rounded-full animate-spin" />
      </div>
    );
  }

  if (isAuthenticated) return null;

  return (
    <div className="min-h-screen w-full flex flex-col items-center justify-center p-6 relative bg-black">
      {/* Logo */}
      <div className="absolute top-8 left-8 md:left-12">
        <a
          href="/"
          className="flex items-center gap-2 hover:opacity-80 transition-opacity"
        >
          <div className="h-8 w-8 rounded-lg bg-white flex items-center justify-center">
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="black"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
              <line x1="16" y1="13" x2="8" y2="13" />
              <line x1="16" y1="17" x2="8" y2="17" />
            </svg>
          </div>
          <span className="text-xl font-bold tracking-tight text-white">
            AI Resume Architect
          </span>
        </a>
      </div>

      {/* Content */}
      <div className="w-full max-w-md">{children}</div>
    </div>
  );
}
