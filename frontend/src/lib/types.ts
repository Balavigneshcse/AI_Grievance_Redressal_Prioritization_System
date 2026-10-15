export type Role = "complainant" | "dept_admin" | "district_admin" | "super_admin" | "officer" | "admin"

export interface User {
  id: string
  email: string
  role: Role
  preferred_language: string
  department_id?: string | null
  district?: string | null
  full_name?: string | null
  is_active?: boolean
}

export interface StaffUser extends User {
  mobile: string
  department: Department | null
  created_at: string
  last_login_at: string | null
}

export interface StaffCreated {
  user: StaffUser
  password: string
}

export interface DistrictInfo {
  id: string
  name: string
  staff: number
}

export type QueueView = "review" | "active" | "resolved" | "all"

export interface AuthResponse {
  access_token: string
  token_type: string
  user: User
}

export interface Department {
  id: string
  name_en: string
  name_ta: string
  name_hi: string
}

export type Status =
  | "received"
  | "analysing"
  | "under_review"
  | "routed"
  | "in_progress"
  | "resolved"
  | "closed"
  | "merged"
  | "awaiting_info"

export type Urgency = "critical" | "high" | "medium" | "low"

export type LocationSource = "camera_gps" | "exif" | "browser" | "manual" | "none"

/** `department` may arrive as an id string or as a full object; both are handled. */
export type DepartmentRef = string | Department | null | undefined

export interface ComplaintSummary {
  id: string
  tracking_id: string
  status: Status
  department: DepartmentRef
  urgency: Urgency | null
  created_at: string
  summary_en: string | null
}

export interface Media {
  id: string
  kind: string
  url: string
}

export interface Analysis {
  language_primary: string | null
  language_secondary: string | null
  department: string | null
  urgency: Urgency | null
  confidence: number | null
  summary_en: string | null
  evidence_spans: string[]
  entities: {
    locations: string[]
    dates: string[]
    people_affected: string[]
    ids: string[]
  } | null
  image_findings: string | null
  image_matches_text: boolean | null
  matched_rule_ids: string[]
  duplicate_candidates: { complaint_id: string; tracking_id: string; score: number }[]
  latency_ms: number | null
}

export interface Decision {
  queue: string
  reasons: string[]
}

export interface TimelineEntry {
  from_status: Status | null
  to_status: Status
  actor_type: string
  note: string | null
  created_at: string
}

export interface Complaint {
  id: string
  tracking_id: string
  status: Status
  raw_text: string
  language_hint: string | null
  department: Department | null
  urgency: Urgency | null
  lat: number | null
  lng: number | null
  location_source: LocationSource | null
  manual_address: string | null
  resolved_place: string | null
  complainant_name?: string | null
  aadhaar_last4?: string | null
  district?: string | null
  office_name?: string | null
  due_at?: string | null
  escalated_at?: string | null
  created_at: string
  media: Media[]
  analysis: Analysis | null
  decision: Decision | null
  timeline: TimelineEntry[]
}

export interface GeoReverse {
  name: string
  area: string
  distance_km: number
}

export interface QueueItem {
  id: string
  tracking_id: string
  status: Status
  urgency: Urgency | null
  district?: string | null
  office_name?: string | null
  due_at?: string | null
  complainant_name?: string | null
  department: DepartmentRef
  language_primary: string | null
  summary_en: string | null
  flags: string[]
  confidence: number | null
  created_at: string
}

export type DecisionAction = "accept" | "reassign" | "merge" | "request_info" | "resolve" | "close"

export interface DecisionPayload {
  action: DecisionAction
  department?: string
  urgency?: Urgency
  merged_into?: string
  reason: string
}

export interface Health {
  db: string
  ollama: string
  models: string
  queue_depth: number
}
