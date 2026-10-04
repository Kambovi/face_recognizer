import axios, { type AxiosError, type AxiosInstance } from "axios";
import type {
  AnalyticsOverview,
  AnalyticsPeriod,
  CameraOut,
  ClientProfile,
  AnalyticsSummaryResponse,
  AttendanceEventListResponse,
  AttendanceEventOut,
  ConsentCreate,
  ConsentOut,
  DashboardTodayResponse,
  EmployeeCreate,
  EmployeeListResponse,
  EmployeeOut,
  EmployeeUpdate,
  EnrollResponse,
  FaceTemplateOut,
  HealthResponse,
  LinkRequest,
  LoginRequest,
  LoginResponse,
  ManualEventCreate,
  ManualOverrideRequest,
  PromoteRequest,
  PromoteResponse,
  ReassignRequest,
  SettingsResponse,
  SettingsUpdateRequest,
  ShiftOut,
  SplitRequest,
  SplitResponse,
  UnknownIdentityOut,
  UnknownListResponse,
  UnknownUpdateRequest,
  AlertOut,
  CameraRole,
  ContractorReport,
  HqLink,
  MusterResponse,
  NotifyConfig,
  RosterAssign,
  RosterRow,
  SiteOut,
  WatchlistEntry,
  ChatAction,
  ChatConfig,
  ChatReply,
  ChatStatus,
  LeaveOut,
  PolicyStatus,
  AuditRow,
  DeviceOut,
  HolidayOut,
  LeaveBalance,
  LeaveType,
  PayrollAdjustment,
  PayrollProfile,
  PayrollProfileIn,
  PayrollRunOut,
  PtState,
  UserOut,
  UserRole,
} from "./types";

// Vite exposes build-time env vars via import.meta.env; falls back to the
// same-origin nginx proxy path in production (see frontend/nginx.conf /
// docker-compose.yml's VITE_API_BASE_URL build arg).
export const API_BASE_URL: string = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8000";

const TOKEN_STORAGE_KEY = "face_attendance_token";

export function getStoredToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setStoredToken(token: string | null): void {
  try {
    if (token) {
      window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
    } else {
      window.localStorage.removeItem(TOKEN_STORAGE_KEY);
    }
  } catch {
    // localStorage unavailable (private browsing, etc.) -- the session
    // simply won't persist across reloads, which is an acceptable
    // degradation rather than a crash.
  }
}

const http: AxiosInstance = axios.create({
  baseURL: `${API_BASE_URL}/api/v1`,
  timeout: 15000,
});

