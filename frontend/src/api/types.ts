export type TJobStatus =
  | "pending"
  | "queued"
  | "running"
  | "retrying"
  | "succeeded"
  | "failed"
  | "cancelling"
  | "cancelled"
  | "expired";

export type TJobPriority = "low" | "normal" | "high";

export type TJobType =
  | "sleep"
  | "report"
  | "flaky"
  | "always_fail"
  | "llm_summary";

export interface IHealth {
  status: string;
  database: string;
  queue: string;
}

export interface IJobSummaryCounts {
  counts: Record<string, number>;
  total: number;
}

export interface IJobSummary {
  jobId: string;
  type: TJobType;
  status: TJobStatus;
  priority: TJobPriority;
  progress: number;
  attempts: number;
  maxAttempts: number;
  createdAt: string;
  updatedAt: string;
}

export interface IJob extends IJobSummary {
  payload: Record<string, unknown>;
  result: Record<string, unknown> | null;
  errorCode: string | null;
  errorMessage: string | null;
  cancellationRequestedAt: string | null;
  cancelReason: string | null;
  deadLetteredAt: string | null;
  queuedAt: string | null;
  startedAt: string | null;
  completedAt: string | null;
}

export interface IJobsPage {
  items: IJobSummary[];
  nextCursor: string | null;
  hasMore: boolean;
}

export interface IJobEvent {
  eventType: string;
  fromStatus: string | null;
  toStatus: string | null;
  detail: Record<string, unknown>;
  createdAt: string;
}

export interface IJobEvents {
  items: IJobEvent[];
}

export interface IJobAccepted {
  jobId: string;
  status: TJobStatus;
  statusUrl: string;
}

export interface ICancelResult {
  jobId: string;
  status: TJobStatus;
}

export interface IJobSubmitRequest {
  type: TJobType;
  payload: Record<string, unknown>;
  priority: TJobPriority;
  maxAttempts?: number;
  idempotencyKey?: string;
}

export interface ICancelRequest {
  jobId: string;
  reason?: string;
}

export interface IJobsQuery {
  status?: TJobStatus;
  type?: TJobType;
  cursor: string | null;
}
