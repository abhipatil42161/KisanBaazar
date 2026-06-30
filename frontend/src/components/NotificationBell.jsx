import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { logger } from "@/lib/logger";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem,
  DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Bell, CheckCheck, CheckCircle2, AlertTriangle, RotateCcw } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";

const KIND_ICONS = {
  "payment.captured": CheckCircle2,
  "payment.failed": AlertTriangle,
  "refund.processed": RotateCcw,
};
const KIND_COLORS = {
  "payment.captured": "text-primary",
  "payment.failed": "text-destructive",
  "refund.processed": "text-amber-500",
};

/** Polled in-app notifications bell. Polls every 45s while authenticated. */
export default function NotificationBell() {
  const { user } = useAuth();
  const nav = useNavigate();
  const [items, setItems] = useState([]);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);

  const load = useCallback(async () => {
    if (!user) return;
    try {
      const { data } = await api.get("/notifications");
      setItems(data.items || []);
      setUnread(data.unread || 0);
    } catch (err) { logger.warn("[notifications] load failed", err?.message); }
  }, [user]);

  useEffect(() => {
    if (!user) return;
    load();
    const id = setInterval(load, 45000);
    return () => clearInterval(id);
  }, [user, load]);

  const onOpen = async (next) => {
    setOpen(next);
    if (next && unread > 0) {
      try {
        await api.post("/notifications/read-all");
        setUnread(0);
        setItems((prev) => prev.map((n) => ({ ...n, read: true })));
      } catch (err) { logger.warn("[notifications] read-all failed", err?.message); }
    }
  };

  if (!user) return null;

  return (
    <DropdownMenu open={open} onOpenChange={onOpen}>
      <DropdownMenuTrigger asChild>
        <Button data-testid="notif-bell" variant="ghost" size="icon" className="rounded-xl h-11 w-11 relative">
          <Bell size={20} strokeWidth={2.5} />
          {unread > 0 && (
            <span data-testid="notif-unread-badge"
              className="absolute -top-1 -right-1 bg-destructive text-destructive-foreground text-[10px] rounded-full min-w-[18px] h-[18px] px-1 flex items-center justify-center font-bold">
              {unread > 9 ? "9+" : unread}
            </span>
          )}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-[340px] max-h-[440px] overflow-y-auto" data-testid="notif-dropdown">
        <DropdownMenuLabel className="flex items-center justify-between">
          <span>Notifications</span>
          {items.length > 0 && (
            <span className="text-xs text-muted-foreground inline-flex items-center gap-1">
              <CheckCheck size={12} /> all read
            </span>
          )}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {items.length === 0 ? (
          <div className="py-8 text-center text-sm text-muted-foreground" data-testid="notif-empty">
            No notifications yet
          </div>
        ) : items.map((n) => {
          const Icon = KIND_ICONS[n.kind] || Bell;
          return (
            <DropdownMenuItem
              key={n.notification_id}
              data-testid={`notif-item-${n.notification_id}`}
              onClick={() => { if (n.link) nav(n.link); setOpen(false); }}
              className="flex items-start gap-3 py-3 cursor-pointer"
            >
              <Icon size={18} className={`shrink-0 mt-0.5 ${KIND_COLORS[n.kind] || "text-foreground"}`} />
              <div className="flex-1 min-w-0">
                <div className="font-medium text-sm truncate">{n.title}</div>
                <div className="text-xs text-muted-foreground line-clamp-2">{n.body}</div>
              </div>
            </DropdownMenuItem>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
