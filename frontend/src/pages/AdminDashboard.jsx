import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Users, Package, ShoppingBag, IndianRupee } from "lucide-react";

export default function AdminDashboard() {
  const [stats, setStats] = useState({});
  const [orders, setOrders] = useState([]);

  useEffect(() => {
    Promise.all([api.get("/dashboard/stats"), api.get("/orders")]).then(([s, o]) => {
      setStats(s.data); setOrders(o.data);
    });
  }, []);

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
      <div className="bg-card border-2 border-border rounded-2xl overflow-hidden">
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
                <td className="p-3 font-semibold">₹{o.total.toLocaleString()}</td>
                <td className="p-3 capitalize">{o.status}</td>
                <td className="p-3 capitalize">{o.payment_status}</td>
              </tr>
            ))}
            {orders.length === 0 && <tr><td colSpan={5} className="p-6 text-center text-muted-foreground">No orders yet</td></tr>}
          </tbody>
        </table>
      </div>
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
