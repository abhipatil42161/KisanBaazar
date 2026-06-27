import { createContext, useContext, useState } from "react";
import { t as translate } from "@/lib/i18n";

const LanguageContext = createContext();
export const useLanguage = () => useContext(LanguageContext);

export const LanguageProvider = ({ children }) => {
  const [lang, setLang] = useState(() => localStorage.getItem("kb_lang") || "en");

  const setLanguage = (l) => {
    setLang(l);
    localStorage.setItem("kb_lang", l);
  };

  const t = (key) => translate(lang, key);

  return <LanguageContext.Provider value={{ lang, setLanguage, t }}>{children}</LanguageContext.Provider>;
};
