"use client";

import { useState, useRef, useEffect } from "react";
import { Mic, SendHorizonal, Square } from "lucide-react";
import { cn } from "@/lib/utils";
import { AudioBars } from "./AudioBars";

interface ChatInputProps {
  onSendMessage: (message: string) => void;
  onSendVoice?: (audio: string, mimetype: string) => void;
  disabled?: boolean;
  onStop?: () => void;
}

export function ChatInput({ onSendMessage, onSendVoice, disabled, onStop }: ChatInputProps) {
  const [input, setInput] = useState("");
  const [isRecording, setIsRecording] = useState(false);
  const [micError, setMicError] = useState<string | null>(null);
  // Held in state, not just on the recorder, so the level meter can tap the same stream.
  const [stream, setStream] = useState<MediaStream | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

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

  const startRecording = async () => {
    setMicError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };

      recorder.onstop = () => {
        // Release the mic indicator as soon as we have the audio.
        stream.getTracks().forEach((track) => track.stop());
        // Unmounts the meter, which closes its AudioContext.
        setStream(null);

        const blob = new Blob(chunksRef.current, { type: recorder.mimeType });
        const reader = new FileReader();
        reader.onloadend = () => onSendVoice?.(reader.result as string, recorder.mimeType);
        reader.readAsDataURL(blob);
      };

      recorder.start();
      recorderRef.current = recorder;
      setStream(stream);
      setIsRecording(true);
    } catch {
      setMicError("Microphone unavailable. Check the browser's permission for this site.");
    }
  };

  const stopRecording = () => {
    recorderRef.current?.stop();
    recorderRef.current = null;
    setIsRecording(false);
  };

  // Never leave the mic hot if the component goes away mid-recording.
  useEffect(() => {
    return () => {
      recorderRef.current?.stream.getTracks().forEach((track) => track.stop());
      recorderRef.current?.stop();
    };
  }, []);

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
      {micError && (
        <p className="w-full px-3 text-left text-xs text-red-400">{micError}</p>
      )}

      {stream && (
        <div className="flex w-full items-center gap-3 px-3">
          <AudioBars stream={stream} />
          <span className="text-xs text-neutral-400">
            Listening — tap the mic to send
          </span>
        </div>
      )}

      <div className="flex items-center gap-2">
        {onSendVoice && (
          <button
            onClick={isRecording ? stopRecording : startRecording}
            disabled={disabled && !isRecording}
            aria-label={isRecording ? "Stop recording and send" : "Record an answer"}
            aria-pressed={isRecording}
            title={isRecording ? "Stop recording and send" : "Record an answer"}
            className={cn(
              "flex h-8 w-8 items-center justify-center rounded-xl transition-transform hover:scale-105 active:scale-95 disabled:opacity-30 disabled:hover:scale-100",
              isRecording
                ? "bg-red-500 text-white animate-pulse"
                : "bg-neutral-800 text-neutral-300"
            )}
          >
            <Mic size={16} strokeWidth={2.5} />
          </button>
        )}

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
    </div>
  );
}