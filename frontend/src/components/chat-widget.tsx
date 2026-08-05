"use client";

import { useState, useRef, useEffect, KeyboardEvent } from "react";
import { MessageCircle, X, Send, Bot, User, RotateCcw } from "lucide-react";

interface Message {
  id: number;
  role: "user" | "bot";
  text: string;
  /** Next steps offered under this reply. The backend picks them per intent so
   *  they never re-ask the question just answered. */
  suggestions?: string[];
}

let _id = 0;
const nextId = () => ++_id;

function RichText({ text }: { text: string }) {
  const lines = text.split("\n");
  return (
    <span className="block space-y-0.5">
      {lines.map((line, i) => {
        const parts = line.split(/(\*\*[^*]+\*\*)/g);
        return (
          <span key={i} className="block leading-relaxed">
            {parts.map((part, j) =>
              part.startsWith("**") && part.endsWith("**") ? (
                <strong key={j}>{part.slice(2, -2)}</strong>
              ) : (
                <span key={j}>{part}</span>
              )
            )}
          </span>
        );
      })}
    </span>
  );
}

function ThinkingDots() {
  return (
    <div className="flex items-center gap-1 px-1 py-1">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="w-2 h-2 rounded-full bg-muted-foreground/50 animate-bounce"
          style={{ animationDelay: `${i * 150}ms`, animationDuration: "900ms" }}
        />
      ))}
    </div>
  );
}

const SUGGESTED_QUESTIONS = [
  "Dashboard summary",
  "Any alerts?",
  "Monitors down?",
  "Show my websites",
  "Unknown scripts",
  "List my clients",
  "Recent changes",
  "Detected forms",
];

// Used when a reply arrives without its own suggestions — an older backend, or a
// network error. Leaving the user with a bare input box is the thing to avoid.
const FALLBACK_SUGGESTIONS = SUGGESTED_QUESTIONS.slice(0, 4);

const WELCOME: Message = {
  id: 0,
  role: "bot",
  text: "Hi! I'm your Digivault assistant 👋\n\nI can check website statuses, show script alerts, monitor uptime, look up client details, and more.\n\nTry one of the quick questions below, or type **help** to see everything I can do.",
  suggestions: SUGGESTED_QUESTIONS,
};

