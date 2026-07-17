import { useCallback, useEffect, useState } from "react";
import { getJson, api } from "@/lib/api";
import { toast } from "sonner";
import { Truck, Package, MapPin, CheckCircle2, KeyRound } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Card, CardContent, CardHeader, CardTitle,
} from "@/components/ui/card";

const STATUS_LABEL = {
  assigned: "Assigned",
  picked_up: "Picked up",
  out_for_delivery: "Out for delivery",
  delivered: "Delivered",
  failed: "Failed",
};

const STATUS_COLOR = {
  assigned: "bg-blue-100 text-blue-700",
  picked_up: "bg-amber-100 text-amber-700",
  out_for_delivery: "bg-orange-100 text-orange-700",
  delivered: "bg-green-100 text-green-700",
  failed: "bg-red-100 text-red-700",
};

// The lifecycle a partner can move a delivery through, in order. "delivered"
// requires OTP verification first (enforced by the backend too).
const NEXT_STATUS = {
  assigned: "picked_up",
  picked_up: "out_for_delivery",
  out_for_delivery: "delivered",
};

function DeliveryCard({ delivery, onAdvance, onVerifyOtp, busy }) {
  const [otp, setOtp] = useState("");
  const next = NEXT_STATUS[delivery.status];
  const needsOtpFirst = next === "delivered" && !delivery.otp_verified;

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-2 pb-2">
        <div>
          <CardTitle className="text-base">Order #{delivery.order_id.slice(-8)}</CardTitle>
          <p className="text-xs text-muted-foreground mt-1 flex items-center gap-1">
            <MapPin className="w-3 h-3" /> {delivery.method?.replace("_", " ")}
            {delivery.weight_kg ? ` · ${delivery.weight_kg} kg` : ""}
          </p>
        </div>
        <Badge className={STATUS_COLOR[delivery.status] || ""}>
          {STATUS_LABEL[delivery.status] || delivery.status}
        </Badge>
      </CardHeader>
      <CardContent className="space-y-3">
        {needsOtpFirst && (
          <div className="flex gap-2">
            <Input
              placeholder="Enter buyer's 6-digit delivery code"
              value={otp}
              maxLength={6}
              onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))}
            />
            <Button
              variant="secondary"
              disabled={busy || otp.length !== 6}
              onClick={() => onVerifyOtp(delivery.delivery_id, otp)}
            >
              <KeyRound className="w-4 h-4 mr-1" /> Verify
            </Button>
          </div>
        )}
        {next && !needsOtpFirst && (
          <Button
            className="w-full"
            disabled={busy}
            onClick={() => onAdvance(delivery.delivery_id, next)}
          >
            <CheckCircle2 className="w-4 h-4 mr-1" />
            Mark as {STATUS_LABEL[next]}
          </Button>
        )}
        {delivery.status === "delivered" && (
          <p className="text-sm text-green-700 flex items-center gap-1">
            <CheckCircle2 className="w-4 h-4" /> Delivered — job complete
          </p>
        )}
      </CardContent>
    </Card>
  );
}

export default function DeliveryDashboard() {
  const [deliveries, setDeliveries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState(null);

  const reload = useCallback(() => {
    getJson("/delivery/my")
      .then(setDeliveries)
      .catch((err) => {
        // eslint-disable-next-line no-console
        console.error("[DeliveryDashboard] failed to load deliveries:", err);
        toast.error("Couldn't load your deliveries");
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { reload(); }, [reload]);

  const advance = async (deliveryId, status) => {
    setBusyId(deliveryId);
    try {
      await api.patch(`/delivery/${deliveryId}/status`, { status });
      toast.success(`Marked as ${STATUS_LABEL[status]}`);
      reload();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Couldn't update status");
    } finally {
      setBusyId(null);
    }
  };

  const verifyOtp = async (deliveryId, code) => {
    setBusyId(deliveryId);
    try {
      await api.post(`/delivery/${deliveryId}/verify-otp`, { code });
      toast.success("Delivery code verified");
      reload();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Incorrect delivery code");
    } finally {
      setBusyId(null);
    }
  };

  const active = deliveries.filter((d) => d.status !== "delivered" && d.status !== "failed");
  const completed = deliveries.filter((d) => d.status === "delivered" || d.status === "failed");

  return (
    <div className="max-w-3xl mx-auto px-4 py-8">
      <div className="flex items-center gap-2 mb-1">
        <Truck className="w-6 h-6 text-primary" />
        <h1 className="text-2xl font-bold">Delivery Dashboard</h1>
      </div>
      <p className="text-muted-foreground mb-6">Your assigned deliveries</p>

      {loading ? (
        <p className="text-muted-foreground">Loading…</p>
      ) : deliveries.length === 0 ? (
        <div className="text-center py-16 text-muted-foreground border rounded-lg">
          <Package className="w-8 h-8 mx-auto mb-2 opacity-50" />
          No deliveries assigned to you yet.
        </div>
      ) : (
        <div className="space-y-6">
          {active.length > 0 && (
            <div>
              <h2 className="text-sm font-semibold text-muted-foreground mb-2 uppercase tracking-wide">
                Active ({active.length})
              </h2>
              <div className="grid gap-3 sm:grid-cols-2">
                {active.map((d) => (
                  <DeliveryCard
                    key={d.delivery_id}
                    delivery={d}
                    busy={busyId === d.delivery_id}
                    onAdvance={advance}
                    onVerifyOtp={verifyOtp}
                  />
                ))}
              </div>
            </div>
          )}
          {completed.length > 0 && (
            <div>
              <h2 className="text-sm font-semibold text-muted-foreground mb-2 uppercase tracking-wide">
                Completed ({completed.length})
              </h2>
              <div className="grid gap-3 sm:grid-cols-2">
                {completed.map((d) => (
                  <DeliveryCard
                    key={d.delivery_id}
                    delivery={d}
                    busy={false}
                    onAdvance={() => {}}
                    onVerifyOtp={() => {}}
                  />
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
