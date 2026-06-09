import { API_BASE_URL, JOBS_PAGE_SIZE, USER_ID } from "../config";
import type {
  ICancelRequest,
  ICancelResult,
  IHealth,
  IJob,
  IJobAccepted,
  IJobEvent,
  IJobSubmitRequest,
  IJobSummary,
  IJobSummaryCounts,
  IJobsPage,
  IJobsQuery,
  TJobPriority,
  TJobStatus,
  TJobType,
} from "./types";

const USER_HEADER = "X-User-Id";
const IDEMPOTENCY_HEADER = "Idempotency-Key";
const CONTENT_TYPE_HEADER = "Content-Type";
const JSON_MEDIA_TYPE = "application/json";

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

interface IRawJobSummary {
  job_id: string;
  type: TJobType;
  status: TJobStatus;
  priority: TJobPriority;
  progress: number;
  attempts: number;
  max_attempts: number;
  created_at: string;
  updated_at: string;
}

interface IRawJob extends IRawJobSummary {
  payload: Record<string, unknown>;
  result: Record<string, unknown> | null;
  error_code: string | null;
  error_message: string | null;
  cancellation_requested_at: string | null;
  cancel_reason: string | null;
  dead_lettered_at: string | null;
  queued_at: string | null;
  started_at: string | null;
  completed_at: string | null;
}

interface IRawJobsPage {
  items: IRawJobSummary[];
  next_cursor: string | null;
  has_more: boolean;
}

interface IRawJobEvent {
  event_type: string;
  from_status: string | null;
  to_status: string | null;
  detail: Record<string, unknown>;
  created_at: string;
}

interface IRawJobEvents {
  items: IRawJobEvent[];
}

interface IRawJobAccepted {
  job_id: string;
  status: TJobStatus;
  status_url: string;
}

interface IRawCancelResult {
  job_id: string;
  status: TJobStatus;
}

interface IErrorBody {
  message?: string;
}

function buildHeaders(extra?: Record<string, string>): HeadersInit {
  return { [USER_HEADER]: USER_ID, ...extra };
}

async function readErrorMessage(response: Response): Promise<string | null> {
  try {
    const body = (await response.json()) as IErrorBody;
    if (typeof body.message === "string" && body.message.length > 0) {
      return body.message;
    }
  } catch {
    return null;
  }
  return null;
}

async function readError(response: Response, path: string): Promise<ApiError> {
  const message = await readErrorMessage(response);
  return new ApiError(
    message ?? `Request to ${path} failed with status ${response.status}`,
    response.status,
  );
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, init);
  if (!response.ok) {
    throw await readError(response, path);
  }
  return (await response.json()) as T;
}

function mapSummary(raw: IRawJobSummary): IJobSummary {
  return {
    jobId: raw.job_id,
    type: raw.type,
    status: raw.status,
    priority: raw.priority,
    progress: raw.progress,
    attempts: raw.attempts,
    maxAttempts: raw.max_attempts,
    createdAt: raw.created_at,
    updatedAt: raw.updated_at,
  };
}

function mapJob(raw: IRawJob): IJob {
  return {
    ...mapSummary(raw),
    payload: raw.payload,
    result: raw.result,
    errorCode: raw.error_code,
    errorMessage: raw.error_message,
    cancellationRequestedAt: raw.cancellation_requested_at,
    cancelReason: raw.cancel_reason,
    deadLetteredAt: raw.dead_lettered_at,
    queuedAt: raw.queued_at,
    startedAt: raw.started_at,
    completedAt: raw.completed_at,
  };
}

function mapEvent(raw: IRawJobEvent): IJobEvent {
  return {
    eventType: raw.event_type,
    fromStatus: raw.from_status,
    toStatus: raw.to_status,
    detail: raw.detail,
    createdAt: raw.created_at,
  };
}

export async function fetchHealth(): Promise<IHealth> {
  return request<IHealth>("/health", { headers: buildHeaders() });
}

export async function fetchJobSummary(): Promise<IJobSummaryCounts> {
  return request<IJobSummaryCounts>("/jobs/summary", {
    headers: buildHeaders(),
  });
}

export async function fetchJobs(query: IJobsQuery): Promise<IJobsPage> {
  const params = new URLSearchParams({ limit: String(JOBS_PAGE_SIZE) });
  if (query.status !== undefined) {
    params.set("status", query.status);
  }
  if (query.type !== undefined) {
    params.set("type", query.type);
  }
  if (query.cursor !== null) {
    params.set("cursor", query.cursor);
  }
  const raw = await request<IRawJobsPage>(`/jobs?${params.toString()}`, {
    headers: buildHeaders(),
  });
  return {
    items: raw.items.map(mapSummary),
    nextCursor: raw.next_cursor,
    hasMore: raw.has_more,
  };
}

export async function fetchJob(jobId: string): Promise<IJob> {
  const raw = await request<IRawJob>(`/jobs/${jobId}`, {
    headers: buildHeaders(),
  });
  return mapJob(raw);
}

export async function fetchJobEvents(jobId: string): Promise<IJobEvent[]> {
  const raw = await request<IRawJobEvents>(`/jobs/${jobId}/events`, {
    headers: buildHeaders(),
  });
  return raw.items.map(mapEvent);
}

export async function submitJob(
  body: IJobSubmitRequest,
): Promise<IJobAccepted> {
  const headers: Record<string, string> = {
    [CONTENT_TYPE_HEADER]: JSON_MEDIA_TYPE,
  };
  if (body.idempotencyKey !== undefined && body.idempotencyKey.length > 0) {
    headers[IDEMPOTENCY_HEADER] = body.idempotencyKey;
  }
  const payload: Record<string, unknown> = {
    type: body.type,
    payload: body.payload,
    priority: body.priority,
  };
  if (body.maxAttempts !== undefined) {
    payload.max_attempts = body.maxAttempts;
  }
  const raw = await request<IRawJobAccepted>("/jobs", {
    method: "POST",
    headers: buildHeaders(headers),
    body: JSON.stringify(payload),
  });
  return { jobId: raw.job_id, status: raw.status, statusUrl: raw.status_url };
}

export async function cancelJob(body: ICancelRequest): Promise<ICancelResult> {
  const payload: Record<string, unknown> = {};
  if (body.reason !== undefined && body.reason.length > 0) {
    payload.reason = body.reason;
  }
  const raw = await request<IRawCancelResult>(`/jobs/${body.jobId}/cancel`, {
    method: "POST",
    headers: buildHeaders({ [CONTENT_TYPE_HEADER]: JSON_MEDIA_TYPE }),
    body: JSON.stringify(payload),
  });
  return { jobId: raw.job_id, status: raw.status };
}
