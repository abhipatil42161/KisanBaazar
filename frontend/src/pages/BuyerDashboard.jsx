import { useEffect, useState } from "react";
import { getJson } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { ShoppingBag, Heart, Package } from "lucide-react";
import { Link } from "react-router-dom";

// Module-scope fetcher.
const fetchBuyerData = () =>
  Promise.all([
    getJson("/dashboard/stats"),
    getJson("/orders"),
    getJson("/wishlist"),
  ]).then(([stats, orders, wishlist]) => ({ stats, orders, wishlist }));

export default function BuyerDashboard() {
  const { user } = useAuth();
  const [data, setData] = useState({ stats: {}, orders: [], wishlist: [] });

  useEffect(() => {
    fetchBuyerData().then(setData);
  }, [setData]);

  const { stats, orders } = data;

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <h1 className="font-heading font-bold text-3xl">Welcome back, {user.name}</h1>
      <p className="text-muted-foreground mt-1">Your orders, saved products & insights.</p>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mt-6 mb-8">
        <Stat icon={ShoppingBag} label="Total Orders" value={stats.orders || 0} color="bg-primary" />
        <Stat icon={Heart} label="Wishlist" value={stats.wishlist || 0} color="bg-rose-500" />
        <Stat icon={Package} label="Pending" value={orders.filter((o) => o.status === "placed").length} color="bg-amber-500" />
      </div>

      <h2 className="font-heading font-semibold text-xl mb-3">My Orders</h2>
      <div className="space-y-3">
        {orders.length === 0 && <p className="text-muted-foreground">No orders yet. <Link to="/products" className="text-primary font-semibold">Start shopping</Link></p>}
        {orders.map((o) => (
          <div key={o.order_id} data-testid={`order-${o.order_id}`} className="bg-card border-2 border-border rounded-2xl p-5">
            <div className="flex justify-between flex-wrap gap-2">
              <div>
                <div className="font-semibold">Order #{o.order_id.slice(-10)}</div>
                <div className="text-xs text-muted-foreground">{new Date(o.created_at).toLocaleString()}</div>
              </div>
              <div className="text-right">
                <div className="font-heading font-bold text-xl text-primary">₹{o.total.toLocaleString()}</div>
                <div className="text-xs capitalize">{o.status} · {o.payment_status}</div>
              </div>
            </div>
            <div className="mt-3 text-sm text-muted-foreground">{o.items.map((it) => `${it.title} × ${it.qty}`).join(" · ")}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function Stat({ icon: Icon, label, value, color }) {
  return (
    <div className="bg-card border-2 border-border rounded-2xl p-5 flex items-center gap-4">
      <div className={`w-12 h-12 rounded-xl ${color} flex items-center justify-center text-white`}><Icon size={22} /></div>
      <div><div className="text-xs text-muted-foreground">{label}</div><div className="font-heading font-bold text-2xl">{value}</div></div>
    </div>
  );
}
