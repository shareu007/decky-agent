import { createContext, useContext } from "react";
import type { ReactNode } from "react";
import type { Language } from "./types";
import { translator } from "./i18n";

const Locale = createContext<Language>("zh-CN");
export function LocaleProvider({ language = "zh-CN", children }: { language?: Language; children: ReactNode }) {
  return <Locale.Provider value={language}>{children}</Locale.Provider>;
}
export const useI18n = () => translator(useContext(Locale));
