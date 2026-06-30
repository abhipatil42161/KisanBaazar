import { useState } from "react";
import { api, getJson } from "@/lib/api";
import { logger } from "@/lib/logger";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { Download, RotateCcw, CheckCircle2, XCircle, Clock, Receipt } from "lucide-react";

const RAZORPAY_SDK = "https://checkout.razorpay.com/v1/checkout.js";
const loadRazorpay = () => new Promise((resolve) => {
  if (typeof window === "undefined") return resolve(false);
  if (window.Razorpay) return resolve(true);
  const existing = document.querySelector(`script[src="${RAZORPAY_SDK}"]`);
  if (existing) {
    existing.addEventListener("load", () => resolve(true), { once: true });
    existing.addEventListener("error", () => resolve(false), { once: true });
    return;
  }
  const s = document.createElement("script");
  s.src = RAZORPAY_SDK; s.async = true;
  s.onload = () => resolve(true); s.onerror = () => resolve(false);
  document.body.appendChild(s);
});

const STATUS_META = {
  captured: { icon: CheckCircle2, color: "text-primary", label: "Captured" },
  refunded: { icon: RotateCcw, color: "text-amber-500", label: "Refunded" },
  refund_initiated: { icon: Clock, color: "text-amber-500", label: "Refund initiated" },
  failed: { icon: XCircle, color: "text-destructive", label: "Failed" },
  cod_pending: { icon: Clock, color: "text-muted-foreground", label: "COD pending" },
};

export const downloadInvoice = async (orderId) => {
  try {
    const res = await api.get(`/orders/${orderId}/invoice`, { responseType: "blob" });
    const blob = new Blob([res.data], { type: "application/pdf" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `invoice_${orderId}.pdf`;
    document.body.appendChild(a); a.click();
    a.remove(); URL.revokeObjectURL(url);
  } catch (err) {
    toast.error(err?.response?.data?.detail || "Invoice not available");
  }
};

export const retryFailedPayment = async (order, { user, onPaid } = {}) => {
  try {
    const { data: fresh } = await api.post(`/orders/${order.order_id}/retry-payment`);
    const { data: cfg } = await api.get("/payments/config");
    if (!cfg.enabled) {
      // Fall back to mock-pay
      await api.post(`/orders/${order.order_id}/pay`);
      toast.success("Payment recorded (mock)");
      onPaid?.();
      return;
    }
    const loaded = await loadRazorpay();
    if (!loaded) { toast.error("Could not load Razorpay"); return; }
    return new Promise((resolve) => {
      const rzp = new window.Razorpay({
        key: cfg.key_id,
        amount: fresh.razorpay_amount_paise,
        currency: "INR",
        order_id: fresh.razorpay_order_id,
        name: "KisanBaazar",
        description: `Retry payment · ${order.order_id}`,
        prefill: { name: user?.name || "", email: user?.email || "", contact: user?.phone || "" },
        theme: { color: "#16a34a" },
        modal: { ondismiss: () => { toast.message("Payment cancelled"); resolve(); } },
        handler: async (resp) => {
          try {
            await api.post(`/orders/${order.order_id}/verify`, {
              razorpay_order_id: resp.razorpay_order_id,
              razorpay_payment_id: resp.razorpay_payment_id,
              razorpay_signature: resp.razorpay_signature,
            });
            toast.success("Payment successful!");
            onPaid?.();
          } catch (err) {
            toast.error(err?.response?.data?.detail || "Verification failed");
          } finally { resolve(); }
        },
      });
      rzp.on("payment.failed", () => { toast.error("Payment failed"); resolve(); });
      rzp.open();
    });
  } catch (err) {
    toast.error(err?.response?.data?.detail || "Retry failed");
    logger.warn("[retry-payment]", err?.message);
  }
};

export default function PaymentHistoryList({ payments, role = "buyer", onRefund }) {
  const [busy, setBusy] = useState(null);

  if (!payments || payments.length === 0) {
    return (
      <div className="text-sm text-muted-foreground py-8 text-center" data-testid="payments-empty">
        No payments yet.
      </div>
    );
  }

  const handleRefund = async (pmt) => {
    if (!window.confirm(`Refund ₹${pmt.amount?.toLocaleString()} for ${pmt.order_id}?`)) return;
    setBusy(pmt.razorpay_payment_id);
    try {
      await api.post(`/admin/payments/${pmt.razorpay_payment_id}/refund`, { reason: "admin_initiated" });
      toast.success("Refund initiated");
      onRefund?.();
    } catch (err) {
      toast.error(err?.response?.data?.detail || "Refund failed");
    } finally { setBusy(null); }
  };

  return (
    <div className="space-y-3" data-testid="payment-history-list">
      {payments.map((p) => {
        const meta = STATUS_META[p.status] || { icon: Receipt, color: "text-muted-foreground", label: p.status };
        const Icon = meta.icon;
        return (
          <div key={p.razorpay_payment_id || p.payment_id}
            data-testid={`payment-row-${p.razorpay_payment_id || p.payment_id}`}
            className="bg-card border-2 border-border rounded-2xl p-5 flex items-center gap-4 flex-wrap">
            <Icon size={28} className={`${meta.color} shrink-0`} />
            <div className="flex-1 min-w-[200px]">
              <div className="font-semibold">
                {role === "farmer" && p.farmer_amount != null
                  ? `Your share: ₹${p.farmer_amount.toLocaleString()}`
                  : `₹${(p.amount || 0).toLocaleString()}`}
                <span className="text-xs text-muted-foreground ml-2">{meta.label}</span>
              </div>
              <div className="text-xs text-muted-foreground mt-1">
                Order <span className="font-mono">{p.order_id}</span>
                {p.razorpay_payment_id && <> · <span className="font-mono">{p.razorpay_payment_id}</span></>}
              </div>
              <div className="text-xs text-muted-foreground">{p.created_at ? new Date(p.created_at).toLocaleString() : ""}</div>
            </div>
            <div className="flex gap-2 ml-auto">
              {role !== "farmer" && p.status === "captured" && (
                <Button data-testid={`download-invoice-${p.order_id}`} size="sm" variant="outline"
                  onClick={() => downloadInvoice(p.order_id)} className="rounded-xl">
                  <Download size={14} className="mr-1" /> Invoice
                </Button>
              )}
              {role === "admin" && p.status === "captured" && (
                <Button data-testid={`refund-${p.razorpay_payment_id}`} size="sm" variant="destructive"
                  disabled={busy === p.razorpay_payment_id}
                  onClick={() => handleRefund(p)} className="rounded-xl">
                  <RotateCcw size={14} className="mr-1" /> {busy === p.razorpay_payment_id ? "..." : "Refund"}
                </Button>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** Fetcher convenience — used by dashboards. */
export const fetchMyPayments = () => getJson("/payments");
export const fetchAdminPayments = () => getJson("/admin/payments");
export const fetchFarmerPayments = () => getJson("/farmer/payments");
