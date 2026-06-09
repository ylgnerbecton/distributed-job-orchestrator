import type { TJobPriority, TJobStatus } from "./api/types";

export type TChipColor =
  | "default"
  | "primary"
  | "secondary"
  | "info"
  | "success"
  | "warning"
  | "error";

const SHORT_ID_LENGTH = 8;
const PLACEHOLDER = "-";

const MINUTE_SECONDS = 60;
const HOUR_SECONDS = 3600;
const DAY_SECONDS = 86400;

const STATUS_COLOR: Record<TJobStatus, TChipColor> = {
  pending: "default",
  queued: "default",
  running: "info",
  retrying: "warning",
  succeeded: "success",
  failed: "error",
  cancelling: "warning",
  cancelled: "default",
  expired: "default",
};

const PRIORITY_COLOR: Record<TJobPriority, TChipColor> = {
  low: "default",
  normal: "info",
  high: "warning",
};

const ACTIVE_STATUSES: ReadonlySet<TJobStatus> = new Set<TJobStatus>([
  "pending",
  "queued",
  "running",
  "retrying",
]);

const CANCELLABLE_STATUSES: ReadonlySet<TJobStatus> = new Set<TJobStatus>([
  "pending",
  "queued",
  "running",
  "retrying",
]);

export type TProgressColor =
  | "primary"
  | "secondary"
  | "info"
  | "success"
  | "warning"
  | "error";

const PROGRESS_COLOR: Record<TJobStatus, TProgressColor> = {
  pending: "primary",
  queued: "primary",
  running: "info",
  retrying: "warning",
  succeeded: "success",
  failed: "error",
  cancelling: "warning",
  cancelled: "secondary",
  expired: "secondary",
};

export function statusColor(status: TJobStatus): TChipColor {
  return STATUS_COLOR[status];
}

export function progressColor(status: TJobStatus): TProgressColor {
  return PROGRESS_COLOR[status];
}

export function priorityColor(priority: TJobPriority): TChipColor {
  return PRIORITY_COLOR[priority];
}

export function isActiveStatus(status: TJobStatus): boolean {
  return ACTIVE_STATUSES.has(status);
}

export function isCancellable(status: TJobStatus): boolean {
  return CANCELLABLE_STATUSES.has(status);
}

export function shortId(value: string): string {
  return value.slice(0, SHORT_ID_LENGTH);
}

export function titleCase(value: string): string {
  return value
    .split("_")
    .map((word) =>
      word.length === 0 ? word : word[0].toUpperCase() + word.slice(1),
    )
    .join(" ");
}

export function formatAbsoluteTime(value: string | null): string {
  if (value === null) {
    return PLACEHOLDER;
  }
  return new Date(value).toLocaleString();
}

export function formatRelativeTime(value: string | null): string {
  if (value === null) {
    return PLACEHOLDER;
  }
  const elapsedSeconds = Math.max(
    0,
    Math.floor((Date.now() - new Date(value).getTime()) / 1000),
  );
  if (elapsedSeconds < MINUTE_SECONDS) {
    return `${elapsedSeconds}s ago`;
  }
  if (elapsedSeconds < HOUR_SECONDS) {
    return `${Math.floor(elapsedSeconds / MINUTE_SECONDS)}m ago`;
  }
  if (elapsedSeconds < DAY_SECONDS) {
    return `${Math.floor(elapsedSeconds / HOUR_SECONDS)}h ago`;
  }
  return `${Math.floor(elapsedSeconds / DAY_SECONDS)}d ago`;
}

export function formatAttempts(attempts: number, maxAttempts: number): string {
  return `${attempts} / ${maxAttempts}`;
}

export function formatJson(value: Record<string, unknown> | null): string {
  if (value === null) {
    return PLACEHOLDER;
  }
  return JSON.stringify(value, null, 2);
}
