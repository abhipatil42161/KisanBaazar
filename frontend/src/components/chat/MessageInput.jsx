import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Send } from "lucide-react";

export default function MessageInput({ value, onChange, onSend, disabled }) {
  return (
    <div className="border-t border-border p-3 flex gap-2">
      <Input
        data-testid="ai-chat-input"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && onSend()}
        placeholder="Ask about crops, prices, schemes..."
        className="rounded-xl h-11"
        disabled={disabled}
      />
      <Button
        data-testid="ai-chat-send"
        onClick={onSend}
        disabled={disabled || !value.trim()}
        className="rounded-xl h-11 bg-primary hover:bg-primary/90"
      >
        <Send size={18} />
      </Button>
    </div>
  );
}
