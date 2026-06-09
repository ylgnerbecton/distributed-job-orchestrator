const DEFAULT_API_BASE_URL = "http://localhost:8000";
const DEFAULT_USER_ID = "demo-user";

export const API_BASE_URL: string =
  import.meta.env.VITE_API_BASE_URL ?? DEFAULT_API_BASE_URL;

export const USER_ID: string = import.meta.env.VITE_USER_ID ?? DEFAULT_USER_ID;

export const JOBS_PAGE_SIZE = 25;

export const POLL_INTERVALS = {
  health: 5000,
  summary: 2000,
  jobs: 2000,
  jobDetail: 1500,
  jobEvents: 2000,
} as const;
