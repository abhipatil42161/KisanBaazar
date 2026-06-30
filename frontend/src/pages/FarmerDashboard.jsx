import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";
import { useFarmerData } from "@/hooks/useFarmerData";
import FarmerStats from "@/components/farmer/FarmerStats";
import FarmerListings from "@/components/farmer/FarmerListings";
import FarmerOrders from "@/components/farmer/FarmerOrders";
import ProductFormDialog from "@/components/farmer/AddProductDialog";
import PaymentHistoryList, { fetchFarmerPayments } from "@/components/PaymentHistoryList";

export default function FarmerDashboard() {
  const { user } = useAuth();
  const { stats, products, orders, cats, reload } = useFarmerData(user.user_id);
  const [payments, setPayments] = useState([]);

  const loadPayments = useCallback(() => {
    fetchFarmerPayments().then(setPayments).catch(() => setPayments([]));
  }, []);
  useEffect(() => { loadPayments(); }, [loadPayments]);

  const totalEarned = payments
    .filter((p) => p.status === "captured")
    .reduce((s, p) => s + (p.farmer_amount || 0), 0);
  const settled = payments
    .filter((p) => p.settlement_status === "settled")
    .reduce((s, p) => s + (p.farmer_amount || 0), 0);

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <div className="flex items-end justify-between flex-wrap gap-3 mb-8">
        <div>
          <h1 className="font-heading font-bold text-3xl">Farmer Dashboard</h1>
          <p className="text-muted-foreground mt-1">Welcome, {user.name} 🌾</p>
        </div>
        <ProductFormDialog cats={cats} onSaved={reload} />
      </div>

      <FarmerStats stats={stats} />

      <div className="grid lg:grid-cols-2 gap-8 mb-10">
        <FarmerListings products={products} cats={cats} onChange={reload} />
        <FarmerOrders orders={orders} />
      </div>

      <h2 className="font-heading font-semibold text-xl mb-3">Received Payments</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
        <div className="bg-card border-2 border-border rounded-2xl p-5">
          <div className="text-xs text-muted-foreground">Total received</div>
          <div className="font-heading font-bold text-2xl text-primary" data-testid="farmer-total-received">
            ₹{totalEarned.toLocaleString()}
          </div>
        </div>
        <div className="bg-card border-2 border-border rounded-2xl p-5">
          <div className="text-xs text-muted-foreground">Settled to bank</div>
          <div className="font-heading font-bold text-2xl" data-testid="farmer-settled">
            ₹{settled.toLocaleString()}
            <span className="text-xs font-normal text-muted-foreground ml-2">
              (pending settlements appear after T+2 from Razorpay)
            </span>
          </div>
        </div>
      </div>
      <PaymentHistoryList payments={payments} role="farmer" />
    </div>
  );
}
