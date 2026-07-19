import { useCallback, useEffect, useState } from "react";
import { getJson, api } from "@/lib/api";
import { Users, Package, ShoppingBag, IndianRupee, Search, ShieldAlert } from "lucide-react";
import { Input } from "@/components/ui/input";
import PaymentHistoryList, { fetchAdminPayments } from "@/components/PaymentHistoryList";
import ReviewList from "@/components/ReviewList";
import AdminUsersPanel from "@/components/admin/AdminUsersPanel";
import AdminProductsPanel from "@/components/admin/AdminProductsPanel";
import AdminOrdersPanel from "@/components/admin/AdminOrdersPanel";
import AdminSettingsPanel from "@/components/admin/AdminSettingsPanel";
import AdminCategoriesPanel from "@/components/admin/AdminCategoriesPanel";
import AdminBannersPanel from "@/components/admin/AdminBannersPanel";
import AdminDeliveryPanel from "@/components/admin/AdminDeliveryPanel";
import AdminSecurityPanel from "@/components/admin/AdminSecurityPanel";
import AdminWebsitePanel from "@/components/admin/AdminWebsitePanel";
import AdminActivityLogPanel from "@/components/admin/AdminActivityLogPanel";
import { useAuth } from "@/contexts/AuthContext";

const fetchAdminData = async () => {
  const [statsR, ordersR, paymentsR] = await Promise.allSettled([
    getJson("/dashboard/stats"), getJson("/orders"), fetchAdminPayments(),
  ]);
  return {
    stats: statsR.status === "fulfilled" ? statsR.value : {},
    orders: ordersR.status === "fulfilled" ? ordersR.value : [],
    payments: paymentsR.status === "fulfilled" ? paymentsR.value : [],
    errors: {
      stats: statsR.status === "rejected",
      orders: ordersR.status === "rejected",
      payments: paymentsR.status === "rejected",
    },
  };
};

const SECTIONS = [
  { id: "overview", label: "Overview" },
  { id: "users", label: "Users" },
  { id: "products", label: "Products" },
  { id: "orders", label: "Orders" },
  { id: "delivery", label: "Delivery" },
  { id: "settings", label: "Fees & Delivery", superAdminOnly: true },
  { id: "categories", label: "Categories" },
  { id: "banners", label: "Banners" },
  { id: "security", label: "Security", superAdminOnly: true },
  { id: "website", label: "Website", superAdminOnly: true },
  { id: "activity", label: "Activity Log", superAdminOnly: true },
];

export default function AdminDashboard() {
  const { user } = useAuth();
  const isSuperAdmin = user?.role === "super_admin";
  const visibleSections = SECTIONS.filter((s) => !s.superAdminOnly || isSuperAdmin);
  const [section, setSection] = useState("overview");
  const [data, setData] = useState({ stats: {}, orders: [], payments: [], errors: {} });
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
  useEffect(() => {
    if (!visibleSections.some((s) => s.id === section)) setSection("overview");
  }, [section, visibleSections]);

  const { stats, orders, payments, errors = {} } = data;
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

      <div className="flex gap-2 flex-wrap mt-5 mb-6 border-b border-border pb-4">
        {visibleSections.map((s) => (
          <button key={s.id} onClick={() => setSection(s.id)}
            className={`px-4 h-9 rounded-xl text-sm font-medium transition-colors ${
              section === s.id ? "bg-primary text-primary-foreground" : "bg-muted hover:bg-muted/70"
            }`}>
            {s.label}
          </button>
        ))}
      </div>

      {section === "users" && <AdminUsersPanel />}
      {section === "products" && <AdminProductsPanel />}
      {section === "orders" && <AdminOrdersPanel />}
      {section === "delivery" && <AdminDeliveryPanel />}
      {section === "settings" && <AdminSettingsPanel />}
      {section === "categories" && <AdminCategoriesPanel />}
      {section === "banners" && <AdminBannersPanel />}
      {section === "security" && <AdminSecurityPanel />}
      {section === "website" && <AdminWebsitePanel />}
      {section === "activity" && <AdminActivityLogPanel />}

      {section === "overview" && <>
      {errors.stats && <ErrorBanner label="dashboard stats" onRetry={reload} />}
      {errors.orders && <ErrorBanner label="orders" onRetry={reload} />}
      {errors.payments && <ErrorBanner label="payments" onRetry={reload} />}

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
      </>}
    </div>
  );
}

function ErrorBanner({ label, onRetry }) {
  return (
    <div className="bg-red-50 border-2 border-red-200 text-red-700 rounded-xl p-4 mb-4 flex items-center justify-between gap-3 text-sm font-medium">
      <span>Couldn't load {label} — showing what's available</span>
      <button onClick={onRetry} className="shrink-0 px-3 py-1.5 rounded-lg bg-red-100 hover:bg-red-200 text-red-800 text-xs font-semibold">
        Retry
      </button>
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
