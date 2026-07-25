import { useState, useEffect, useRef, useCallback } from "react";
import { useAuth } from "@/context/AuthContext";

export type MessageRole = "human" | "ai";

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  ui?: string;
  options?: string[];
}

const SESSION_STORAGE_KEY = "chat_session_id";

function getOrCreateSessionId(userId: string): string {
  const storageKey = `${SESSION_STORAGE_KEY}_${userId}`;
  try {
    const stored = localStorage.getItem(storageKey);
    if (stored) return stored;
  } catch {
    // localStorage unavailable (SSR, private browsing, etc.)
  }
  const newId = crypto.randomUUID();
  try {
    localStorage.setItem(storageKey, newId);
  } catch {
    // Best-effort persist
  }
  return newId;
}

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isConnecting, setIsConnecting] = useState(true);
  const [isReceiving, setIsReceiving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const isReceivingRef = useRef(false);
  const currentMessageIdRef = useRef<string | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const pingIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const sessionIdRef = useRef<string>("");
  
  const { user } = useAuth();

  // Sync sessionIdRef when user changes — read from localStorage or create new
  useEffect(() => {
    if (user?.id) {
      sessionIdRef.current = getOrCreateSessionId(user.id);
    }
  }, [user?.id]);
  
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
            return;
          }
          
          if (payload.type === "metadata") {
            currentMessageIdRef.current = payload.message_id;
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
            const { node, data } = payload;
            
            if (data?.current_question?.question_text) {
              setMessages(prev => [
                ...prev,
                {
                  id: crypto.randomUUID(),
                  role: "ai",
                  content: data.current_question.question_text,
                  ui: data.current_question.ui,
                  options: data.current_question.options
                }
              ]);
            }
            // We silently ignore other node updates so we don't spam the chat UI
            // with "Finished processing: analyze_gaps"
            return;
          }
          
          if (payload.type === "done") {
            isReceivingRef.current = false;
            setIsReceiving(false);
            currentMessageIdRef.current = null;
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
        currentMessageIdRef.current = null;
        
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
    
    if (!payload.session_id) {
      payload.session_id = sessionIdRef.current;
    }
    
    wsRef.current.send(JSON.stringify(payload));
  }, []);

  const sendMessage = useCallback((content: string) => {
    sendPayload({ type: "message", content }, content);
  }, [sendPayload]);

  const stopGenerating = useCallback(() => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    
    wsRef.current.send(JSON.stringify({ type: "cancel" }));
    isReceivingRef.current = false;
    setIsReceiving(false);
  }, []);

  const resetSession = useCallback(() => {
    if (!user?.id) return;
    const storageKey = `${SESSION_STORAGE_KEY}_${user.id}`;
    const newId = crypto.randomUUID();
    sessionIdRef.current = newId;
    try {
      localStorage.setItem(storageKey, newId);
    } catch {
      // Best-effort persist
    }
    setMessages([]);
  }, [user?.id]);

  return {
    messages,
    isConnecting,
    isReceiving,
    error,
    sendMessage,
    sendPayload,
    stopGenerating,
    resetSession
  };
}
