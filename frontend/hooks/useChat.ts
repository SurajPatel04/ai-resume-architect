import { useState, useEffect, useRef, useCallback } from "react";
import { useAuth } from "@/context/AuthContext";
import { uploadResume } from "@/lib/api/chat";
import type { Resume } from "@/types/resume";

export type MessageRole = "human" | "ai";

/** One weak bullet on the impact gate's card, as it is drawn. */
export interface ImpactGap {
  /** "Current bullet 2 — Projects: InsightFlow" */
  label: string;
  /** What the resume says today. */
  original: string;
  /** Why it was picked out — "describes a duty rather than an achievement". */
  reason: string;
  /** The proposed rewrite, `{}` marking the blank. Empty when none was usable. */
  template: string;
}

/** Whatever a `ui` needs beyond a list of chips. */
export interface MessageMeta {
  /**
   * "metric": the whole rewritten bullet, with `{}` marking the one spot the
   * candidate's figure goes — "…lifting success to {}%.".
   */
  template?: string;
  /** "impact_gate": every weak bullet, each with its own blank to fill in. */
  gaps?: ImpactGap[];
}

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  ui?: string;
  options?: string[];
  meta?: MessageMeta;
}

/** A saved conversation, as returned by the backend's `list_sessions`. */
export interface ChatSession {
  session_id: string;
  title: string;
  updated_at: string;
}

export interface TokenUsage {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
}

export interface AtsFeedback {
  matched_keywords?: string[];
  missing_keywords?: string[];
  feedback?: string;
}

export interface QualityFactor {
  name: string;
  score: number;
  max_score: number;
  advice: string;
}

/** The slice of graph state the UI renders outside the message list. */
export interface ResumeSnapshot {
  completion: number;
  phase?: string;
  pdfPath?: string;
  atsScore?: number;
  atsFeedback?: AtsFeedback;
  qualityScore?: number;
  qualityFeedback?: QualityFactor[];
  profile?: Resume;
  /**
   * The entry the question on screen is about, so the panel can point at it rather than
   * leaving the user to work out which of six bullets we mean. `field` is the backend's
   * own path ("experience[0]"); bulletIndex is set only when one exact line is in
   * question. Cleared the moment a node reports no current question.
   */
  focus?: { field: string; bulletIndex: number | null };
}

const EMPTY_SNAPSHOT: ResumeSnapshot = { completion: 0 };

const SESSION_STORAGE_KEY = "chat_session_id";

function storageKeyFor(userId: string): string {
  return `${SESSION_STORAGE_KEY}_${userId}`;
}

function persistSessionId(userId: string, sessionId: string): void {
  try {
    localStorage.setItem(storageKeyFor(userId), sessionId);
  } catch {
    // Best-effort persist
  }
}

