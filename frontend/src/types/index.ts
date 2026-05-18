// Shared TypeScript types — expand as pages are built out.

// ── Dashboard ─────────────────────────────────────────────────────────────────

export interface DashboardStats {
  total_plans: number
  active_certificates: number
  approaching_expiry: number  // within 90 days, not yet expired
  expired: number
  open_jobs: number
  pending_reviews: number
}

export interface ClientSummary {
  id: string
  plan_number: number
  company_name: string
  company_address: string
  standards: string[]         // e.g. ["QMS", "EMS"]
  audit_type: string          // "initial" | "surveillance" | "recertification"
  status: string              // audit set workflow status
  cert_issued_date: string | null   // ISO date "YYYY-MM-DD"
  cert_expiry_date: string | null   // ISO date "YYYY-MM-DD"
  cert_status: 'active' | 'approaching_expiry' | 'expired' | null
  stage_1_date: string | null
  stage_2_date: string | null
  lead_auditor_name: string | null
  created_at: string          // ISO datetime
}

// ── Audit Set ─────────────────────────────────────────────────────────────────

export interface StageResponse {
  id: string
  stage_type: string
  stage_order: number
  notification_date: string | null
  audit_date_start: string | null
  audit_date_end: string | null
  lead_auditor_name: string | null
  auditors: unknown[] | null
  technical_experts: unknown[] | null
  observers: unknown[] | null
  audit_days: number | null
  status: string
}

export interface AuditSetPersonnel {
  full_time: number
  part_time: number
  subcontractors: number
  seasonal: number
}

/** @deprecated Use ManDayResult instead */
export interface ManDayEntry {
  base_days?: number
  after_integration?: number
  after_reporting_reduction?: number
  final?: number
}

/** Per-standard breakdown row inside ManDayResult (mirrors backend StandardAuditResult) */
export interface StandardAuditResult {
  standard: string
  category: string
  eps: number
  base_init: number
  base_ph1: number
  base_ph2: number
  base_surv: number
  base_recert: number
  base_recert_ph1: number
  base_recert_ph2: number
  site_addition: number
}

/** Full IAF MD 5 calculation result (mirrors backend CalculationResult) */
export interface ManDayResult {
  org_name: string
  standards: string[]
  audit_type: string
  scope: string
  standard_results: StandardAuditResult[]
  combined_base: number
  integration_reduction: number
  reporting_reduction: number
  final_total: number
  final_ph1: number
  final_ph2: number
  final_surv1: number
  final_surv2: number
  final_recert: number
  final_recert_ph1: number
  final_recert_ph2: number
  total_employees: number
  office_employees: number
  repetitive_employees: number
  eps: number
  enms_k?: number | null
  enms_complexity?: string | null
  scope_integration_level?: string | null   // "Low" | "Medium" | "High" — IAF MD 11
  md11_floor_applied?: boolean              // true when 50% floor was enforced
  md11_floor_value?: number | null          // the floor that was applied
  warning?: string | null
}

// ── Scope derivation ──────────────────────────────────────────────────────────

/** Single standard's derived scope entry */
export interface RequiredScopeEntry {
  type: 'food' | 'medical' | 'sector' | 'energy' | 'ea'
  codes: string[]
}

/** Full derived scope — keyed by ISO standard name, e.g. "ISO 22000" */
export type RequiredScope = Record<string, RequiredScopeEntry>

export interface AuditSetResponse {
  id: string
  plan_number: number
  status: string
  company_name: string
  company_address: string | null
  standards: string[] | null
  audit_type: string
  cycle_number: number
  accreditation_body: string | null
  scope_tr: string | null
  scope_en: string | null
  effective_employees: number | null
  man_day_result: ManDayResult | null
  ea_code: string | null
  ea_category: string | null
  certification_fee: number | null
  surveillance_fee: number | null
  required_scope: RequiredScope | null
  scope_integration_level: string | null     // "Low" | "Medium" | "High"
  stages: StageResponse[]
  created_at: string
  updated_at: string
  // cert fields — returned when backend includes them
  personnel?: AuditSetPersonnel | null
  cert_issued_date?: string | null
  cert_expiry_date?: string | null
  cert_status?: 'active' | 'approaching_expiry' | 'expired' | null
}

