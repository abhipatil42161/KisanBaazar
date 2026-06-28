import { useCallback, useEffect, useState } from "react";
import { getJson } from "@/lib/api";

// Module-scope: keeps the useCallback body free of Promise-callback params.
const fetchFarmerData = (userId) =>
  Promise.all([
    getJson("/dashboard/stats"),
    getJson("/products"),
    getJson("/orders"),
    getJson("/categories"),
  ]).then(([stats, products, orders, cats]) => ({
    stats,
    products: products.filter((item) => item.farmer_id === userId),
    orders,
    cats,
  }));

export function useFarmerData(userId) {
  const [data, setData] = useState({ stats: {}, products: [], orders: [], cats: [] });

  const load = useCallback(
    () => fetchFarmerData(userId).then(setData),
    [userId, setData],
  );

  useEffect(() => { load(); }, [load]);

  return { ...data, reload: load };
}
