import { useEffect, useState } from "react";
import { getJson } from "@/lib/api";

const DEFAULTS = {
  site_name: "KisanBaazar",
  site_description: "Connecting India's farmers directly to the world. Transparent. Trusted. Trade.",
  logo_url: null,
  contact_email: "hello@kisanbaazar.in",
  contact_phone: "1800-KISAN-00",
  contact_address: "Pune, Maharashtra",
  footer_text: "Made with 🌾 for Indian farmers",
  social_links: { facebook: "", instagram: "", twitter: "", youtube: "", whatsapp: "" },
};

export function useSiteContent() {
  const [content, setContent] = useState(DEFAULTS);
  useEffect(() => {
    getJson("/site-content").then(setContent).catch(() => setContent(DEFAULTS));
  }, []);
  return content;
}
