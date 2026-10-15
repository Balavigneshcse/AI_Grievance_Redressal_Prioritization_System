import i18n from "i18next"
import { initReactI18next } from "react-i18next"
import en from "@/i18n/en.json"
import ta from "@/i18n/ta.json"
import hi from "@/i18n/hi.json"

export const LANG_KEY = "synapse_lang"

export type Lang = "en" | "ta" | "hi"

export const LANGS: { code: Lang; label: string; nativeLabel: string }[] = [
  { code: "en", label: "English", nativeLabel: "English" },
  { code: "ta", label: "Tamil", nativeLabel: "தமிழ்" },
  { code: "hi", label: "Hindi", nativeLabel: "हिन्दी" },
]

export function isLang(value: unknown): value is Lang {
  return value === "en" || value === "ta" || value === "hi"
}

function storedLang(): Lang {
  try {
    const v = localStorage.getItem(LANG_KEY)
    if (isLang(v)) return v
  } catch {
    /* ignore */
  }
  return "en"
}

void i18n.use(initReactI18next).init({
  resources: {
    en: { translation: en },
    ta: { translation: ta },
    hi: { translation: hi },
  },
  lng: storedLang(),
  fallbackLng: "en",
  interpolation: { escapeValue: false },
  returnNull: false,
})

function applyLang(lng: string) {
  document.documentElement.lang = lng
  document.documentElement.dataset.lang = lng
}

applyLang(i18n.language)

i18n.on("languageChanged", (lng) => {
  try {
    localStorage.setItem(LANG_KEY, lng)
  } catch {
    /* ignore */
  }
  applyLang(lng)
})

export function currentLang(): Lang {
  const l = i18n.language ? i18n.language.slice(0, 2) : "en"
  return isLang(l) ? l : "en"
}

export default i18n
