// Mirrors backend/app/schemas/*.py exactly. Kept hand-written (no codegen
// step in this stack) -- when a backend schema changes, update the matching
// interface here in the same commit.

export type SubjectType = "EMPLOYEE" | "UNKNOWN";
export type EventType = "IN" | "OUT";
export type RejectReason = "liveness_failed" | "too_small" | "low_quality" | "no_match";
export type UnknownStatusValue = "OPEN" | "LINKED" | "PROMOTED" | "IGNORED";
export type UserRole = "admin" | "viewer";
export type AnalyticsPeriod = "daily" | "weekly" | "monthly" | "annual";

// -- auth ---------------------------------------------------------------------

export interface LoginRequest {
  email: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  role: string;
  email: string;
}

// -- employees ------------------------------------------------------------------

export interface ShiftOut {
  id: string;
  name: string;
  in_time: string;
  out_time: string;
  grace_minutes: number;
  is_default: boolean;
}

export interface EmployeeOut {
  id: string;
  face_id: string;
  emp_code: string;
  name: string;
  department: string | null;
  designation: string | null;
  shift_id: string | null;
  home_kiosk_id: string | null;
  contractor: string | null;
  is_active: boolean;
  created_at: string;
  template_count: number;
}

export interface EmployeeListResponse {
  items: EmployeeOut[];
  total: number;
  page: number;
  page_size: number;
}

export interface EmployeeCreate {
  name: string;
  emp_code: string;
  department?: string | null;
  designation?: string | null;
  shift_id?: string | null;
  home_kiosk_id?: string | null;
  contractor?: string | null;
}

export interface EmployeeUpdate {
  name?: string;
  department?: string | null;
  designation?: string | null;
  shift_id?: string | null;
  home_kiosk_id?: string | null;
  contractor?: string | null;
  is_active?: boolean;
}

export interface ConsentCreate {
  policy_version: string;
  purpose_text: string;
  ip_address?: string | null;
}

export interface ConsentOut {
  id: string;
  employee_id: string;
  granted_at: string;
  revoked_at: string | null;
  policy_version: string;
  purpose_text: string;
}

export interface EnrollImageResult {
  filename: string;
  accepted: boolean;
  reason: string | null;
  quality_score: number;
  template_id: string | null;
}

export interface EnrollResponse {
  results: EnrollImageResult[];
  accepted_count: number;
  template_count: number;
}

export interface FaceTemplateOut {
  id: string;
  quality_score: number;
  model_version: string;
  created_at: string;
  is_primary: boolean;
  crop_url: string | null;
}

// -- dashboard --------------------------------------------------------------

export interface KnownRowOut {
  face_id: string;
  emp_code: string | null;
  name: string;
  designation: string | null;
  department: string | null;
  shift_in: string | null;
  shift_out: string | null;
  in_time: string | null;
  out_time: string | null;
  total_hours: number;
  status: string;
  similarity: number | null;
  thumb_url: string | null;
  best_shot_url: string | null;
  // Added with GET /dashboard (date range); always present from the backend.
  date: string;
  kiosk_ids: string[];
  is_active: boolean;
  on_time: boolean | null;
  // ids used by the dashboard's inline edit actions
  subject_id: string;
  in_event_id: string | null;
  out_event_id: string | null;
  home_kiosk_id: string | null;
}

export interface UnknownRowOut {
  face_id: string;
  label: string | null;
  first_seen: string;
  last_seen: string;
  sighting_count: number;
  in_time: string | null;
  out_time: string | null;
  total_hours: number;
  status: string;
  best_crop_url: string | null;
  date: string;
  kiosk_ids: string[];
  subject_id: string;
  in_event_id: string | null;
  out_event_id: string | null;
}

export interface AbsentRowOut {
  face_id: string;
  emp_code: string | null;
  name: string;
  designation: string | null;
  department: string | null;
  shift_in: string | null;
  shift_out: string | null;
  thumb_url: string | null;
  date: string;
  is_active: boolean;
  subject_id: string;
  home_kiosk_id: string | null;
}

export interface ExceptionRowOut {
  kind: string;
  face_id: string;
  label: string | null;
  detail: string;
  date: string;
  kiosk_ids: string[];
}

