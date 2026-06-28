import { useRef, useState } from "react";
import { Sparkles } from "lucide-react";
import { API } from "@/lib/api";
import ChatHeader from "@/components/chat/ChatHeader";
import MessageList from "@/components/chat/MessageList";
import MessageInput from "@/components/chat/MessageInput";

const INITIAL_MESSAGE = {
  id: "greet",
  role: "ai",
  text: "Namaste! I'm your KisanBaazar AI. Ask me about crop prices, organic certification, export procedures, or government schemes.",
};

function useChatStream() {
  const [messages, setMessages] = useState([INITIAL_MESSAGE]);
  const [streaming, setStreaming] = useState(false);
  const sessionRef = useRef(null);
  const msgIdRef = useRef(1);

  const send = async (text) => {
    const trimmed = text.trim();
    if (!trimmed || streaming) return;
    const userId = `u-${msgIdRef.current++}`;
    const aiId = `a-${msgIdRef.current++}`;
    setMessages((m) => [...m, { id: userId, role: "user", text: trimmed }, { id: aiId, role: "ai", text: "" }]);
    setStreaming(true);
    try {
      const res = await fetch(`${API}/ai/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: trimmed, session_id: sessionRef.current }),
      });
      sessionRef.current = res.headers.get("X-Session-Id") || sessionRef.current;
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunk = decoder.decode(value, { stream: true });
        setMessages((m) => m.map((msg) => (msg.id === aiId ? { ...msg, text: msg.text + chunk } : msg)));
      }
    } catch {
      setMessages((m) => m.map((msg) => (msg.id === aiId ? { ...msg, text: "Sorry, I'm unavailable. Please try again." } : msg)));
    } finally {
      setStreaming(false);
    }
  };

  return { messages, streaming, send };
}

export default function AIChat() {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const { messages, streaming, send } = useChatStream();

  const handleSend = async () => {
    const text = input;
    setInput("");
    await send(text);
  };

  if (!open) {
    return (
      <button
        data-testid="ai-chat-open"
        onClick={() => setOpen(true)}
        className="fixed bottom-24 right-6 z-50 w-16 h-16 rounded-full bg-primary text-primary-foreground shadow-2xl hover:scale-110 transition-transform flex items-center justify-center group"
      >
        <Sparkles size={26} strokeWidth={2.5} />
        <span className="absolute right-full mr-3 bg-card border border-border px-3 py-1.5 rounded-xl text-sm font-medium whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity">
          Ask AI
        </span>
      </button>
    );
  }

  return (
    <div className="fixed bottom-24 right-6 z-50 w-[min(92vw,400px)] h-[min(80vh,600px)] bg-card border-2 border-border rounded-3xl shadow-2xl flex flex-col overflow-hidden">
      <ChatHeader onClose={() => setOpen(false)} />
      <MessageList messages={messages} />
      <MessageInput value={input} onChange={setInput} onSend={handleSend} disabled={streaming} />
    </div>
  );
}
