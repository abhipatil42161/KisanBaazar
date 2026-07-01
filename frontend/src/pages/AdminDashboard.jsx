import { useCallback, useEffect, useState } from "react";
import { getJson, api } from "@/lib/api";
import { Users, Package, ShoppingBag, IndianRupee, Search, ShieldAlert } from "lucide-react";
import { Input } from "@/components/ui/input";
import PaymentHistoryList, { fetchAdminPayments } from "@/components/PaymentHistoryList";
import ReviewList from "@/components/ReviewList";

const fetchAdminData = () =>
  Promise.all([getJson("/dashboard/stats"), getJson("/orders"), fetchAdminPayments()])
    .then(([stats, orders, payments]) => ({ stats, orders, payments }));

export default function AdminDashboard() {
  const [data, setData] = useState({ stats: {}, orders: [], payments: [] });
  const [tab, setTab] = useState("all"); // all | captured | failed | refunded
  const [q, setQ] = useState("");
  const [reviews, setReviews] = useState([]);
  const reload = useCallback(() => { fetchAdminData().then(setData); }, []);
  const loadReviews = useCallback(() => {
    api.get("/admin/reviews?status=reported")
      .then((r) => setReviews(r.data || []))
      .catch(() => setReviews([]));
  }, []);
  useEffect(() => { reload(); loadReviews(); }, [reload, loadReviews]);

  const { stats, orders, payments } = data;
  const needle = q.trim().toLowerCase();
  const filtered = payments
    .filter((p) => tab === "all" || p.status === tab)
    .filter((p) => !needle
      || (p.order_id || "").toLowerCase().includes(needle)
      || (p.razorpay_payment_id || "").toLowerCase().includes(needle)
      || (p.razorpay_order_id || "").toLowerCase().includes(needle)
      || (p.buyer_name || "").toLowerCase().includes(needle)
      || (p.method || "").toLowerCase().includes(needle));
  const TABS = [
    { id: "all", label: `All (${payments.length})` },
    { id: "captured", label: `Captured (${payments.filter((p) => p.status === "captured").length})` },
    { id: "failed", label: `Failed (${payments.filter((p) => p.status === "failed").length})` },
    { id: "refunded", label: `Refunded (${payments.filter((p) => p.status === "refunded").length})` },
  ];

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <h1 className="font-heading font-bold text-3xl">Admin Dashboard</h1>
      <p className="text-muted-foreground mt-1">Platform overview</p>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mt-6 mb-8">
        <S icon={Users} label="Users" value={stats.users || 0} color="bg-blue-500" />
        <S icon={Package} label="Products" value={stats.products || 0} color="bg-emerald-500" />
        <S icon={ShoppingBag} label="Orders" value={stats.orders || 0} color="bg-amber-500" />
        <S icon={IndianRupee} label="Revenue" value={`₹${(stats.revenue || 0).toLocaleString()}`} color="bg-primary" />
      </div>

      <h2 className="font-heading font-semibold text-xl mb-3">Recent Orders</h2>
      <div className="bg-card border-2 border-border rounded-2xl overflow-hidden mb-10">
        <table className="w-full text-sm">
          <thead className="bg-muted/50">
            <tr className="text-left">
              <th className="p-3">Order</th><th className="p-3">Buyer</th><th className="p-3">Total</th><th className="p-3">Status</th><th className="p-3">Payment</th>
            </tr>
          </thead>
          <tbody>
            {orders.map((o) => (
              <tr key={o.order_id} className="border-t border-border">
                <td className="p-3 font-mono text-xs">{o.order_id.slice(-10)}</td>
                <td className="p-3">{o.buyer_name}</td>
                <td className="p-3 font-semibold">₹{(o.charge_total ?? o.total).toLocaleString()}</td>
                <td className="p-3 capitalize">{o.status}</td>
                <td className="p-3 capitalize">{o.payment_status}</td>
              </tr>
            ))}
            {orders.length === 0 && <tr><td colSpan={5} className="p-6 text-center text-muted-foreground">No orders yet</td></tr>}
          </tbody>
        </table>
      </div>

      <h2 className="font-heading font-semibold text-xl mb-3">Payment Management</h2>
      <div className="flex flex-col sm:flex-row gap-3 mb-4">
        <div className="relative flex-1">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input
            data-testid="admin-payment-search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search by order ID, payment ID, buyer name, or method…"
            className="pl-9 h-10 rounded-xl"
          />
        </div>
        <div className="flex gap-2 flex-wrap" data-testid="admin-payment-tabs">
          {TABS.map((t) => (
            <button key={t.id} data-testid={`admin-payment-tab-${t.id}`}
              onClick={() => setTab(t.id)}
              className={`px-4 h-10 rounded-xl text-sm font-medium transition-colors ${
                tab === t.id ? "bg-primary text-primary-foreground" : "bg-muted hover:bg-muted/70"
              }`}>{t.label}</button>
          ))}
        </div>
      </div>
      {needle && (
        <p className="text-xs text-muted-foreground mb-3" data-testid="admin-payment-result-count">
          {filtered.length} of {payments.length} matching "{q}"
        </p>
      )}
      <PaymentHistoryList payments={filtered} role="admin" onRefund={reload} />

      <h2 className="font-heading font-semibold text-xl mb-3 mt-10 flex items-center gap-2">
        <ShieldAlert className="text-amber-500" size={20} />
        Review Moderation
        <span className="text-xs text-muted-foreground font-normal">({reviews.length} reported)</span>
      </h2>
      <ReviewList reviews={reviews} role="admin" onChange={loadReviews} showProductTitle />
    </div>
  );
}

function S({ icon: Icon, label, value, color }) {
  return (
    <div className="bg-card border-2 border-border rounded-2xl p-5">
      <div className={`w-10 h-10 rounded-xl ${color} flex items-center justify-center text-white mb-3`}><Icon size={20} /></div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="font-heading font-bold text-2xl">{value}</div>
    </div>
  );
}
