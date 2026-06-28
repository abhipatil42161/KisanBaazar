import { useEffect, useState } from "react";
import { getJson } from "@/lib/api";
import ProductCard from "@/components/ProductCard";
import { Globe2, FileCheck2, Ship, Container } from "lucide-react";

export default function ExporterDashboard() {
  const [products, setProducts] = useState([]);

  useEffect(() => {
    getJson("/products?export_ready=true").then(setProducts);
  }, [setProducts]);

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <h1 className="font-heading font-bold text-3xl">Exporter Dashboard</h1>
      <p className="text-muted-foreground mt-1">Discover export-ready Indian produce.</p>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mt-6 mb-8">
        <Action icon={Globe2} label="Export-ready products" value={products.length} />
        <Action icon={FileCheck2} label="Certifications" value="APEDA · FSSAI · USDA" />
        <Action icon={Ship} label="Shipping partners" value="Maersk · MSC · DHL" />
        <Action icon={Container} label="Containers tracked" value="0" />
      </div>

      <h2 className="font-heading font-semibold text-xl mb-3">Export-Ready Catalog</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-5">
        {products.map((p, i) => <ProductCard key={p.product_id} p={p} index={i} />)}
      </div>
    </div>
  );
}

function Action({ icon: Icon, label, value }) {
  return (
    <div className="bg-card border-2 border-border rounded-2xl p-5">
      <Icon className="text-primary mb-2" size={22} />
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="font-heading font-bold text-lg mt-0.5">{value}</div>
    </div>
  );
}
