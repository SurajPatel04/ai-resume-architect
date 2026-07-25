"use client";

import { useState, useRef, useEffect } from "react";
import { SendHorizonal, Square } from "lucide-react";

interface ChatInputProps {
  onSendMessage: (message: string) => void;
  disabled?: boolean;
  onStop?: () => void;
}

export function ChatInput({ onSendMessage, disabled, onStop }: ChatInputProps) {
  const [input, setInput] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleSubmit = () => {
    if (input.trim() && !disabled) {
      onSendMessage(input.trim());
      setInput("");
      // Reset height
      if (textareaRef.current) {
        textareaRef.current.style.height = "auto";
      }
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${Math.min(
        textareaRef.current.scrollHeight,
        200
      )}px`;
    }
  }, [input]);

  return (
    <div className="relative flex w-full max-w-4xl flex-col items-end gap-2 p-2 rounded-2xl bg-neutral-900 border border-neutral-800 shadow-input">
      <textarea
        ref={textareaRef}
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Message AI Resume Architect..."
        disabled={disabled && !onStop}
        className="w-full resize-none bg-transparent px-3 py-2 text-sm text-white placeholder-neutral-500 focus:outline-none disabled:opacity-50 max-h-[200px]"
        rows={1}
      />
      {disabled && onStop ? (
        <button
          onClick={onStop}
          className="flex h-8 w-8 items-center justify-center rounded-xl bg-neutral-700 text-white transition-transform hover:scale-105 active:scale-95"
          title="Stop generating"
        >
          <Square size={14} fill="currentColor" />
        </button>
      ) : (
        <button
          onClick={handleSubmit}
          disabled={!input.trim() || disabled}
          className="flex h-8 w-8 items-center justify-center rounded-xl bg-white text-black transition-transform hover:scale-105 active:scale-95 disabled:opacity-30 disabled:hover:scale-100"
        >
          <SendHorizonal size={16} strokeWidth={2.5} />
        </button>
      )}
    </div>
  );
}
