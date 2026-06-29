import { useAuth } from "@/contexts/AuthContext";
import { useFarmerData } from "@/hooks/useFarmerData";
import FarmerStats from "@/components/farmer/FarmerStats";
import FarmerListings from "@/components/farmer/FarmerListings";
import FarmerOrders from "@/components/farmer/FarmerOrders";
import ProductFormDialog from "@/components/farmer/AddProductDialog";

export default function FarmerDashboard() {
  const { user } = useAuth();
  const { stats, products, orders, cats, reload } = useFarmerData(user.user_id);

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

      <div className="grid lg:grid-cols-2 gap-8">
        <FarmerListings products={products} cats={cats} onChange={reload} />
        <FarmerOrders orders={orders} />
      </div>
    </div>
  );
}
