import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

export function useFarmerData(userId) {
  const [stats, setStats] = useState({});
  const [products, setProducts] = useState([]);
  const [orders, setOrders] = useState([]);
  const [cats, setCats] = useState([]);

  const load = useCallback(async () => {
    const [s, p, o, c] = await Promise.all([
      api.get("/dashboard/stats"),
      api.get("/products"),
      api.get("/orders"),
      api.get("/categories"),
    ]);
    setStats(s.data);
    setProducts(p.data.filter((x) => x.farmer_id === userId));
    setOrders(o.data);
    setCats(c.data);
  }, [userId]);

  useEffect(() => { load(); }, [load]);

  return { stats, products, orders, cats, reload: load };
}