// ── Jobs (AI report pipeline) ─────────────────────────────────────────────────

export type JobStateValue =
  | 'QUEUED' | 'PREPROCESSING' | 'STEP_0' | 'STEP_A' | 'STEP_B' | 'STEP_C'
  | 'ASSEMBLING' | 'COMPLETE' | 'FAILED'

export interface JobStatus {
  job_id: string
  state: JobStateValue
  current_step?: string | null
  error_message?: string | null
  started_at?: string | null
  completed_at?: string | null
  step_timestamps?: Record<string, string>
}

export interface JobCreateResponse {
  job_id: string
  status: string
  standards: string[]
  stage: string
  language: string
  company_documents_received: number
  sample_reports_received: number
  template_received: boolean
  message: string
}

export interface JobListEntry {
  job_id: string
  company: string
  standards: string[]
  stage: string
  language: string
  accreditation_body: string
  submitted_at?: string | null
  state: JobStateValue | string
  current_step?: string | null
  error_message?: string | null
  completed_at?: string | null
}

// ── Auditors ──────────────────────────────────────────────────────────────────

export interface AuditorQualificationSummary {
  standard_code: string
  accreditation_body: string | null
  scope_category: string | null
  is_qualified: boolean
  technical_depth: string | null
  experience_years: number | null
  last_training_date: string | null   // ISO "YYYY-MM-DD"
  last_verified_date: string | null
  training_expiry_warning: boolean
  verification_warning: boolean
}

export interface AuditorDashboardEntry {
  auditor_id: string
  name: string
  email: string | null
  role: string | null
  is_active: boolean
  ea_codes: string[]
  accreditation_bodies: string[]
  qualifications: AuditorQualificationSummary[]
  total_audits: number
  last_audit_date: string | null
  days_since_last_audit: number | null
}

// Nested items mirrored from backend Pydantic schemas

export interface EducationItem      { degree?: string | null; institution?: string | null; year?: string | null }
export interface LanguageItem       { language?: string | null; level?: string | null }
export interface StandardQualificationItem {
  standard_code?: string | null
  accreditation_body?: string | null
  scope_category?: string | null       // for category-based standards (ISO 22000, FSSC, etc.)
  ea_codes?: string[]                  // per-standard EA codes for ISO 9001/14001/45001/27001
  technical_depth?: string | null
  experience_years?: number | null
  is_qualified?: boolean | null
  last_training_date?: string | null
  last_verified_date?: string | null
}
export interface WorkExperienceItem {
  employer?: string | null; position?: string | null
  start_date?: string | null; end_date?: string | null
  description?: string | null
}
export interface TrainingRecordItem {
  training_date?: string | null; institution?: string | null
  subject?: string | null; duration_days?: number | null
  standard_code?: string | null; certificate_available?: boolean | null
}
export interface AuditLogItem {
  audit_date?: string | null; client_name?: string | null
  standard_code?: string | null; role?: string | null; notes?: string | null
}

export interface AuditorResponse {
  id: string
  name: string
  email?: string | null
  phone?: string | null
  mobile?: string | null
  role?: string | null
  field_of_expertise?: string | null
  ea_codes?: string[] | null
  accreditation_bodies?: string[] | null
  is_active: boolean
  created_at?: string | null
  updated_at?: string | null
  education: EducationItem[]
  languages: LanguageItem[]
  standard_qualifications: StandardQualificationItem[]
  work_experience: WorkExperienceItem[]
  training_records: TrainingRecordItem[]
  audit_log: AuditLogItem[]
}

// Mirrors backend AuditorSummarySchema — returned by GET /auditors/
export interface AuditorSummary {
  id: string
  name: string
  email?: string | null
  role?: string | null
  field_of_expertise?: string | null
  ea_codes?: string[] | null
  accreditation_bodies?: string[] | null
  is_active: boolean
  created_at?: string | null
}

// Shape returned by POST /auditors/ingest — matches AuditorCreateSchema fields
export interface AuditorIngestResult {
  name?: string | null
  email?: string | null
  phone?: string | null
  mobile?: string | null
  role?: string | null
  field_of_expertise?: string | null
  active_since?: string | null              // "YYYY-MM-DD" — when the auditor joined the CB
  ea_codes?: string[] | null
  accreditation_bodies?: string[] | null
  education?: EducationItem[] | null
  languages?: LanguageItem[] | null
  standard_qualifications?: StandardQualificationItem[] | null
  work_experience?: WorkExperienceItem[] | null
  training_records?: TrainingRecordItem[] | null
}

