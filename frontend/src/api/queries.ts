import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import type {
  InfiniteData,
  UseInfiniteQueryResult,
  UseMutationResult,
  UseQueryResult,
} from "@tanstack/react-query";

import { POLL_INTERVALS } from "../config";
import {
  cancelJob,
  fetchHealth,
  fetchJob,
  fetchJobEvents,
  fetchJobSummary,
  fetchJobs,
  submitJob,
} from "./client";
import type { ApiError } from "./client";
import type {
  ICancelRequest,
  ICancelResult,
  IHealth,
  IJob,
  IJobAccepted,
  IJobEvent,
  IJobSubmitRequest,
  IJobSummaryCounts,
  IJobsPage,
  TJobStatus,
  TJobType,
} from "./types";

export const JOBS_QUERY_KEY = "jobs";
export const JOB_SUMMARY_QUERY_KEY = "jobSummary";

interface IJobsFilter {
  status?: TJobStatus;
  type?: TJobType;
}

export function useHealth(): UseQueryResult<IHealth, Error> {
  return useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
    refetchInterval: POLL_INTERVALS.health,
  });
}

export function useJobSummary(): UseQueryResult<IJobSummaryCounts, Error> {
  return useQuery({
    queryKey: [JOB_SUMMARY_QUERY_KEY],
    queryFn: fetchJobSummary,
    refetchInterval: POLL_INTERVALS.summary,
  });
}

export function useJobsInfinite(
  filter: IJobsFilter,
): UseInfiniteQueryResult<InfiniteData<IJobsPage, string | null>, Error> {
  return useInfiniteQuery({
    queryKey: [JOBS_QUERY_KEY, filter.status ?? null, filter.type ?? null],
    queryFn: ({ pageParam }) =>
      fetchJobs({
        status: filter.status,
        type: filter.type,
        cursor: pageParam,
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
    refetchInterval: POLL_INTERVALS.jobs,
  });
}

export function useJob(jobId: string | null): UseQueryResult<IJob, Error> {
  return useQuery({
    queryKey: ["job", jobId],
    queryFn: () => fetchJob(jobId as string),
    enabled: jobId !== null,
    refetchInterval: POLL_INTERVALS.jobDetail,
  });
}

export function useJobEvents(
  jobId: string | null,
): UseQueryResult<IJobEvent[], Error> {
  return useQuery({
    queryKey: ["jobEvents", jobId],
    queryFn: () => fetchJobEvents(jobId as string),
    enabled: jobId !== null,
    refetchInterval: POLL_INTERVALS.jobEvents,
  });
}

export function useSubmitJob(): UseMutationResult<
  IJobAccepted,
  ApiError,
  IJobSubmitRequest
> {
  const queryClient = useQueryClient();
  return useMutation<IJobAccepted, ApiError, IJobSubmitRequest>({
    mutationFn: submitJob,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: [JOBS_QUERY_KEY] });
      void queryClient.invalidateQueries({
        queryKey: [JOB_SUMMARY_QUERY_KEY],
      });
    },
  });
}

export function useCancelJob(): UseMutationResult<
  ICancelResult,
  ApiError,
  ICancelRequest
> {
  const queryClient = useQueryClient();
  return useMutation<ICancelResult, ApiError, ICancelRequest>({
    mutationFn: cancelJob,
    onSuccess: (_result, variables) => {
      void queryClient.invalidateQueries({ queryKey: [JOBS_QUERY_KEY] });
      void queryClient.invalidateQueries({
        queryKey: [JOB_SUMMARY_QUERY_KEY],
      });
      void queryClient.invalidateQueries({
        queryKey: ["job", variables.jobId],
      });
    },
  });
}
