"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowLeft, FileText, Menu } from "lucide-react";
import { useChat } from "@/hooks/useChat";
import { ChatMessage } from "@/components/chat/ChatMessage";
import { ChatInput } from "@/components/chat/ChatInput";
import { EmptyChatState } from "@/components/chat/EmptyChatState";
import { ThinkingIndicator } from "@/components/chat/ThinkingIndicator";
import { SessionSidebar } from "@/components/chat/SessionSidebar";
import { ResumePanel } from "@/components/chat/ResumePanel";
import { useAuth } from "@/context/AuthContext";

export default function ChatPage() {
  const {
    messages,
    sessions,
    sessionId,
    sendMessage,
    sendPayload,
    sendUpload,
    sendVoice,
    stopGenerating,
    switchSession,
    newSession,
    isReceiving,
    activeNode,
    isConnecting,
    isLoadingHistory,
    isUploading,
    snapshot,
    error,
  } = useChat();
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const { user } = useAuth();
  // Both panels are part of the layout from md/lg up. Below that the screen only fits
  // the conversation, so they slide over it instead of being unreachable.
  const [showSessions, setShowSessions] = useState(false);
  const [showPreview, setShowPreview] = useState(false);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    // isReceiving too, or the thinking indicator appears below the fold.
  }, [messages, isReceiving]);

  return (
    <div className="flex h-screen max-h-screen bg-black">
      <SessionSidebar
        sessions={sessions}
        activeId={sessionId}
        onSelect={switchSession}
        onNew={newSession}
        open={showSessions}
        onClose={() => setShowSessions(false)}
      />

      <div className="flex flex-1 flex-col min-w-0">
        {/* Header */}
        <header className="shrink-0 flex items-center justify-between border-b border-neutral-800 bg-neutral-950/50 backdrop-blur-md px-6 py-4">
          <div className="flex items-center gap-3 sm:gap-4">
            <button
              onClick={() => setShowSessions(true)}
              aria-label="Show your resumes"
              className="flex h-8 w-8 items-center justify-center rounded-full bg-neutral-900 text-neutral-400 transition-colors hover:bg-neutral-800 hover:text-white md:hidden"
            >
              <Menu size={18} />
            </button>
            <Link
              href="/dashboard"
              className="hidden h-8 w-8 items-center justify-center rounded-full bg-neutral-900 text-neutral-400 transition-colors hover:bg-neutral-800 hover:text-white sm:flex"
            >
              <ArrowLeft size={18} />
            </Link>
            <div className="flex items-center gap-2">
              <div className="h-2 w-2 rounded-full bg-green-500 animate-pulse" />
              <h1 className="text-sm font-semibold tracking-wide text-white">
                AI Architect Chat
              </h1>
            </div>
          </div>

          <div className="flex items-center gap-3 sm:gap-5">
            <button
              onClick={() => setShowPreview(true)}
              aria-label="Show the resume preview"
              className="flex h-8 w-8 items-center justify-center rounded-full bg-neutral-900 text-neutral-400 transition-colors hover:bg-neutral-800 hover:text-white lg:hidden"
            >
              <FileText size={16} />
            </button>
          </div>
        </header>

        {/* Chat Area */}
        <div className="flex-1 overflow-y-auto px-4 py-6 sm:px-6">
          <div className="mx-auto max-w-4xl">
            {error && (
              <div className="mb-6 rounded-xl border border-red-500/20 bg-red-500/10 p-4 text-sm text-red-400 text-center">
                {error}
              </div>
            )}

            {isLoadingHistory ? (
              <div className="flex justify-center py-20">
                <div className="h-6 w-6 animate-spin rounded-full border-2 border-neutral-800 border-t-white" />
              </div>
            ) : messages.length === 0 ? (
              <EmptyChatState
                userName={user?.first_name || "there"}
                onUpload={sendUpload}
                isUploading={isUploading}
                onCreateScratch={() => {
                  // No form to submit: the server seeds the profile from the signed-in
                  // account and the interview asks for the rest.
                  sendPayload(
                    { type: "create_scratch" },
                    "Let's create a new resume from scratch."
                  );
                }}
                onSendMessage={sendMessage}
              />
            ) : (
              messages.map((msg, idx) => (
                <ChatMessage
                  key={msg.id}
                  message={msg}
                  isReceiving={isReceiving && idx === messages.length - 1}
                  onSendMessage={sendMessage}
                />
              ))
            )}

            {/* The graph answers in whole messages, not token deltas, so nothing at all
              appears between sending and the reply landing. */}
            {isReceiving && <ThinkingIndicator node={activeNode} />}

            <div ref={messagesEndRef} className="h-4" />
          </div>
        </div>

        {/* Input Area (Only show when chat is active) */}
        {messages.length > 0 && (
          <div className="shrink-0 border-t border-neutral-900 bg-black p-4">
            <div className="mx-auto flex max-w-4xl justify-center">
              <ChatInput
                onSendMessage={sendMessage}
                onSendVoice={sendVoice}
                disabled={isConnecting || isReceiving}
                onStop={isReceiving ? stopGenerating : undefined}
              />
            </div>
            <p className="mt-3 text-center text-xs text-neutral-600">
              AI Resume Architect can make mistakes. Consider verifying important information.
            </p>
          </div>
        )}
      </div>

      <ResumePanel
        snapshot={snapshot}
        open={showPreview}
        onClose={() => setShowPreview(false)}
      />
    </div>
  );
}