// Returned by POST /auditors/assign-clauses
export interface ClauseAssignmentClause {
  clause_id: string
  title: string
  applicability?: string
}

export interface ClauseAssignmentEntry {
  auditor_id: string
  auditor_name: string
  role: string | null
  technical_depth?: string | null
  experience_years?: number | null
  assigned_clauses: ClauseAssignmentClause[]
}

export interface ClauseAssignmentResponse {
  standard_code: string
  assignments: ClauseAssignmentEntry[]
  note?: string
}

export type EligibilityRoleValue = 'lead_auditor' | 'team_auditor' | 'technical_expert'

export interface EligibilityCheckRequest {
  standard_code: string
  company_ea_code: string
  accreditation_body: string
  role: EligibilityRoleValue
}

export interface EligibilityResult {
  eligible: boolean
  blocking_reasons: string[]
  warnings: string[]
}

// ── Audit plan generator ──────────────────────────────────────────────────────

export interface AuditPlanClauseRef {
  clause_id: string
  title: string
}

export interface AuditPlanAssignment {
  auditor_name: string
  role: string                       // "Lead Auditor" | "Auditor" | "Technical Expert"
  assigned_clauses: AuditPlanClauseRef[]
}

export interface AuditPlanInput {
  company_name: string
  company_address: string
  standard_code: string
  accreditation_body: string         // "UAF" | "TURKAK"
  stage: number                      // 1 | 2
  audit_date: string                 // "YYYY-MM-DD"
  lead_auditor_name: string
  assignments: AuditPlanAssignment[]
  opening_time?: string              // default "09:00"
  closing_time?: string              // default "17:00"
  document_ref?: string              // default "FR.223"
}

// ── Admin user management ─────────────────────────────────────────────────────

export type UserRole = 'admin' | 'planner' | 'auditor' | 'officer' | 'executive'

export interface AdminUser {
  id:           string
  email:        string
  full_name:    string
  role:         UserRole
  is_active:    boolean
  auditor_id:   string | null
  last_login:   string | null      // ISO datetime
  created_at:   string             // ISO datetime
}

export interface AdminUserCreatePayload {
  email:       string
  password:    string
  full_name:   string
  role:        UserRole
  auditor_id?: string | null
}

export interface AdminUserUpdatePayload {
  full_name?:  string
  role?:       UserRole
  is_active?:  boolean
  auditor_id?: string | null
}

export interface AdminResetPasswordPayload {
  new_password: string
}

// ── Branding (public config) ──────────────────────────────────────────────────

export interface BrandingResponse {
  cb_name: string
  cb_short_name: string
  cb_logo_url: string
  cb_primary_color: string
  cb_website: string
  cb_email: string
  cb_phone: string
  cb_address: string
  accreditation_bodies: string[]
  supported_standards: string[]
}

// ── Witness audit records (ISO 17021-1 §7.1) ──────────────────────────────────

export interface WitnessRecord {
  id: number
  witness_date: string
  client_name: string | null
  standard_code: string | null
  ea_code: string | null
  role_witnessed: string | null
  observer_name: string | null
  outcome: 'Satisfactory' | 'Needs Improvement' | 'Unsatisfactory' | null
  notes: string | null
}

export interface WitnessStatus {
  auditor_id: string
  auditor_name: string
  last_witness_date: string | null
  days_since_last_witness: number | null
  witness_overdue: boolean
  new_auditor_unwitnessed: boolean
  total_witness_count: number
  records: WitnessRecord[]
}

// ── Auditor availability (GET /auditors/available) ────────────────────────────

export interface AuditorAvailabilityItem {
  id: string
  name: string
  role: string | null
  ea_codes: string[]
  standard_qualifications: {
    standard_code: string
    technical_depth: string
    ea_codes: string[]          // per-standard EA codes — may be [] for old records
    scope_category: string | null
  }[]
  available: boolean
  conflict_detail: string | null
  covered_scope: Record<string, string[]>    // {standard: [covered_codes]} from required_categories
}