http.interceptors.request.use((config) => {
  const token = getStoredToken();
  if (token) {
    config.headers = config.headers ?? {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export interface ApiError {
  status: number | null;
  code: string;
  detail: string;
}

export function toApiError(error: unknown): ApiError {
  const axiosError = error as AxiosError<{ detail?: string; code?: string }>;
  if (axiosError.isAxiosError) {
    const body = axiosError.response?.data;
    return {
      status: axiosError.response?.status ?? null,
      code: body?.code ?? "network_error",
      detail: body?.detail ?? axiosError.message,
    };
  }
  return { status: null, code: "unknown_error", detail: String(error) };
}

let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

let onPasswordChangeRequired: (() => void) | null = null;
export function setPasswordChangeHandler(handler: (() => void) | null): void {
  onPasswordChangeRequired = handler;
}

http.interceptors.response.use(
  (response) => response,
  (error: AxiosError<{ code?: string }>) => {
    const url = error.config?.url ?? "";
    // a wrong password on the login form is not "session expired"
    if (error.response?.status === 401 && !url.endsWith("/auth/login") && !url.endsWith("/auth/change-password")) {
      onUnauthorized?.();
    }
    if (error.response?.status === 403 && error.response.data?.code === "password_change_required") {
      onPasswordChangeRequired?.();
    }
    return Promise.reject(error);
  },
);

// -- auth -----------------------------------------------------------------------

export async function login(payload: LoginRequest): Promise<LoginResponse> {
  const { data } = await http.post<LoginResponse>("/auth/login", payload);
  return data;
}

export async function changePassword(current_password: string, new_password: string): Promise<LoginResponse> {
  const { data } = await http.post<LoginResponse>("/auth/change-password", { current_password, new_password });
  return data;
}

export async function logoutEverywhere(): Promise<void> {
  await http.post("/auth/logout");
}

// -- users / cameras / audit (admin) ------------------------------------------------

export async function listUsers(): Promise<UserOut[]> {
  const { data } = await http.get<UserOut[]>("/users");
  return data;
}

export async function createUser(payload: { email: string; name?: string | null; role: UserRole }): Promise<UserOut> {
  const { data } = await http.post<UserOut>("/users", payload);
  return data;
}

export async function updateUser(id: string, payload: { name?: string | null; role?: UserRole; is_active?: boolean }): Promise<UserOut> {
  const { data } = await http.patch<UserOut>(`/users/${id}`, payload);
  return data;
}

export async function resetUserPassword(id: string): Promise<UserOut> {
  const { data } = await http.post<UserOut>(`/users/${id}/reset-password`);
  return data;
}

export async function deleteUser(id: string): Promise<void> {
  await http.delete(`/users/${id}`);
}

export async function listAudit(params: { entity?: string; action?: string; limit?: number } = {}): Promise<AuditRow[]> {
  const { data } = await http.get<AuditRow[]>("/audit", { params });
  return data;
}

export async function listDevices(): Promise<DeviceOut[]> {
  const { data } = await http.get<DeviceOut[]>("/devices");
  return data;
}

export async function addDevice(kiosk_id: string, name: string | null): Promise<DeviceOut> {
  const { data } = await http.post<DeviceOut>("/devices", { kiosk_id, name });
  return data;
}

export async function rotateDevice(id: string): Promise<DeviceOut> {
  const { data } = await http.post<DeviceOut>(`/devices/${id}/rotate`);
  return data;
}

export async function updateDevice(id: string, payload: { name?: string | null; enabled?: boolean }): Promise<DeviceOut> {
  const { data } = await http.patch<DeviceOut>(`/devices/${id}`, payload);
  return data;
}

export async function deleteDevice(id: string): Promise<void> {
  await http.delete(`/devices/${id}`);
}

// -- holidays ---------------------------------------------------------------------------

export async function listHolidays(year: number): Promise<HolidayOut[]> {
  const { data } = await http.get<HolidayOut[]>("/holidays", { params: { year } });
  return data;
}

export async function addHoliday(payload: { day: string; name: string; kind: HolidayOut["kind"] }): Promise<HolidayOut> {
  const { data } = await http.post<HolidayOut>("/holidays", payload);
  return data;
}

export async function addHolidaysBulk(items: { day: string; name: string; kind: HolidayOut["kind"] }[]): Promise<{ saved: number }> {
  const { data } = await http.post<{ saved: number }>("/holidays/bulk", items);
  return data;
}

export async function deleteHoliday(id: string): Promise<void> {
  await http.delete(`/holidays/${id}`);
}

export async function indiaHolidayPreset(year: number): Promise<{ day: string; name: string; kind: HolidayOut["kind"] }[]> {
  const { data } = await http.get<{ day: string; name: string; kind: HolidayOut["kind"] }[]>("/holidays/presets/india", { params: { year } });
  return data;
}

// -- payroll -----------------------------------------------------------------------------

export async function getPayrollStates(): Promise<{ company_state: string; states: PtState[] }> {
  const { data } = await http.get<{ company_state: string; states: PtState[] }>("/payroll/states");
  return data;
}

export async function getPayrollProfile(employeeId: string): Promise<PayrollProfile> {
  const { data } = await http.get<PayrollProfile>(`/payroll/profile/${employeeId}`);
  return data;
}

export async function savePayrollProfile(employeeId: string, payload: PayrollProfileIn): Promise<PayrollProfile> {
  const { data } = await http.put<PayrollProfile>(`/payroll/profile/${employeeId}`, payload);
  return data;
}

export async function listPayrollRuns(): Promise<PayrollRunOut[]> {
  const { data } = await http.get<PayrollRunOut[]>("/payroll/runs");
  return data;
}

export async function getPayrollRun(month: string): Promise<PayrollRunOut> {
  const { data } = await http.get<PayrollRunOut>(`/payroll/runs/${month}`);
  return data;
}

export async function generatePayroll(month: string): Promise<PayrollRunOut> {
  const { data } = await http.post<PayrollRunOut>(`/payroll/runs/${month}/generate`, undefined, { timeout: 120_000 });
  return data;
}

export async function lockPayroll(month: string): Promise<PayrollRunOut> {
  const { data } = await http.post<PayrollRunOut>(`/payroll/runs/${month}/lock`);
  return data;
}

export async function unlockPayroll(month: string): Promise<PayrollRunOut> {
  const { data } = await http.post<PayrollRunOut>(`/payroll/runs/${month}/unlock`);
  return data;
}

export async function listAdjustments(month: string): Promise<PayrollAdjustment[]> {
  const { data } = await http.get<PayrollAdjustment[]>("/payroll/adjustments", { params: { month } });
  return data;
}

export async function addAdjustment(payload: { month: string; employee_id: string; kind: "earning" | "deduction"; label: string; amount: number }): Promise<void> {
  await http.post("/payroll/adjustments", payload);
}

export async function deleteAdjustment(id: string): Promise<void> {
  await http.delete(`/payroll/adjustments/${id}`);
}

// -- dashboard --------------------------------------------------------------

export async function getDashboardToday(): Promise<DashboardTodayResponse> {
  const { data } = await http.get<DashboardTodayResponse>("/dashboard/today");
  return data;
}

export interface DashboardParams {
  /** Inclusive local (Asia/Kolkata) dates, "YYYY-MM-DD". Max 366 days. */
  date_from: string;
  date_to: string;
}

export async function getDashboard(params: DashboardParams): Promise<DashboardTodayResponse> {
  const { data } = await http.get<DashboardTodayResponse>("/dashboard", { params });
  return data;
}

// -- attendance ---------------------------------------------------------------

export interface ListEventsParams {
  date_from?: string;
  date_to?: string;
  subject_type?: string;
  reject_reason?: string;
  page?: number;
  page_size?: number;
}

export async function listEvents(params: ListEventsParams = {}): Promise<AttendanceEventListResponse> {
  const { data } = await http.get<AttendanceEventListResponse>("/attendance/events", { params });
  return data;
}

export async function manualOverrideEvent(eventId: string, payload: ManualOverrideRequest): Promise<AttendanceEventOut> {
  const { data } = await http.patch<AttendanceEventOut>(`/attendance/events/${eventId}`, payload);
  return data;
}

export async function reassignEvent(eventId: string, payload: ReassignRequest): Promise<AttendanceEventOut> {
  const { data } = await http.patch<AttendanceEventOut>(`/attendance/events/${eventId}/reassign`, payload);
  return data;
}

// -- unknowns -----------------------------------------------------------------

export interface ListUnknownsParams {
  status?: string;
  sort?: string;
  page?: number;
  page_size?: number;
}

export async function listUnknowns(params: ListUnknownsParams = {}): Promise<UnknownListResponse> {
  const { data } = await http.get<UnknownListResponse>("/unknowns", { params });
  return data;
}

export async function updateUnknown(unknownId: string, payload: UnknownUpdateRequest): Promise<UnknownIdentityOut> {
  const { data } = await http.patch<UnknownIdentityOut>(`/unknowns/${unknownId}`, payload);
  return data;
}

export async function deleteUnknown(unknownId: string): Promise<void> {
  await http.delete(`/unknowns/${unknownId}`);
}

export async function linkUnknown(unknownId: string, payload: LinkRequest): Promise<UnknownIdentityOut> {
  const { data } = await http.post<UnknownIdentityOut>(`/unknowns/${unknownId}/link`, payload);
  return data;
}

export async function promoteUnknown(unknownId: string, payload: PromoteRequest): Promise<PromoteResponse> {
  const { data } = await http.post<PromoteResponse>(`/unknowns/${unknownId}/promote`, payload);
  return data;
}

export async function splitUnknown(unknownId: string, payload: SplitRequest): Promise<SplitResponse> {
  const { data } = await http.post<SplitResponse>(`/unknowns/${unknownId}/split`, payload);
  return data;
}

export async function listUnknownTemplates(unknownId: string): Promise<FaceTemplateOut[]> {
  const { data } = await http.get<FaceTemplateOut[]>(`/unknowns/${unknownId}/templates`);
  return data;
}

// -- employees ------------------------------------------------------------------

export interface ListEmployeesParams {
  department?: string;
  is_active?: boolean;
  page?: number;
  page_size?: number;
}

export async function listEmployees(params: ListEmployeesParams = {}): Promise<EmployeeListResponse> {
  const { data } = await http.get<EmployeeListResponse>("/employees", { params });
  return data;
}

export async function createEmployee(payload: EmployeeCreate): Promise<EmployeeOut> {
  const { data } = await http.post<EmployeeOut>("/employees", payload);
  return data;
}

export async function updateEmployee(employeeId: string, payload: EmployeeUpdate): Promise<EmployeeOut> {
  const { data } = await http.patch<EmployeeOut>(`/employees/${employeeId}`, payload);
  return data;
}

export async function deleteEmployee(employeeId: string): Promise<void> {
  await http.delete(`/employees/${employeeId}`);
}

export async function grantConsent(employeeId: string, payload: ConsentCreate): Promise<ConsentOut> {
  const { data } = await http.post<ConsentOut>(`/employees/${employeeId}/consent`, payload);
  return data;
}

export async function revokeConsent(employeeId: string): Promise<void> {
  await http.delete(`/employees/${employeeId}/consent`);
}

export async function enrollEmployee(employeeId: string, files: File[]): Promise<EnrollResponse> {
  const form = new FormData();
  for (const file of files) {
    form.append("files", file);
  }
  const { data } = await http.post<EnrollResponse>(`/employees/${employeeId}/enroll`, form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export async function listTemplates(employeeId: string): Promise<FaceTemplateOut[]> {
  const { data } = await http.get<FaceTemplateOut[]>(`/employees/${employeeId}/templates`);
  return data;
}

export async function deleteTemplate(employeeId: string, templateId: string): Promise<void> {
  await http.delete(`/employees/${employeeId}/templates/${templateId}`);
}

// -- shifts ---------------------------------------------------------------------

export async function listShifts(): Promise<ShiftOut[]> {
  const { data } = await http.get<ShiftOut[]>("/shifts");
  return data;
}

export interface ShiftCreate {
  name: string;
  in_time: string;
  out_time: string;
  grace_minutes: number;
  is_default: boolean;
}

export async function createShift(payload: ShiftCreate): Promise<ShiftOut> {
  const { data } = await http.post<ShiftOut>("/shifts", payload);
  return data;
}

export async function updateShift(id: string, payload: Partial<ShiftCreate>): Promise<ShiftOut> {
  const { data } = await http.patch<ShiftOut>(`/shifts/${id}`, payload);
  return data;
}

export async function deleteShift(id: string): Promise<void> {
  await http.delete(`/shifts/${id}`);
}

export async function listRoster(date_from: string, date_to: string): Promise<RosterRow[]> {
  const { data } = await http.get<RosterRow[]>("/shifts/roster", { params: { date_from, date_to } });
  return data;
}

export async function assignRoster(payload: RosterAssign): Promise<{ assigned: number }> {
  const { data } = await http.post<{ assigned: number }>("/shifts/roster", payload);
  return data;
}

export async function deleteRosterRow(id: string): Promise<void> {
  await http.delete(`/shifts/roster/${id}`);
}

// -- reports ---------------------------------------------------------------------

/** Authenticated file download (a plain <a href> can't send the token). */
export async function downloadFile(path: string, params: Record<string, string | undefined>, filename: string): Promise<void> {
  const res = await http.get<Blob>(path, { params, responseType: "blob" });
  const url = URL.createObjectURL(res.data);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export async function getContractorReport(date_from: string, date_to: string): Promise<ContractorReport> {
  const { data } = await http.get<ContractorReport>("/reports/contractors", { params: { date_from, date_to } });
  return data;
}

export async function listContractorNames(): Promise<string[]> {
  const { data } = await http.get<string[]>("/reports/contractor-names");
  return data;
}

export async function getMuster(): Promise<MusterResponse> {
  const { data } = await http.get<MusterResponse>("/muster");
  return data;
}

export async function setCameraRole(kioskId: string, role: CameraRole): Promise<void> {
  await http.patch(`/cameras/${encodeURIComponent(kioskId)}`, { role });
}

export async function getAlertCount(): Promise<{ open: number; latest_at: string | null }> {
  const { data } = await http.get<{ open: number; latest_at: string | null }>("/alerts/count");
  return data;
}

export async function listAlerts(openOnly = false, limit = 50): Promise<AlertOut[]> {
  const { data } = await http.get<AlertOut[]>("/alerts", { params: { open_only: openOnly, limit } });
  return data;
}

export async function ackAlert(id: string): Promise<void> {
  await http.post(`/alerts/${id}/ack`);
}

export async function ackAllAlerts(): Promise<void> {
  await http.post("/alerts/ack-all");
}

export async function getWatchlist(): Promise<WatchlistEntry[]> {
  const { data } = await http.get<WatchlistEntry[]>("/alerts/watchlist");
  return data;
}

export async function listSites(): Promise<SiteOut[]> {
  const { data } = await http.get<SiteOut[]>("/hq/sites");
  return data;
}

export async function createSite(name: string): Promise<SiteOut> {
  const { data } = await http.post<SiteOut>("/hq/sites", { name });
  return data;
}

export async function deleteSite(id: string): Promise<void> {
  await http.delete(`/hq/sites/${id}`);
}

export async function getHqLink(): Promise<HqLink> {
  const { data } = await http.get<HqLink>("/hq/link");
  return data;
}

export async function setHqLink(url: string, token: string): Promise<HqLink> {
  const { data } = await http.put<HqLink>("/hq/link", { url, token });
  return data;
}

export async function testHqLink(): Promise<{ pushed: boolean; reason?: string }> {
  const { data } = await http.post<{ pushed: boolean; reason?: string }>("/hq/link/test");
  return data;
}

export async function getNotifyConfig(): Promise<NotifyConfig> {
  const { data } = await http.get<NotifyConfig>("/notify/config");
  return data;
}

export async function saveNotifyConfig(payload: Partial<NotifyConfig> & { access_token?: string }): Promise<NotifyConfig> {
  const { data } = await http.put<NotifyConfig>("/notify/config", payload);
  return data;
}

export async function testNotify(): Promise<{ sent: boolean; error: string | null }> {
  const { data } = await http.post<{ sent: boolean; error: string | null }>("/notify/test");
  return data;
}

export async function sendDailyNow(): Promise<{ sent: boolean; text: string; error: string | null }> {
  const { data } = await http.post<{ sent: boolean; text: string; error: string | null }>("/notify/daily-now");
  return data;
}

// -- analytics ------------------------------------------------------------------

export interface AnalyticsSummaryParams {
  period: AnalyticsPeriod;
  date_from?: string;
  date_to?: string;
  subject_id?: string;
  include_unknowns?: boolean;
}

export async function getAnalyticsSummary(params: AnalyticsSummaryParams): Promise<AnalyticsSummaryResponse> {
  const { data } = await http.get<AnalyticsSummaryResponse>("/analytics/summary", { params });
  return data;
}

/** CSV export needs the login token, which a plain <a href> can't send --
 *  fetch it through the authenticated client and save it as a file. */
export async function downloadAnalyticsCsv(params: AnalyticsSummaryParams): Promise<void> {
  const res = await http.get<Blob>("/analytics/export.csv", { params, responseType: "blob" });
  const url = URL.createObjectURL(res.data);
  const a = document.createElement("a");
  a.href = url;
  a.download = `attendance_${params.date_from ?? params.period}_${params.date_to ?? ""}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function analyticsExportCsvUrl(params: AnalyticsSummaryParams): string {
  const search = new URLSearchParams();
  search.set("period", params.period);
  if (params.date_from) search.set("date_from", params.date_from);
  if (params.date_to) search.set("date_to", params.date_to);
  if (params.subject_id) search.set("subject_id", params.subject_id);
  if (params.include_unknowns) search.set("include_unknowns", "true");
  return `${API_BASE_URL}/api/v1/analytics/export.csv?${search.toString()}`;
}

// -- settings -------------------------------------------------------------------

export async function getSettings(): Promise<SettingsResponse> {
  const { data } = await http.get<SettingsResponse>("/settings");
  return data;
}

export async function updateSettings(payload: SettingsUpdateRequest): Promise<SettingsResponse> {
  const { data } = await http.patch<SettingsResponse>("/settings", payload);
  return data;
}

// -- health -----------------------------------------------------------------------

export async function getHealth(): Promise<HealthResponse> {
  const { data } = await http.get<HealthResponse>("/health");
  return data;
}

// -- media (crop images) -------------------------------------------------------

export function mediaUrl(path: string | null): string | null {
  if (!path) return null;
  return path.startsWith("http") ? path : `${API_BASE_URL}${path}`;
}

export default http;

// -- manual attendance entry ----------------------------------------------------

export async function createManualEvent(payload: ManualEventCreate): Promise<AttendanceEventOut> {
  const { data } = await http.post<AttendanceEventOut>("/attendance/events/manual", payload);
  return data;
}

// -- client profile + cameras ------------------------------------------------------

export async function getProfile(): Promise<ClientProfile> {
  const { data } = await http.get<ClientProfile>("/profile");
  return data;
}

export async function listCameras(): Promise<CameraOut[]> {
  const { data } = await http.get<CameraOut[]>("/cameras");
  return data;
}

// -- analytics overview -------------------------------------------------------------

export async function getAnalyticsOverview(params: { date_from: string; date_to: string }): Promise<AnalyticsOverview> {
  const { data } = await http.get<AnalyticsOverview>("/analytics/overview", { params });
  return data;
}

// -- leaves ------------------------------------------------------------------------

export async function listLeaves(employee_id: string): Promise<LeaveOut[]> {
  const { data } = await http.get<LeaveOut[]>("/leaves", { params: { employee_id } });
  return data;
}

export async function addLeave(payload: {
  employee_id: string;
  date_from: string;
  date_to: string;
  leave_type?: string | null;
  kind?: "paid" | "unpaid" | "off";
  portion?: number;
  note?: string | null;
  force?: boolean;
}): Promise<{ days: number }> {
  const { data } = await http.post<{ days: number }>("/leaves", payload);
  return data;
}

export async function listLeaveTypes(): Promise<LeaveType[]> {
  const { data } = await http.get<LeaveType[]>("/leaves/types");
  return data;
}

export async function getLeaveBalance(employeeId: string): Promise<LeaveBalance[]> {
  const { data } = await http.get<LeaveBalance[]>(`/leaves/balance/${employeeId}`);
  return data;
}

export async function setLeaveOpening(payload: { employee_id: string; year: number; leave_type: string; days: number }): Promise<void> {
  await http.put("/leaves/opening", payload);
}

export async function deleteLeave(id: string): Promise<void> {
  await http.delete(`/leaves/${id}`);
}

// -- chatbot -----------------------------------------------------------------------

export async function getChatStatus(): Promise<ChatStatus> {
  const { data } = await http.get<ChatStatus>("/chat/status");
  return data;
}

export async function sendChat(payload: {
  message?: string;
  history?: { role: "user" | "assistant"; content: string }[];
  action?: ChatAction;
}): Promise<ChatReply> {
  const { data } = await http.post<ChatReply>("/chat", payload, { timeout: 90_000 });
  return data;
}

export async function getChatConfig(): Promise<ChatConfig> {
  const { data } = await http.get<ChatConfig>("/chat/config");
  return data;
}

export async function saveChatConfig(payload: Partial<ChatConfig> & { api_key?: string }): Promise<ChatConfig> {
  const { data } = await http.put<ChatConfig>("/chat/config", payload);
  return data;
}

export async function reindexPolicy(): Promise<PolicyStatus> {
  const { data } = await http.post<PolicyStatus>("/chat/reindex");
  return data;
}

export async function testChatModel(): Promise<{ ok: boolean; reply?: string; error?: string }> {
  const { data } = await http.post<{ ok: boolean; reply?: string; error?: string }>("/chat/test", {}, { timeout: 90_000 });
  return data;
}
