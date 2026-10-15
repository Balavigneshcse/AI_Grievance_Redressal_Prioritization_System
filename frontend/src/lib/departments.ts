import { useCallback, useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { api } from "@/lib/api"
import type { Department, DepartmentRef } from "@/lib/types"
import { DEPARTMENT_IDS, departmentName } from "@/lib/labels"
import { currentLang } from "@/lib/i18n"

let cache: Department[] | null = null
let inflight: Promise<Department[]> | null = null

function loadDepartments(): Promise<Department[]> {
  if (cache) return Promise.resolve(cache)
  if (!inflight) {
    inflight = api<Department[]>("/departments")
      .then((list) => {
        cache = Array.isArray(list) ? list : []
        return cache
      })
      .catch(() => [] as Department[])
      .finally(() => {
        inflight = null
      })
  }
  return inflight
}

/**
 * Departments from the API (cached per session). While offline the static id
 * list is used with names from the i18n dictionary, so the UI still renders.
 */
export function useDepartments() {
  const { t, i18n } = useTranslation()
  const [departments, setDepartments] = useState<Department[]>(cache ?? [])

  useEffect(() => {
    let cancelled = false
    void loadDepartments().then((list) => {
      if (!cancelled) setDepartments(list)
    })
    return () => {
      cancelled = true
    }
  }, [])

  const options: Department[] =
    departments.length > 0
      ? departments
      : DEPARTMENT_IDS.map((id) => ({
          id,
          name_en: t(`dept.${id}`, { lng: "en" }),
          name_ta: t(`dept.${id}`, { lng: "ta" }),
          name_hi: t(`dept.${id}`, { lng: "hi" }),
        }))

  const name = useCallback(
    (dep: DepartmentRef, fallback = ""): string => {
      const lang = currentLang()
      const resolved = departmentName(dep, lang, options, fallback)
      // id not in the API list: try the dictionary before echoing the id
      if (typeof dep === "string" && resolved === dep) {
        return t(`dept.${dep}`, { defaultValue: dep })
      }
      return resolved
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [options, t, i18n.language],
  )

  return { departments: options, name }
}
