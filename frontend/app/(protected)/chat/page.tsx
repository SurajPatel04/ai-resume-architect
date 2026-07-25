"use client";

import { useEffect, useRef } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { useChat } from "@/hooks/useChat";
import { ChatMessage } from "@/components/chat/ChatMessage";
import { ChatInput } from "@/components/chat/ChatInput";
import { EmptyChatState } from "@/components/chat/EmptyChatState";
import { useAuth } from "@/context/AuthContext";

export default function ChatPage() {
  const { messages, sendMessage, sendPayload, stopGenerating, isReceiving, isConnecting, error } = useChat();
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const { user } = useAuth();

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  return (
    <div className="flex flex-col h-screen max-h-screen bg-black">
      {/* Header */}
      <header className="shrink-0 flex items-center justify-between border-b border-neutral-800 bg-neutral-950/50 backdrop-blur-md px-6 py-4">
        <div className="flex items-center gap-4">
          <Link
            href="/dashboard"
            className="flex h-8 w-8 items-center justify-center rounded-full bg-neutral-900 text-neutral-400 transition-colors hover:bg-neutral-800 hover:text-white"
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
      </header>

      {/* Chat Area */}
      <div className="flex-1 overflow-y-auto px-4 py-6 sm:px-6">
        <div className="mx-auto max-w-4xl">
          {error && (
            <div className="mb-6 rounded-xl border border-red-500/20 bg-red-500/10 p-4 text-sm text-red-400 text-center">
              {error}
            </div>
          )}
          
          {messages.length === 0 ? (
            <EmptyChatState 
              userName={user?.first_name || "there"}
              onUpload={(base64, filename) => {
                sendPayload(
                  { type: "upload", file_data: base64, file_name: filename },
                  `Uploaded resume: ${filename}`
                );
              }}
              onCreateScratch={(data) => {
                sendPayload(
                  { type: "create_scratch", data: data },
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
          <div ref={messagesEndRef} className="h-4" />
        </div>
      </div>

      {/* Input Area (Only show when chat is active) */}
      {messages.length > 0 && (
        <div className="shrink-0 border-t border-neutral-900 bg-black p-4">
          <div className="mx-auto flex max-w-4xl justify-center">
            <ChatInput 
              onSendMessage={sendMessage} 
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
  );
}