export function ChatWidget() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([WELCOME]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
      inputRef.current?.focus();
    }
  }, [open]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  async function send(text?: string) {
    const msg = (text ?? input).trim();
    if (!msg || loading) return;

    setMessages((prev) => [...prev, { id: nextId(), role: "user", text: msg }]);
    setInput("");
    setLoading(true);

    // A short floor so the thinking dots register as a beat rather than a flash.
    // This used to be 1200ms, which made every lookup feel slower than it was.
    const [res] = await Promise.all([
      fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: msg }),
      }).catch(() => null),
      new Promise((r) => setTimeout(r, 250)),
    ]);

    try {
      // The /api/chat route already unwraps the DRF envelope, so this is the
      // intent result itself. Do NOT reach for `.data` here — that is the
      // intent's own payload (domain, counts), not the reply.
      const data = res ? await res.json() : null;
      const reply: string =
        data?.reply ?? (res?.ok ? "Done!" : "Something went wrong. Please try again.");
      setMessages((prev) => [
        ...prev,
        {
          id: nextId(),
          role: "bot",
          text: reply,
          // Fall back to the opening questions rather than leaving a dead end if
          // the reply arrives without any.
          suggestions: data?.suggestions?.length ? data.suggestions : FALLBACK_SUGGESTIONS,
        },
      ]);
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          id: nextId(),
          role: "bot",
          text: "Network error. Please try again.",
          suggestions: FALLBACK_SUGGESTIONS,
        },
      ]);
    } finally {
      setLoading(false);
    }
  }

  function reset() {
    setMessages([WELCOME]);
    setInput("");
    inputRef.current?.focus();
  }

  function onKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  // Chips hang off the newest reply only. Keeping them under every past message
  // made the transcript a wall of buttons, and clicking an old one re-asked a
  // question whose context had moved on.
  const last = messages[messages.length - 1];
  const activeSuggestions =
    !loading && last?.role === "bot" ? last.suggestions ?? [] : [];

  return (
    <>
      {/* Floating toggle button */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="fixed bottom-6 right-6 z-50 flex items-center justify-center w-13 h-13 rounded-full bg-primary text-primary-foreground shadow-lg hover:bg-primary/90 transition-all hover:scale-105 active:scale-95"
        aria-label={open ? "Close chat" : "Open chat"}
      >
        {open ? <X className="h-5 w-5" /> : <MessageCircle className="h-5 w-5" />}
      </button>

      {/* Chat panel. Width is capped to the viewport so it does not run off the
          edge on a phone, where a fixed 380px is wider than the screen. */}
      {open && (
        <div className="fixed bottom-24 right-6 left-6 sm:left-auto z-50 sm:w-[380px] max-h-[70vh] sm:max-h-[560px] flex flex-col rounded-xl border bg-card shadow-2xl overflow-hidden">
          {/* Header */}
          <div className="flex items-center gap-2 px-4 py-3 border-b bg-primary/5">
            <div className="w-7 h-7 rounded-full bg-primary/15 flex items-center justify-center">
              <Bot className="h-4 w-4 text-primary" />
            </div>
            <div>
              <p className="font-semibold text-sm leading-none">Digivault Assistant</p>
              <p className="text-xs text-emerald-600 mt-0.5">● Online</p>
            </div>
            <div className="ml-auto flex items-center gap-1">
              {/* A long thread with a misunderstood question in it was previously
                  only clearable by reloading the page. */}
              {messages.length > 1 && (
                <button
                  onClick={reset}
                  title="Start over"
                  aria-label="Start over"
                  className="p-1 text-muted-foreground hover:text-foreground transition-colors"
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                </button>
              )}
              <button
                onClick={() => setOpen(false)}
                aria-label="Close chat"
                className="p-1 text-muted-foreground hover:text-foreground transition-colors"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto p-4 space-y-3 min-h-0">
            {messages.map((msg) => (
              <div
                key={msg.id}
                className={`flex gap-2 items-start ${msg.role === "user" ? "flex-row-reverse" : ""}`}
              >
                <div
                  className={`shrink-0 w-6 h-6 rounded-full flex items-center justify-center ${
                    msg.role === "bot"
                      ? "bg-primary/10 text-primary"
                      : "bg-muted text-muted-foreground"
                  }`}
                >
                  {msg.role === "bot" ? (
                    <Bot className="h-3.5 w-3.5" />
                  ) : (
                    <User className="h-3.5 w-3.5" />
                  )}
                </div>
                <div
                  className={`max-w-[82%] rounded-2xl px-3 py-2 text-sm ${
                    msg.role === "user"
                      ? "bg-primary text-primary-foreground rounded-tr-sm"
                      : "bg-muted text-foreground rounded-tl-sm"
                  }`}
                >
                  <RichText text={msg.text} />
                </div>
              </div>
            ))}

            {/* Thinking animation */}
            {loading && (
              <div className="flex gap-2 items-start">
                <div className="shrink-0 w-6 h-6 rounded-full flex items-center justify-center bg-primary/10 text-primary">
                  <Bot className="h-3.5 w-3.5" />
                </div>
                <div className="bg-muted rounded-2xl rounded-tl-sm px-3 py-2">
                  <ThinkingDots />
                </div>
              </div>
            )}

            {/* Next steps for the newest reply. Present after every answer, not
                just the welcome — that was the dead end. */}
            {activeSuggestions.length > 0 && (
              <div className="pt-1">
                <p className="text-xs text-muted-foreground mb-2">
                  {messages.length <= 1 ? "Quick questions:" : "What next?"}
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {activeSuggestions.map((q) => (
                    <button
                      key={q}
                      type="button"
                      onClick={() => send(q)}
                      className="text-xs px-2.5 py-1 rounded-full border border-primary/30 bg-primary/5 text-primary hover:bg-primary/10 transition-colors"
                    >
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            )}

            <div ref={bottomRef} />
          </div>

          {/* Input */}
          <div className="border-t px-3 py-2 flex gap-2 items-center bg-background">
            <input
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKey}
              placeholder="Ask me anything…"
              disabled={loading}
              className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground disabled:opacity-50"
            />
            <button
              onClick={() => send()}
              disabled={!input.trim() || loading}
              className="shrink-0 w-7 h-7 rounded-full flex items-center justify-center bg-primary text-primary-foreground disabled:opacity-40 hover:bg-primary/90 transition-colors"
              aria-label="Send"
            >
              <Send className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      )}
    </>
  );
}
