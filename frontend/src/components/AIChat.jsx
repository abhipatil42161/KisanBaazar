import { useState, useRef, useEffect } from "react";
import { MessageCircle, X, Send, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { API } from "@/lib/api";

export default function AIChat() {
  const [open, setOpen] = useState(false);
  const [msgs, setMsgs] = useState([
    { id: "greet", role: "ai", text: "Namaste! I'm your KisanBaazar AI. Ask me about crop prices, organic certification, export procedures, or government schemes." },
  ]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const scrollRef = useRef(null);
  const sessionRef = useRef(null);
  const msgIdRef = useRef(1);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [msgs]);

  const send = async () => {
    const text = input.trim();
    if (!text || streaming) return;
    setInput("");
    const userId = `u-${msgIdRef.current++}`;
    const aiId = `a-${msgIdRef.current++}`;
    setMsgs((m) => [...m, { id: userId, role: "user", text }, { id: aiId, role: "ai", text: "" }]);
    setStreaming(true);

    try {
      const res = await fetch(`${API}/ai/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, session_id: sessionRef.current }),
      });
      sessionRef.current = res.headers.get("X-Session-Id") || sessionRef.current;
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunk = decoder.decode(value, { stream: true });
        setMsgs((m) => m.map((msg) => msg.id === aiId ? { ...msg, text: msg.text + chunk } : msg));
      }
    } catch {
      setMsgs((m) => m.map((msg) => msg.id === aiId ? { ...msg, text: "Sorry, I'm unavailable. Please try again." } : msg));
    } finally {
      setStreaming(false);
    }
  };

  return (
    <>
      {!open && (
        <button data-testid="ai-chat-open" onClick={() => setOpen(true)}
          className="fixed bottom-24 right-6 z-50 w-16 h-16 rounded-full bg-primary text-primary-foreground shadow-2xl hover:scale-110 transition-transform flex items-center justify-center group">
          <Sparkles size={26} strokeWidth={2.5} />
          <span className="absolute right-full mr-3 bg-card border border-border px-3 py-1.5 rounded-xl text-sm font-medium whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity">
            Ask AI
          </span>
        </button>
      )}

      {open && (
        <div className="fixed bottom-24 right-6 z-50 w-[min(92vw,400px)] h-[min(80vh,600px)] bg-card border-2 border-border rounded-3xl shadow-2xl flex flex-col overflow-hidden">
          <div className="px-5 py-4 bg-primary text-primary-foreground flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Sparkles size={20} strokeWidth={2.5} />
              <div>
                <div className="font-heading font-semibold">KisanBaazar AI</div>
                <div className="text-xs opacity-80">Powered by Claude</div>
              </div>
            </div>
            <Button data-testid="ai-chat-close" variant="ghost" size="icon" onClick={() => setOpen(false)}
              className="text-primary-foreground hover:bg-white/10 rounded-xl">
              <X size={20} />
            </Button>
          </div>

          <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-3">
            {msgs.map((m) => (
              <div key={m.id} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                <div className={`max-w-[85%] px-4 py-2.5 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap ${
                  m.role === "user" ? "bg-primary text-primary-foreground rounded-br-sm" : "bg-muted rounded-bl-sm"
                }`}>
                  {m.text || <span className="opacity-50">…</span>}
                </div>
              </div>
            ))}
          </div>

          <div className="border-t border-border p-3 flex gap-2">
            <Input data-testid="ai-chat-input" value={input} onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && send()}
              placeholder="Ask about crops, prices, schemes..."
              className="rounded-xl h-11" disabled={streaming} />
            <Button data-testid="ai-chat-send" onClick={send} disabled={streaming || !input.trim()}
              className="rounded-xl h-11 bg-primary hover:bg-primary/90">
              <Send size={18} />
            </Button>
          </div>
        </div>
      )}
    </>
  );
}