export interface DashboardTodayResponse {
  known: KnownRowOut[];
  unknown: UnknownRowOut[];
  absent: AbsentRowOut[];
  exceptions: ExceptionRowOut[];
  counts: Record<string, number>;
  date_from: string;
  date_to: string;
  /** Every entry point (kiosk / camera id) seen in the range or via heartbeat. */
  kiosks: string[];
}

/** Same shape is returned by GET /dashboard (range) and GET /dashboard/today. */
export type DashboardResponse = DashboardTodayResponse;

// -- attendance ---------------------------------------------------------------

export interface AttendanceEventOut {
  id: string;
  subject_type: SubjectType | null;
  employee_id: string | null;
  unknown_identity_id: string | null;
  event_type: string;
  occurred_at: string;
  similarity: number | null;
  liveness_score: number | null;
  kiosk_id: string;
  crop_url: string | null;
  reject_reason: string | null;
  is_manual_override: boolean;
  overridden_by: string | null;
  override_reason: string | null;
}

export interface AttendanceEventListResponse {
  items: AttendanceEventOut[];
  total: number;
  page: number;
  page_size: number;
}

export interface ManualOverrideRequest {
  event_type?: EventType;
  occurred_at?: string;
  reason: string;
}

export type ReassignTargetType = "EMPLOYEE" | "UNKNOWN" | "NEW_UNKNOWN";

export interface ReassignRequest {
  target_type: ReassignTargetType;
  target_id?: string | null;
  reason: string;
}

// -- unknowns -----------------------------------------------------------------

export interface UnknownIdentityOut {
  id: string;
  face_id: string;
  label: string | null;
  first_seen_at: string;
  last_seen_at: string;
  sighting_count: number;
  best_crop_url: string | null;
  status: string;
  resolved_employee_id: string | null;
}

export interface UnknownListResponse {
  items: UnknownIdentityOut[];
  total: number;
  page: number;
  page_size: number;
}

export interface UnknownUpdateRequest {
  label?: string | null;
  notes?: string | null;
  status?: "OPEN" | "IGNORED";
}

export interface LinkRequest {
  employee_id: string;
  reason: string;
  adopt_templates: boolean;
}

export interface ConsentPayload {
  policy_version: string;
  purpose_text: string;
  ip_address?: string | null;
}

export interface PromoteRequest {
  name: string;
  emp_code: string;
  department?: string | null;
  designation?: string | null;
  shift_id?: string | null;
  home_kiosk_id?: string | null;
  contractor?: string | null;
  consent?: ConsentPayload | null;
  reason: string;
}

export interface PromoteResponse {
  employee_id: string;
  face_id: string;
}

export interface SplitRequest {
  template_ids: string[];
  reason: string;
}

export interface SplitResponse {
  new_unknown_id: string;
  new_face_id: string;
}

// -- analytics ------------------------------------------------------------------

export interface SummaryRowOut {
  face_id: string;
  name: string | null;
  designation: string | null;
  department: string | null;
  shift_in: string | null;
  shift_out: string | null;
  avg_in_time: string | null;
  avg_out_time: string | null;
  total_hours: number;
  present_days: number;
  absent_days: number;
  late_count: number;
  early_exit_count: number;
  attendance_pct: number;
  is_unknown: boolean;
  label: string | null;
}

export interface AnalyticsSummaryResponse {
  period: string;
  date_from: string;
  date_to: string;
  rows: SummaryRowOut[];
}

// -- settings -------------------------------------------------------------------

export interface SettingsResponse {
  settings: Record<string, unknown>;
  device: Record<string, unknown> | null;
}

export interface SettingsUpdateRequest {
  values: Record<string, unknown>;
}

// -- misc -----------------------------------------------------------------------

export interface ApiErrorBody {
  detail: string;
  code: string;
}

export interface HealthResponse {
  status: string;
  db: string;
  model: string;
  device: Record<string, unknown> | null;
  time: string;
}

// -- manual attendance entry ----------------------------------------------------

export interface ManualEventCreate {
  employee_id: string;
  event_type: EventType;
  occurred_at: string; // ISO datetime with offset
  reason: string;
}

