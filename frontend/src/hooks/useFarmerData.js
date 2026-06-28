import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

export function useFarmerData(userId) {
  const [stats, setStats] = useState({});
  const [products, setProducts] = useState([]);
  const [orders, setOrders] = useState([]);
  const [cats, setCats] = useState([]);

  const load = useCallback(async () => {
    const results = await Promise.all([
      api.get("/dashboard/stats"),
      api.get("/products"),
      api.get("/orders"),
      api.get("/categories"),
    ]);
    setStats(results[0].data);
    setProducts(results[1].data.filter((item) => item.farmer_id === userId));
    setOrders(results[2].data);
    setCats(results[3].data);
    // 'userId' is the only reactive dep. 'api', setters, 'results' and 'item' are
    // either stable imports, stable React setters, or function-scope locals.
  }, [userId]);

  useEffect(() => { load(); }, [load]);

  return { stats, products, orders, cats, reload: load };
}
