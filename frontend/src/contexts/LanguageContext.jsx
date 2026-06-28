import { createContext, useCallback, useContext, useMemo, useState } from "react";
import { t as translate } from "@/lib/i18n";

const LanguageContext = createContext();
export const useLanguage = () => useContext(LanguageContext);

export const LanguageProvider = ({ children }) => {
  const [lang, setLang] = useState(() => localStorage.getItem("kb_lang") || "en");

  const setLanguage = useCallback((nextLang) => {
    setLang(nextLang);
    localStorage.setItem("kb_lang", nextLang);
  }, [setLang]);

  const t = useCallback((key) => translate(lang, key), [lang]);

  const value = useMemo(() => ({ lang, setLanguage, t }), [lang, setLanguage, t]);

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
};
