import { useEffect, useState } from "react";
import { getJson, api } from "@/lib/api";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Package, MapPin } from "lucide-react";

const NEXT_STATUS = {
  assigned: "picked_up",
  picked_up: "in_transit",
  in_transit: "out_for_delivery",
  out_for_delivery: "delivered",
};

const STATUS_LABEL = {
  pending: "Waiting for assignment",
  assigned: "Assigned — start pickup",
  picked_up: "Picked up",
  in_transit: "In transit",
  out_for_delivery: "Out for delivery",
  delivered: "Delivered",
};

export default function DeliveryDashboard() {
  const [deliveries, setDeliveries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [otpInputs, setOtpInputs] = useState({});

  const load = () => getJson("/delivery/my-deliveries").then(setDeliveries).catch(() => toast.error("Couldn't load deliveries")).finally(() => setLoading(false));
  useEffect(() => { load(); }, []);

  const advance = async (d) => {
    const next = NEXT_STATUS[d.status];
    if (!next) return;
    const body = { status: next };
    if (next === "delivered") {
      const otp = otpInputs[d.delivery_id];
      if (!otp || otp.length !== 6) return toast.error("Ask the buyer for their 6-digit delivery OTP");
      body.otp = otp;
    }
    try {
      const updated = await api.patch(`/delivery/${d.delivery_id}/status`, body).then((r) => r.data);
      setDeliveries((prev) => prev.map((x) => (x.delivery_id === d.delivery_id ? updated : x)));
      toast.success(`Marked as ${STATUS_LABEL[next]}`);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Couldn't update status");
    }
  };

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <h1 className="font-heading font-bold text-3xl">My Deliveries</h1>
      <p className="text-muted-foreground mt-1">Orders assigned to you for local delivery</p>

      <div className="space-y-4 mt-6">
        {deliveries.map((d) => (
          <div key={d.delivery_id} className="bg-card border-2 border-border rounded-2xl p-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="font-heading font-semibold flex items-center gap-2"><Package size={16} /> Order {d.order_id.slice(-8)}</p>
                <p className="text-sm text-muted-foreground mt-1 flex items-center gap-1"><MapPin size={14} /> PIN {d.buyer_pincode || "—"}</p>
              </div>
              <Badge variant={d.status === "delivered" ? "secondary" : "default"}>{STATUS_LABEL[d.status]}</Badge>
            </div>
            {d.status !== "delivered" && d.status !== "pending" && (
              <div className="mt-4 flex items-center gap-2">
                {NEXT_STATUS[d.status] === "delivered" && (
                  <Input placeholder="6-digit OTP from buyer" maxLength={6}
                    value={otpInputs[d.delivery_id] || ""}
                    onChange={(e) => setOtpInputs((s) => ({ ...s, [d.delivery_id]: e.target.value }))}
                    className="h-10 rounded-xl max-w-[160px]" />
                )}
                <Button size="sm" className="h-10 rounded-xl" onClick={() => advance(d)}>
                  Mark as {STATUS_LABEL[NEXT_STATUS[d.status]]}
                </Button>
              </div>
            )}
          </div>
        ))}
        {!loading && deliveries.length === 0 && (
          <div className="text-center text-muted-foreground py-16">No deliveries assigned to you yet.</div>
        )}
      </div>
    </div>
  );
}