// -- client profile (vendor-locked, read-only) ---------------------------------

export type OrgType = "business" | "school" | "hospital";

export interface ClientProfile {
  configured: boolean;
  org_type: OrgType;
  org_name: string;
  departments: string[];
  max_enrolled_per_camera: number;
  person_label: string;
  person_label_plural: string;
  id_label: string;
  department_label: string;
  department_label_plural: string;
  designation_label: string;
}

export interface CameraOut {
  kiosk_id: string;
  enrolled: number;
  cap: number;
  online: boolean;
  liveness: LivenessState;
}

/** Anti-spoofing status from the camera's last heartbeat. */
export type LivenessState = "on" | "off" | "unknown";

// -- analytics overview -----------------------------------------------------------

export interface OverviewSummary {
  attendance_pct: number;
  present_person_days: number;
  late_count: number;
  on_time_pct: number;
  avg_hours: number;
  /** minutes after midnight, -1 = no data */
  avg_arrival_minutes: number;
  unknown_visitors?: number;
}

export interface OverviewKpis extends OverviewSummary {
  roster: number;
  present_latest_day: number;
  latest_day: string;
  unknown_visitors: number;
  previous: OverviewSummary & { unknown_visitors: number };
  previous_from: string;
  previous_to: string;
}

export interface TrendPoint {
  date: string;
  working_day: boolean;
  roster: number;
  present: number;
  late: number;
  attendance_pct: number;
}

export interface LocationStat {
  kiosk_id: string;
  roster: number;
  present_latest_day: number;
  absent_latest_day: number;
  attendance_pct: number;
  unknown_visitors_latest_day: number;
  online: boolean;
  liveness: LivenessState;
  assigned: number;
}

export interface DepartmentStat {
  department: string;
  roster: number;
  attendance_pct: number;
  late_count: number;
  present_latest_day: number;
}

export interface ArrivalBucket {
  bucket: string;
  start_minutes: number;
  count: number;
}

export interface PersonStat {
  employee_id: string;
  face_id: string;
  emp_code: string;
  name: string;
  department: string | null;
  home_kiosk_id: string | null;
  expected_days: number;
  present_days: number;
  late_days: number;
  attendance_pct: number;
}

export interface AnalyticsOverview {
  date_from: string;
  date_to: string;
  working_days: number;
  kpis: OverviewKpis;
  trend: TrendPoint[];
  locations: LocationStat[];
  departments: DepartmentStat[];
  arrivals: ArrivalBucket[];
  lowest_attendance: PersonStat[];
  most_late: PersonStat[];
}

// -- shifts / roster ----------------------------------------------------------

export interface RosterRow {
  id: string;
  employee_id: string;
  emp_code: string;
  name: string;
  shift_id: string;
  shift_name: string;
  start_date: string;
  end_date: string;
}

export interface RosterAssign {
  employee_ids: string[];
  shift_id: string;
  start_date: string;
  end_date: string;
}

// -- reports ------------------------------------------------------------------

export type DayStatus = "P" | "HD" | "A" | "WO" | "WOP" | "-";

export interface PersonTotals {
  days_in_range: number;
  working_days: number;
  present: number;
  half_days: number;
  absent: number;
  weekly_off: number;
  worked_on_off: number;
  late_days: number;
  late_minutes: number;
  early_leave_minutes: number;
  ot_hours: number;
  worked_hours: number;
  lop_days: number;
  paid_days: number;
}

export interface ContractorDay {
  date: string;
  on_roll: number;
  present: number;
  half_day: number;
  man_days: number;
  ot_hours: number;
}

export interface ContractorPerson extends PersonTotals {
  employee_id: string;
  emp_code: string;
  name: string;
  department: string | null;
  contractor: string;
}

export interface ContractorRow {
  contractor: string;
  headcount: number;
  man_days: number;
  ot_hours: number;
  worked_hours: number;
  late_days: number;
  avg_daily_present: number;
  daily: ContractorDay[];
  people: ContractorPerson[];
}

export interface ContractorReport {
  date_from: string;
  date_to: string;
  contractors: ContractorRow[];
}

export type PayrollFormat = "generic" | "tally" | "zoho" | "greythr" | "keka";
