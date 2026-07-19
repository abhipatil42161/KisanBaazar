import { useEffect, useState } from "react";
import { getJson } from "@/lib/api";

const DEFAULTS = { platform_fee_percent: 1, delivery_charge: 0 };

/** Admin-configurable platform fee % and delivery charge, used to compute
 * cart/checkout totals consistently with what the backend will charge. */
export function useSiteSettings() {
  const [settings, setSettings] = useState(DEFAULTS);
  useEffect(() => {
    getJson("/settings").then(setSettings).catch(() => setSettings(DEFAULTS));
  }, []);
  return settings;
}

export function computeTotal(subtotal, settings) {
  const fee = Math.round(subtotal * ((settings.platform_fee_percent || 0) / 100));
  const delivery = settings.delivery_charge || 0;
  return { fee, delivery, total: Math.round(subtotal + fee + delivery) };
}
