export const CALCULATOR_STANDARDS = [
  { code: 'QMS', label: 'ISO 9001', detail: 'Quality' },
  { code: 'EMS', label: 'ISO 14001', detail: 'Environment' },
  { code: 'OHSMS', label: 'ISO 45001', detail: 'OH&S' },
  { code: 'FSMS', label: 'ISO 22000', detail: 'Food safety' },
  { code: 'ISMS', label: 'ISO 27001', detail: 'Information security' },
  { code: 'MDQMS', label: 'ISO 13485', detail: 'Medical devices' },
  { code: 'ABMS', label: 'ISO 37001', detail: 'Anti-bribery' },
  { code: 'ENMS', label: 'ISO 50001', detail: 'Energy' },
] as const

export type CalculatorStandard = typeof CALCULATOR_STANDARDS[number]['code']
export type AuditType = 'initial' | 'surveillance' | 'recertification'
export type Category = 'High' | 'Medium' | 'Low' | 'Limited'

export interface CalculatorSite {
  id: string
  name: string
  address: string
  process_description: string
  employee_count: number
  site_type: 'permanent' | 'temporary'
  sampling_eligible: boolean
}

export interface AdvancedCalculatorRequest {
  organization_name: string
  scope: string
  standards: CalculatorStandard[]
  audit_type: AuditType
  accreditation_body: 'UAF' | 'TURKAK'
  full_time_personnel: number
  part_time_personnel: number
  part_time_hours_per_day: number
  normal_hours_per_day: number
  subcontractors: number
  subcontractors_in_scope: boolean
  seasonal_temporary_personnel: number
  office_personnel: number
  repetitive_personnel: number
  shift_count: number
  same_process_all_shifts: boolean
  sites: CalculatorSite[]
  multi_site_sampling_requested: boolean
  multi_site_eligibility: {
    single_management_system: boolean
    central_function_identified: boolean
    centralized_management_review: boolean
    centralized_internal_audit: boolean
    similar_processes: boolean
  }
  mature_management_system: boolean
  sampled_site_reduction_pct: number
  sampled_site_reduction_justification: string
  manual_ea_codes: string[]
  category_overrides: Partial<Record<CalculatorStandard, Category>>
  integration: {
    enabled: boolean
    integrated_documentation: boolean
    integrated_management_review: boolean
    integrated_internal_audits: boolean
    integrated_policy_objectives: boolean
    integrated_processes: boolean
    integrated_improvement: boolean
    integrated_responsibilities: boolean
    combined_audit_capability_pct: number
  }
  md5_adjustment_pct: number
  adjustment_justification: string
  increase_factors: string[]
  decrease_factors: string[]
  remote_audit_pct: number
  food_chain_categories: string[]
  fsms_haccp_studies: number | null
  fsms_offsite_storage_count: number
  fsms_separate_head_office: boolean
  fsms_fssc22000: boolean
  annual_energy_tj: number | null
  num_energy_types: number | null
  num_seus: number | null
}

export interface ScopeClassificationResult {
  standard: string
  scope_type: string
  codes: string[]
  code_names: string[]
  category: string
  source: string
}

export interface AdvancedStandardResult {
  standard: string
  category: string
  eps: number
  central_time: number
  additional_site_time: number
  subtotal: number
  stage_1: number | null
  stage_2: number | null
}

export interface AdvancedCalculationResult {
  organization_name: string
  scope: string
  audit_type: AuditType
  accreditation_body: string
  effective_personnel: number
  part_time_fte: number
  classifications: ScopeClassificationResult[]
  standard_results: AdvancedStandardResult[]
  multi_site_plan: {
    sampling_requested: boolean
    sampling_permitted: boolean
    eligible_sites: number
    required_sample_size: number
    audited_additional_sites: number
    sampled_site_ids: string[]
    excluded_site_ids: string[]
    minimum_random_sites: number
    formula: string
  }
  base_time: number
  md5_adjustment_pct: number
  md5_adjustment_days: number
  after_md5_adjustment: number
  integration_level_pct: number
  combined_audit_capability_pct: number
  md11_reduction_pct: number
  md11_reduction_days: number
  final_audit_time: number
  stage_1_time: number | null
  stage_2_time: number | null
  on_site_time: number
  remote_time: number
  warnings: string[]
  compliance_notes: string[]
}
