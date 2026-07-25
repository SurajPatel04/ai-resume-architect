import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";
import type { ChatMessage as ChatMessageType } from "@/hooks/useChat";

interface ChatMessageProps {
  message: ChatMessageType;
  isReceiving?: boolean;
  onSendMessage?: (content: string) => void;
}

export function ChatMessage({ message, isReceiving, onSendMessage }: ChatMessageProps) {
  const isAi = message.role === "ai";

  return (
    <div
      className={cn(
        "flex w-full mb-6",
        isAi ? "justify-start" : "justify-end"
      )}
    >
      <div
        className={cn(
          "max-w-[85%] rounded-2xl px-5 py-4",
          isAi
            ? "bg-neutral-900/50 border border-neutral-800 text-neutral-200 shadow-sm"
            : "bg-white text-black shadow-sm"
        )}
      >
        {isAi && (
          <div className="flex items-center gap-2 mb-2 pb-2 border-b border-neutral-800">
            <div className="h-5 w-5 rounded bg-white flex items-center justify-center shrink-0">
              <svg
                width="12"
                height="12"
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
            <span className="text-xs font-bold uppercase tracking-widest text-neutral-400">
              AI Resume Architect
            </span>
          </div>
        )}

        <div
          className={cn(
            "prose prose-sm max-w-none break-words",
            isAi ? "prose-invert prose-p:leading-relaxed prose-pre:bg-neutral-950 prose-pre:border-neutral-800" : ""
          )}
        >
          {isAi ? (
            message.content ? (
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {message.content}
              </ReactMarkdown>
            ) : isReceiving ? (
              <div className="flex items-center gap-1.5 h-6">
                <span className="w-1.5 h-1.5 bg-neutral-500 rounded-full animate-bounce [animation-delay:-0.3s]"></span>
                <span className="w-1.5 h-1.5 bg-neutral-500 rounded-full animate-bounce [animation-delay:-0.15s]"></span>
                <span className="w-1.5 h-1.5 bg-neutral-500 rounded-full animate-bounce"></span>
              </div>
            ) : (
              <p className="opacity-50 italic">Empty response</p>
            )
          ) : (
            <p className="whitespace-pre-wrap font-medium">{message.content}</p>
          )}
        </div>

        {isAi && message.ui === "chips" && message.options && message.options.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-2">
            {message.options.map((opt, i) => (
              <button
                key={i}
                onClick={() => onSendMessage && onSendMessage(opt)}
                className="px-4 py-1.5 rounded-full text-sm font-medium bg-neutral-800 hover:bg-neutral-700 text-neutral-200 transition-colors border border-neutral-700 cursor-pointer"
              >
                {opt}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
