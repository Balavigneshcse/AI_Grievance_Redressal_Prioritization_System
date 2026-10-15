import { z } from "zod"

/** 8+ chars with upper, lower, digit and symbol (API policy). Messages are i18n keys. */
export const passwordSchema = z
  .string()
  .min(8, "validation.passwordMin")
  .regex(/[A-Z]/, "validation.passwordUpper")
  .regex(/[a-z]/, "validation.passwordLower")
  .regex(/[0-9]/, "validation.passwordDigit")
  .regex(/[^A-Za-z0-9]/, "validation.passwordSymbol")

/** 0..100 strength score used by the Progress bar. */
export function passwordScore(pw: string): number {
  if (!pw) return 0
  let score = 0
  if (pw.length >= 8) score += 20
  if (pw.length >= 12) score += 10
  if (/[A-Z]/.test(pw)) score += 20
  if (/[a-z]/.test(pw)) score += 15
  if (/[0-9]/.test(pw)) score += 15
  if (/[^A-Za-z0-9]/.test(pw)) score += 20
  return Math.min(100, score)
}

export function passwordLevel(score: number): "weak" | "fair" | "strong" {
  if (score >= 80) return "strong"
  if (score >= 50) return "fair"
  return "weak"
}
