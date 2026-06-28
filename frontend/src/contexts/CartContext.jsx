import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

const CartContext = createContext();
export const useCart = () => useContext(CartContext);

export const CartProvider = ({ children }) => {
  const [items, setItems] = useState(() => {
    try { return JSON.parse(localStorage.getItem("kb_cart") || "[]"); }
    catch { return []; }
  });

  useEffect(() => {
    localStorage.setItem("kb_cart", JSON.stringify(items));
    // 'items' is the only reactive dep; localStorage is a global.
  }, [items]);

  const add = useCallback((product, qty = null) => {
    const q = qty ?? product.moq ?? 1;
    setItems((arr) => {
      const idx = arr.findIndex((it) => it.product_id === product.product_id);
      if (idx >= 0) {
        const copy = [...arr];
        copy[idx] = { ...copy[idx], qty: copy[idx].qty + q };
        return copy;
      }
      return [...arr, {
        product_id: product.product_id, title: product.title,
        price: product.price, qty: q, image: product.images?.[0],
        unit: product.unit, farmer_name: product.farmer_name,
      }];
    });
    toast.success(`Added ${product.title} to cart`);
    // 'setItems' is stable; 'toast' is a module import; remaining identifiers are
    // function-scope locals and callback params.
  }, []);

  const remove = useCallback(
    (pid) => setItems((arr) => arr.filter((it) => it.product_id !== pid)),
    // 'setItems' is stable; 'pid'/'arr'/'it' are callback params.
    []
  );
  const updateQty = useCallback(
    (pid, qty) => setItems((arr) => arr.map((it) => it.product_id === pid ? { ...it, qty: Math.max(1, qty) } : it)),
    // 'setItems' is stable; 'pid'/'qty'/'arr'/'it'/Math are callback params or globals.
    []
  );
  const clear = useCallback(() => setItems([]), []);

  const total = items.reduce((sum, it) => sum + it.price * it.qty, 0);
  const count = items.reduce((sum, it) => sum + it.qty, 0);

  const value = useMemo(
    () => ({ items, add, remove, updateQty, clear, total, count }),
    [items, add, remove, updateQty, clear, total, count],
  );

  return <CartContext.Provider value={value}>{children}</CartContext.Provider>;
};
