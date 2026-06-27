import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "@/lib/api";
import ProductCard from "@/components/ProductCard";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Search, SlidersHorizontal } from "lucide-react";

export default function Products() {
  const [sp, setSp] = useSearchParams();
  const [products, setProducts] = useState([]);
  const [cats, setCats] = useState([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState(sp.get("q") || "");

  const category = sp.get("category") || "";
  const organic = sp.get("organic") === "true";
  const exportReady = sp.get("export_ready") === "true";
  const auction = sp.get("auction") === "true";

  useEffect(() => {
    api.get("/categories").then((r) => setCats(r.data));
  }, []);

  useEffect(() => {
    setLoading(true);
    const params = {};
    if (sp.get("q")) params.q = sp.get("q");
    if (category) params.category = category;
    if (organic) params.organic = true;
    if (exportReady) params.export_ready = true;
    if (auction) params.auction = true;
    api.get("/products", { params }).then((r) => { setProducts(r.data); setLoading(false); });
  }, [sp]);

  const updateParam = (key, val) => {
    const next = new URLSearchParams(sp);
    if (val === "" || val === false || val === null) next.delete(key);
    else next.set(key, String(val));
    setSp(next);
  };

  const onSearch = (e) => { e.preventDefault(); updateParam("q", q); };

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <div className="flex flex-col lg:flex-row gap-8">
        {/* Sidebar filters */}
        <aside className="lg:w-72 lg:sticky lg:top-24 lg:self-start space-y-6">
          <div className="bg-card border-2 border-border rounded-2xl p-5">
            <h3 className="font-heading font-semibold text-lg flex items-center gap-2 mb-4">
              <SlidersHorizontal size={18} /> Filters
            </h3>
            <form onSubmit={onSearch} className="relative mb-5">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" size={16} />
              <Input data-testid="filter-search" value={q} onChange={(e) => setQ(e.target.value)}
                placeholder="Search..." className="pl-10 h-11 rounded-xl" />
            </form>
            <div className="space-y-2.5">
              <label className="flex items-center gap-2 cursor-pointer text-sm font-medium">
                <Checkbox data-testid="filter-organic" checked={organic}
                  onCheckedChange={(v) => updateParam("organic", v)} /> Organic only
              </label>
              <label className="flex items-center gap-2 cursor-pointer text-sm font-medium">
                <Checkbox data-testid="filter-export" checked={exportReady}
                  onCheckedChange={(v) => updateParam("export_ready", v)} /> Export grade
              </label>
              <label className="flex items-center gap-2 cursor-pointer text-sm font-medium">
                <Checkbox data-testid="filter-auction" checked={auction}
                  onCheckedChange={(v) => updateParam("auction", v)} /> Live auctions
              </label>
            </div>
            <div className="mt-5">
              <div className="text-sm font-semibold mb-2">Categories</div>
              <div className="flex flex-col gap-1 max-h-72 overflow-y-auto pr-1">
                <button data-testid="cat-all" onClick={() => updateParam("category", "")}
                  className={`text-left px-3 py-1.5 rounded-lg text-sm ${!category ? "bg-primary text-primary-foreground font-medium" : "hover:bg-muted"}`}>
                  All categories
                </button>
                {cats.map((c) => (
                  <button key={c.id} data-testid={`cat-${c.id}`} onClick={() => updateParam("category", c.id)}
                    className={`text-left px-3 py-1.5 rounded-lg text-sm ${category === c.id ? "bg-primary text-primary-foreground font-medium" : "hover:bg-muted"}`}>
                    {c.name}
                  </button>
                ))}
              </div>
            </div>
            <Button data-testid="filter-clear" variant="outline" className="w-full mt-5 rounded-xl"
              onClick={() => { setSp({}); setQ(""); }}>Clear all</Button>
          </div>
        </aside>

        {/* Grid */}
        <div className="flex-1">
          <div className="flex items-end justify-between mb-6">
            <div>
              <h1 className="font-heading font-bold text-3xl">Marketplace</h1>
              <p className="text-muted-foreground text-sm mt-1">{products.length} products found</p>
            </div>
          </div>
          {loading ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-5">
              {Array(6).fill(0).map((_, i) => (
                <div key={i} className="bg-muted rounded-2xl aspect-[4/3] animate-pulse" />
              ))}
            </div>
          ) : products.length === 0 ? (
            <div className="text-center py-20 text-muted-foreground">
              <p className="text-lg">No products match your filters.</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-5">
              {products.map((p, i) => <ProductCard key={p.product_id} p={p} index={i} />)}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