function getOrCreateSessionId(userId: string): string {
  try {
    const stored = localStorage.getItem(storageKeyFor(userId));
    if (stored) return stored;
  } catch {
    // localStorage unavailable (SSR, private browsing, etc.)
  }
  const newId = crypto.randomUUID();
  persistSessionId(userId, newId);
  return newId;
}

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [sessionId, setSessionId] = useState<string>("");
  const [isConnecting, setIsConnecting] = useState(true);
  const [isReceiving, setIsReceiving] = useState(false);
  // The graph node currently running, so the waiting state can say what it's doing.
  const [activeNode, setActiveNode] = useState<string | null>(null);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [snapshot, setSnapshot] = useState<ResumeSnapshot>(EMPTY_SNAPSHOT);
  const [turnUsage, setTurnUsage] = useState<TokenUsage | null>(null);
  const [sessionUsage, setSessionUsage] = useState<TokenUsage | null>(null);
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const isReceivingRef = useRef(false);
  const currentMessageIdRef = useRef<string | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const pingIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const sessionIdRef = useRef<string>("");
  const historyRequestedRef = useRef(false);

  const { user } = useAuth();
  const userId = user?.id;

  // Sync sessionIdRef when user changes — read from localStorage or create new
  useEffect(() => {
    if (userId) {
      sessionIdRef.current = getOrCreateSessionId(userId);
      setSessionId(sessionIdRef.current);
    }
  }, [userId]);

  const send = useCallback((payload: object): boolean => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) return false;
    wsRef.current.send(JSON.stringify(payload));
    return true;
  }, []);

  const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000/api/v1/chat/ws";
  const MAX_RECONNECT_ATTEMPTS = 10;

  const connect = useCallback(async () => {
    if (!user?.id) return;

    // Don't reconnect if we already have an open or connecting socket
    if (wsRef.current && (wsRef.current.readyState === WebSocket.OPEN || wsRef.current.readyState === WebSocket.CONNECTING)) {
      return;
    }

    setIsConnecting(true);
    setError(null);

    try {
      const ws = new WebSocket(WS_URL);

      ws.onopen = () => {
        console.log("[useChat] Connected");
        setIsConnecting(false);
        setError(null);
        reconnectAttemptsRef.current = 0;

        // The session list also tells us whether the current session exists
        // server-side, which is what gates the history request below.
        ws.send(JSON.stringify({ type: "list_sessions" }));

        // Start heartbeat
        if (pingIntervalRef.current) clearInterval(pingIntervalRef.current);
        pingIntervalRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: "ping" }));
          }
        }, 30000);
      };

      ws.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);

          if (payload.type === "pong") {
            return; // Heartbeat ack
          }

          if (payload.type === "error") {
            console.error("[useChat] Server error:", payload.reason);
            // Don't set the main error state for transient message errors unless it's a fatal close code
            if (payload.code === 4401) {
              // Token expired, let onclose handle the refresh
              return;
            }
            if (!payload.message_id) {
              setError(payload.reason || "Server error");
            }
            // A graph failure used to leave the optimistic upload bubble under an
            // infinite spinner. An error ends the active turn just like `done` does.
            isReceivingRef.current = false;
            setIsReceiving(false);
            setActiveNode(null);
            return;
          }

          if (payload.type === "metadata") {
            currentMessageIdRef.current = payload.message_id;
            if (payload.title === "Parsing Resume...") setActiveNode("parse_document");
            return;
          }

          if (payload.type === "sessions") {
            const list: ChatSession[] = payload.sessions || [];
            setSessions(list);

            // Only ask for history once we know the session was actually saved —
            // the backend answers "Session not found" for a freshly minted id.
            // Once per connection: the list also refreshes after every turn, and
            // re-hydrating then would remount the whole transcript mid-chat.
            if (!historyRequestedRef.current && list.some(s => s.session_id === sessionIdRef.current)) {
              historyRequestedRef.current = true;
              setIsLoadingHistory(true);
              ws.send(JSON.stringify({ type: "history", session_id: sessionIdRef.current }));
            }
            return;
          }

          if (payload.type === "notice") {
            // e.g. an uploaded PDF that couldn't be parsed. The backend also stores
            // it as an assistant message, so on reload it comes back via history.
            setMessages(prev => [
              ...prev,
              { id: crypto.randomUUID(), role: "ai", content: payload.reason },
            ]);
            return;
          }

          if (payload.type === "usage") {
            setTurnUsage(payload.turn);
            setSessionUsage(payload.session);
            return;
          }

          if (payload.type === "transcript") {
            // What Deepgram heard, echoed back so the user sees their own turn
            // before the graph starts answering it.
            setMessages(prev => [
              ...prev,
              { id: crypto.randomUUID(), role: "human", content: payload.text },
            ]);
            return;
          }

          if (payload.type === "history") {
            setIsLoadingHistory(false);
            // Ignore a reply for a session the user has already switched away from.
            if (payload.session_id !== sessionIdRef.current) return;

            setMessages(
              (payload.messages || []).map((m: {
                role: string; content: string; ui?: string; options?: string[]; meta?: MessageMeta;
              }) => ({
                id: crypto.randomUUID(),
                role: m.role === "user" ? "human" : "ai",
                content: m.content,
                ui: m.ui,
                options: m.options,
                // Without this a reloaded session redraws a "metric" question as a bare
                // text box, having forgotten what it was asking for a number of.
                meta: m.meta,
              } as ChatMessage))
            );

            setSnapshot({
              completion: payload.completion ?? 0,
              phase: payload.phase,
              pdfPath: payload.pdf_path,
              atsScore: payload.ats_score,
              atsFeedback: payload.ats_feedback,
              qualityScore: payload.quality_score,
              qualityFeedback: payload.quality_feedback,
              profile: payload.master_profile,
              // A resumed session lands mid-question, so the highlight has to come back
              // with it — the last message on screen is still asking about that entry.
              focus: payload.current_question?.field
                ? {
                  field: payload.current_question.field,
                  bulletIndex: payload.current_question.bullet_index ?? null,
                }
                : undefined,
            });
            setSessionUsage(payload.usage ?? null);
            setTurnUsage(null);
            return;
          }

          if (payload.type === "delta") {
            const { message_id, data } = payload;

            setMessages(prev => {
              const newMessages = [...prev];
              // Find the AI message we're currently appending to
              const aiMsgIndex = newMessages.findIndex(m => m.id === message_id);

              if (aiMsgIndex !== -1) {
                newMessages[aiMsgIndex] = {
                  ...newMessages[aiMsgIndex],
                  content: newMessages[aiMsgIndex].content + data,
                };
              } else {
                // If it doesn't exist, create it (should happen when receiving first delta)
                newMessages.push({
                  id: message_id,
                  role: "ai",
                  content: data,
                });
              }

              return newMessages;
            });
            return;
          }

          if (payload.type === "message") {
            setMessages(prev => [
              ...prev,
              {
                id: crypto.randomUUID(),
                role: "ai",
                content: payload.content
              }
            ]);
            return;
          }

          if (payload.type === "graph_update") {
            const { data } = payload;

            setActiveNode(payload.node ?? null);

            if (data?.current_question?.question_text) {
              setMessages(prev => [
                ...prev,
                {
                  id: crypto.randomUUID(),
                  role: "ai",
                  content: data.current_question.question_text,
                  ui: data.current_question.ui,
                  options: data.current_question.options,
                  meta: data.current_question.meta ?? undefined
                }
              ]);
            }

            // Nodes report their slice of state, so merge rather than replace —
            // analyze_gaps sends completion, render_resume sends pdf_path, and so on.
            setSnapshot(prev => {
              const next = { ...prev };
              if (typeof data?.completion === "number") next.completion = data.completion;
              if (data?.phase) next.phase = data.phase;
              if (data?.pdf_path) next.pdfPath = data.pdf_path;
              if (typeof data?.ats_score === "number") next.atsScore = data.ats_score;
              if (data?.ats_feedback) next.atsFeedback = data.ats_feedback;
              if (typeof data?.quality_score === "number") next.qualityScore = data.quality_score;
              if (data?.quality_feedback) next.qualityFeedback = data.quality_feedback;
              if (data?.master_profile) next.profile = data.master_profile;
              // Presence, not truthiness: a node reporting `current_question: null` is
              // saying the question was answered, and the highlight has to come off.
              if (data && "current_question" in data) {
                const q = data.current_question;
                next.focus = q?.field
                  ? { field: q.field, bulletIndex: q.bullet_index ?? null }
                  : undefined;
              }
              // The tailored version is what actually gets rendered, so prefer it.
              if (data?.generated_resumes?.tailored) next.profile = data.generated_resumes.tailored;
              return next;
            });

            // Everything else stays out of the chat log so we don't spam it
            // with "Finished processing: analyze_gaps"
            return;
          }

          if (payload.type === "done") {
            isReceivingRef.current = false;
            setIsReceiving(false);
            setActiveNode(null);
            currentMessageIdRef.current = null;
            // A new session only gets a row after its first turn, and every turn
            // bumps updated_at — so the sidebar needs a refresh either way.
            ws.send(JSON.stringify({ type: "list_sessions" }));
            return;
          }

        } catch (e) {
          console.error("[useChat] Failed to parse message:", e, event.data);
        }
      };

      ws.onclose = async (event) => {
        console.log("[useChat] Closed:", event.code, event.reason);
        wsRef.current = null;
        setIsConnecting(true);
        isReceivingRef.current = false;
        setIsReceiving(false);
        setActiveNode(null);
        setIsLoadingHistory(false);
        currentMessageIdRef.current = null;
        // Redraw the transcript from the DB once we're back.
        historyRequestedRef.current = false;

        if (pingIntervalRef.current) {
          clearInterval(pingIntervalRef.current);
        }

        // Handle Token Expiry
        if (event.code === 4401) {
          console.log("[useChat] Token expired.");
          setError("Session expired. Please log in again.");
          return;
        }

        // Handle connection limit
        if (event.code === 4400) {
          setError("You already have an active chat connection in another tab.");
          return;
        }

        // Normal reconnect with exponential backoff
        if (!event.wasClean && event.code !== 1000) {
          if (reconnectAttemptsRef.current < MAX_RECONNECT_ATTEMPTS) {
            const backoff = Math.min(1000 * Math.pow(2, reconnectAttemptsRef.current), 30000);
            reconnectAttemptsRef.current++;
            console.log(`[useChat] Reconnecting in ${backoff}ms (attempt ${reconnectAttemptsRef.current})`);

            if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
            reconnectTimeoutRef.current = setTimeout(connect, backoff);
            setError("Connection lost. Reconnecting...");
          } else {
            setError("Failed to reconnect to chat server. Please refresh the page.");
          }
        }
      };

      ws.onerror = (e) => {
        console.error("[useChat] WebSocket error:", e);
      };

      wsRef.current = ws;
    } catch (e) {
      console.error("[useChat] Failed to create WebSocket:", e);
      setError("Failed to connect to chat server");
    }
  }, [user?.id, WS_URL]); // Only depend on user.id, not the full user object

  useEffect(() => {
    connect();

    return () => {
      if (wsRef.current) {
        wsRef.current.close(1000, "Component unmounted");
        wsRef.current = null;
      }
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      if (pingIntervalRef.current) clearInterval(pingIntervalRef.current);
    };
  }, [connect]);

  const sendPayload = useCallback((payload: any, optimisticMessage?: string) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      setError("Not connected to chat server");
      return;
    }

    if (optimisticMessage) {
      const humanMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: "human",
        content: optimisticMessage
      };
      setMessages(prev => [...prev, humanMsg]);
    }

    isReceivingRef.current = true;
    setIsReceiving(true);
    // A fresh turn starts generic; the first graph_update names what's actually running.
    setActiveNode(null);

    if (!payload.session_id) {
      payload.session_id = sessionIdRef.current;
    }

    wsRef.current.send(JSON.stringify(payload));
  }, []);

  const sendMessage = useCallback((content: string) => {
    sendPayload({ type: "message", content }, content);
  }, [sendPayload]);

  /**
   * POST the file, then tell the socket to pick it up by id. Two steps, but the
   * bytes go over HTTP where they can be streamed to disk and size-checked.
   */
  const sendUpload = useCallback(async (file: File) => {
    setError(null);
    setIsUploading(true);
    try {
      const { upload_id, file_name } = await uploadResume(file);
      sendPayload(
        { type: "upload", upload_id, file_name },
        `Uploaded resume: ${file_name}`
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setIsUploading(false);
    }
  }, [sendPayload]);

  /**
   * Ship a recording to the backend, which transcribes it with Deepgram and feeds
   * the text into the graph like any typed answer. No optimistic bubble — the
   * `transcript` reply carries the actual words.
   */
  const sendVoice = useCallback((audio: string, mimetype: string) => {
    sendPayload({ type: "voice", audio, mimetype });
  }, [sendPayload]);

  const stopGenerating = useCallback(() => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;

    wsRef.current.send(JSON.stringify({ type: "cancel" }));
    isReceivingRef.current = false;
    setIsReceiving(false);
    setActiveNode(null);
  }, []);

  /** Point the hook at `id` and pull that conversation's transcript from the DB. */
  const switchSession = useCallback((id: string) => {
    if (!userId || !id) return;
    if (isReceivingRef.current) stopGenerating();

    sessionIdRef.current = id;
    setSessionId(id);
    persistSessionId(userId, id);
    setMessages([]);
    setError(null);
    setSnapshot(EMPTY_SNAPSHOT);
    setTurnUsage(null);
    setSessionUsage(null);
    historyRequestedRef.current = true;
    setIsLoadingHistory(true);

    if (!send({ type: "history", session_id: id })) {
      // Socket is down; onopen will re-hydrate from list_sessions instead.
      historyRequestedRef.current = false;
      setIsLoadingHistory(false);
    }
  }, [userId, send, stopGenerating]);

  /** Start an empty conversation. It gets a DB row on its first turn. */
  const newSession = useCallback(() => {
    if (!userId) return;
    if (isReceivingRef.current) stopGenerating();

    const id = crypto.randomUUID();
    sessionIdRef.current = id;
    setSessionId(id);
    persistSessionId(userId, id);
    setMessages([]);
    setError(null);
    setSnapshot(EMPTY_SNAPSHOT);
    setTurnUsage(null);
    setSessionUsage(null);
    historyRequestedRef.current = true;
    setIsLoadingHistory(false);
  }, [userId, stopGenerating]);

  return {
    messages,
    sessions,
    sessionId,
    isConnecting,
    isReceiving,
    activeNode,
    isLoadingHistory,
    isUploading,
    snapshot,
    turnUsage,
    sessionUsage,
    error,
    sendMessage,
    sendPayload,
    sendUpload,
    sendVoice,
    stopGenerating,
    switchSession,
    newSession
  };
}