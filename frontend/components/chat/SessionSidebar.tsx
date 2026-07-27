"use client";

import { SquarePen } from "lucide-react";
import { cn } from "@/lib/utils";
import type { ChatSession } from "@/hooks/useChat";

interface SessionSidebarProps {
    sessions: ChatSession[];
    activeId: string;
    onSelect: (sessionId: string) => void;
    onNew: () => void;
    /** Small screens only: the same panel, slid over the chat. Ignored from md up, where
     *  it is always in the layout. */
    open?: boolean;
    onClose?: () => void;
}

function relativeDate(iso: string): string {
    const then = new Date(iso);
    if (Number.isNaN(then.getTime())) return "";

    const days = Math.floor((Date.now() - then.getTime()) / 86_400_000);
    if (days <= 0) return "Today";
    if (days === 1) return "Yesterday";
    if (days < 7) return `${days} days ago`;
    return then.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function SessionSidebar({ sessions, activeId, onSelect, onNew, open, onClose }: SessionSidebarProps) {
    return (
        <>
            {open && (
                <div
                    className="fixed inset-0 z-40 bg-black/70 md:hidden"
                    onClick={onClose}
                    aria-hidden
                />
            )}
            <aside
                className={cn(
                    "w-64 shrink-0 flex-col border-r border-neutral-800 bg-neutral-950",
                    "hidden md:flex",
                    open && "fixed inset-y-0 left-0 z-50 flex"
                )}
            >
                <div className="p-3">
                    <button
                        onClick={() => {
                            onNew();
                            onClose?.();
                        }}
                        className="flex w-full items-center justify-center gap-2 rounded-xl bg-white px-4 py-2.5 text-sm font-semibold text-black transition-colors hover:bg-neutral-200 active:scale-[0.98]"
                    >
                        <SquarePen size={16} />
                        New resume
                    </button>
                </div>

                <nav className="flex-1 overflow-y-auto px-2 pb-4">
                    {sessions.length === 0 ? (
                        <p className="px-3 py-6 text-center text-xs text-neutral-600">
                            Your conversations will show up here.
                        </p>
                    ) : (
                        <ul className="space-y-1">
                            {sessions.map((session) => (
                                <li key={session.session_id}>
                                    <button
                                        onClick={() => {
                                            onSelect(session.session_id);
                                            onClose?.();
                                        }}
                                        className={cn(
                                            "w-full rounded-lg px-3 py-2 text-left transition-colors",
                                            session.session_id === activeId
                                                ? "bg-neutral-800 text-white"
                                                : "text-neutral-400 hover:bg-neutral-900 hover:text-neutral-200"
                                        )}
                                    >
                                        <span className="block truncate text-sm font-medium">
                                            {session.title || "New resume"}
                                        </span>
                                        <span className="block text-xs text-neutral-600">
                                            {relativeDate(session.updated_at)}
                                        </span>
                                    </button>
                                </li>
                            ))}
                        </ul>
                    )}
                </nav>
            </aside>
        </>
    );
}