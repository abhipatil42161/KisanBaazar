import { IndianRupee, Package, ShoppingBag } from "lucide-react";

function StatCard({ icon: Icon, label, value, color }) {
  return (
    <div className="bg-card border-2 border-border rounded-2xl p-5 flex items-center gap-4">
      <div className={`w-12 h-12 rounded-xl ${color} flex items-center justify-center text-white`}>
        <Icon size={22} strokeWidth={2.5} />
      </div>
      <div>
        <div className="text-xs text-muted-foreground font-medium">{label}</div>
        <div className="font-heading font-bold text-2xl">{value}</div>
      </div>
    </div>
  );
}

export default function FarmerStats({ stats }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-8">
      <StatCard icon={Package} label="Active Listings" value={stats.products || 0} color="bg-emerald-500" />
      <StatCard icon={ShoppingBag} label="Orders Received" value={stats.orders || 0} color="bg-amber-500" />
      <StatCard icon={IndianRupee} label="Total Revenue" value={`₹${(stats.revenue || 0).toLocaleString()}`} color="bg-primary" />
    </div>
  );
}
