"use client";

import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/context/AuthContext";

export default function DashboardPage() {
  const { user, logout } = useAuth();
  const router = useRouter();

  async function handleLogout() {
    await logout();
    router.push("/signin");
  }

  if (!user) return null;

  const initials =
    (user.first_name[0] ?? "").toUpperCase() +
    (user.last_name[0] ?? "").toUpperCase();

  const joined = new Date(user.created_at).toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });

  return (
    <div>
      {/* Top Nav */}
      <nav className="fixed top-0 z-50 w-full border-b border-white/5 bg-black/90 backdrop-blur-md">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-2">
            <div className="h-8 w-8 rounded-lg bg-white flex items-center justify-center">
              <svg
                width="16"
                height="16"
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
            <span className="text-lg font-bold tracking-tight">
              AI Resume Architect
            </span>
          </div>

          <div className="flex items-center gap-4">
            <Link
              href="/chat"
              className="rounded-full bg-white px-5 py-2 text-sm font-medium text-black transition-all hover:bg-neutral-200 active:scale-95 shadow-[0_0_15px_rgba(255,255,255,0.1)]"
            >
              Chat with AI
            </Link>
            <button
              onClick={handleLogout}
              id="logout-button"
              className="rounded-full border border-white/10 bg-transparent px-5 py-2 text-sm font-medium text-neutral-300 transition-all hover:border-white/20 hover:text-white active:scale-95"
            >
              Sign Out
            </button>
          </div>
        </div>
      </nav>

      {/* Main Content */}
      <main className="mx-auto max-w-5xl px-6 pt-28 pb-16">
        {/* Welcome */}
        <div className="mb-12 flex flex-col md:flex-row md:items-end justify-between gap-6">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">
              Welcome back, {user.first_name} 👋
            </h1>
            <p className="mt-2 text-neutral-500">
              Here&apos;s your account overview
            </p>
          </div>
        </div>

        {/* Profile Card */}
        <div className="rounded-2xl border border-neutral-800 bg-neutral-900/50 p-6 mb-10">
          <div className="flex items-start gap-5">
            {/* Avatar */}
            <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-white to-neutral-400 text-xl font-bold text-black">
              {initials}
            </div>

            <div className="flex-1 min-w-0">
              <h2 className="text-xl font-bold">
                {user.first_name} {user.last_name}
              </h2>
              <p className="mt-1 text-sm text-neutral-400">{user.email}</p>

              <div className="mt-4 flex flex-wrap gap-3">
                <span className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-xs font-medium text-neutral-400">
                  <svg
                    width="12"
                    height="12"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                  >
                    <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
                    <line x1="16" y1="2" x2="16" y2="6" />
                    <line x1="8" y1="2" x2="8" y2="6" />
                    <line x1="3" y1="10" x2="21" y2="10" />
                  </svg>
                  Joined {joined}
                </span>
                <span className="inline-flex items-center gap-2 rounded-full border border-green-500/20 bg-green-500/10 px-3 py-1.5 text-xs font-medium text-green-400">
                  <div className="h-1.5 w-1.5 rounded-full bg-green-400" />
                  Active
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Feature Cards Grid */}
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {/* Chat Link Card */}
          <Link
            href="/chat"
            className="group block rounded-2xl border border-neutral-800 bg-neutral-900/50 p-6 transition-all hover:border-white/20 hover:bg-neutral-900"
          >
            <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-xl border border-neutral-800 bg-white text-black shadow-[0_0_15px_rgba(255,255,255,0.15)] group-hover:scale-105 transition-transform">
              <svg
                width="20"
                height="20"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
              </svg>
            </div>
            <h3 className="text-sm font-bold">Chat with AI</h3>
            <p className="mt-1 text-xs text-neutral-500">
              Interactive assistant to help craft and review your resume
            </p>
          </Link>

          {[
            {
              icon: (
                <svg
                  width="20"
                  height="20"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="white"
                  strokeWidth="2"
                >
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                  <polyline points="14 2 14 8 20 8" />
                </svg>
              ),
              title: "My Resumes",
              desc: "Create and manage your AI-powered resumes",
            },
            {
              icon: (
                <svg
                  width="20"
                  height="20"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="white"
                  strokeWidth="2"
                >
                  <circle cx="12" cy="12" r="10" />
                  <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
                  <line x1="12" y1="17" x2="12.01" y2="17" />
                </svg>
              ),
              title: "Account Info",
              desc: `ID: ${user.id.slice(0, 8)}…`,
            },
          ].map((card) => (
            <div
              key={card.title}
              className="group rounded-2xl border border-neutral-800 bg-neutral-900/50 p-6 transition-all hover:border-white/20 hover:bg-neutral-900"
            >
              <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-xl border border-neutral-800 bg-neutral-950">
                {card.icon}
              </div>
              <h3 className="text-sm font-bold">{card.title}</h3>
              <p className="mt-1 text-xs text-neutral-500">{card.desc}</p>
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}
