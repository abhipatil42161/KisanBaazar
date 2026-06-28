import { Sparkles, X } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function ChatHeader({ onClose }) {
  return (
    <div className="px-5 py-4 bg-primary text-primary-foreground flex items-center justify-between">
      <div className="flex items-center gap-2">
        <Sparkles size={20} strokeWidth={2.5} />
        <div>
          <div className="font-heading font-semibold">KisanBaazar AI</div>
          <div className="text-xs opacity-80">Powered by Claude</div>
        </div>
      </div>
      <Button
        data-testid="ai-chat-close"
        variant="ghost"
        size="icon"
        onClick={onClose}
        className="text-primary-foreground hover:bg-white/10 rounded-xl"
      >
        <X size={20} />
      </Button>
    </div>
  );
}
