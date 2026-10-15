import type { Lang } from "@/lib/i18n"

export type ScriptHint = "ta" | "hi" | "latin"

/** Client-side hint from the Unicode script of the text (not a full language id). */
export function detectScript(text: string): ScriptHint {
  let tamil = 0
  let devanagari = 0
  for (const ch of text) {
    const code = ch.codePointAt(0) ?? 0
    if (code >= 0x0b80 && code <= 0x0bff) tamil++
    else if (code >= 0x0900 && code <= 0x097f) devanagari++
  }
  if (tamil === 0 && devanagari === 0) return "latin"
  return tamil >= devanagari ? "ta" : "hi"
}

/**
 * language_hint sent to the API. Native script wins; for Latin text we fall back
 * to the UI language when it is not English (likely romanised Tamil/Hindi).
 */
export function languageHint(text: string, uiLang: Lang): string | undefined {
  const script = detectScript(text)
  if (script !== "latin") return script
  if (uiLang !== "en") return uiLang
  return undefined
}
