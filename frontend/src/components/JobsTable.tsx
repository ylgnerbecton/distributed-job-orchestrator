import AddIcon from "@mui/icons-material/Add";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import LinearProgress from "@mui/material/LinearProgress";
import MenuItem from "@mui/material/MenuItem";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import useMediaQuery from "@mui/material/useMediaQuery";
import { useTheme } from "@mui/material/styles";
import { useState } from "react";
import type { MouseEvent } from "react";

import { useCancelJob, useJobsInfinite } from "../api/queries";
import type { IJobSummary, TJobStatus, TJobType } from "../api/types";
import {
  formatAttempts,
  formatRelativeTime,
  isCancellable,
  priorityColor,
  progressColor,
  shortId,
  statusColor,
  titleCase,
} from "../format";
import { JobDetailDialog } from "./JobDetailDialog";
import { Panel } from "./Panel";

const STATUS_OPTIONS: readonly TJobStatus[] = [
  "pending",
  "queued",
  "running",
  "retrying",
  "succeeded",
  "failed",
  "cancelling",
  "cancelled",
  "expired",
];

const TYPE_OPTIONS: readonly TJobType[] = [
  "sleep",
  "report",
  "flaky",
  "always_fail",
  "llm_summary",
];

function flattenUnique(pages: { items: IJobSummary[] }[]): IJobSummary[] {
  const seen = new Set<string>();
  const jobs: IJobSummary[] = [];
  for (const page of pages) {
    for (const job of page.items) {
      if (!seen.has(job.jobId)) {
        seen.add(job.jobId);
        jobs.push(job);
      }
    }
  }
  return jobs;
}

function ProgressCell({ job }: { job: IJobSummary }): JSX.Element {
  if (job.status === "running" || job.status === "retrying") {
    return (
      <Box
        sx={{ display: "flex", alignItems: "center", gap: 1, minWidth: 120 }}
      >
        <LinearProgress
          variant="determinate"
          value={job.progress}
          color={progressColor(job.status)}
          sx={{ flexGrow: 1, height: 8, borderRadius: 4 }}
        />
        <Typography variant="caption" sx={{ width: 36, textAlign: "right" }}>
          {job.progress}%
        </Typography>
      </Box>
    );
  }
  return (
    <Typography variant="caption" color="text.secondary">
      {titleCase(job.status)}
    </Typography>
  );
}

interface IJobCardProps {
  job: IJobSummary;
  onOpen: (jobId: string) => void;
  onCancel: (jobId: string) => void;
  cancelDisabled: boolean;
}

function JobCard({
  job,
  onOpen,
  onCancel,
  cancelDisabled,
}: IJobCardProps): JSX.Element {
  return (
    <Box
      onClick={() => onOpen(job.jobId)}
      sx={{
        border: 1,
        borderColor: "divider",
        borderRadius: 2,
        p: 1.5,
        cursor: "pointer",
        "&:hover": { borderColor: "primary.light", bgcolor: "action.hover" },
      }}
    >
      <Stack
        direction="row"
        justifyContent="space-between"
        alignItems="center"
        spacing={1}
      >
        <Stack
          direction="row"
          spacing={1}
          alignItems="baseline"
          sx={{ minWidth: 0 }}
        >
          <Typography variant="body2" fontWeight={700} noWrap>
            {titleCase(job.type)}
          </Typography>
          <Typography variant="caption" color="text.secondary" noWrap>
            {shortId(job.jobId)}
          </Typography>
        </Stack>
        <Chip
          size="small"
          color={statusColor(job.status)}
          label={titleCase(job.status)}
        />
      </Stack>
      <Box sx={{ mt: 1 }}>
        <ProgressCell job={job} />
      </Box>
      <Stack
        direction="row"
        justifyContent="space-between"
        alignItems="center"
        sx={{ mt: 1 }}
      >
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
          <Chip
            size="small"
            variant="outlined"
            color={priorityColor(job.priority)}
            label={titleCase(job.priority)}
          />
          <Typography variant="caption" color="text.secondary">
            {formatAttempts(job.attempts, job.maxAttempts)}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {formatRelativeTime(job.createdAt)}
          </Typography>
        </Stack>
        <Button
          size="small"
          color="warning"
          disabled={cancelDisabled || !isCancellable(job.status)}
          onClick={(event) => {
            event.stopPropagation();
            onCancel(job.jobId);
          }}
        >
          Cancel
        </Button>
      </Stack>
    </Box>
  );
}

interface IJobsTableProps {
  onNewJob: () => void;
}

export function JobsTable({ onNewJob }: IJobsTableProps): JSX.Element {
  const theme = useTheme();
  const isCompact = useMediaQuery(theme.breakpoints.down("md"));
  const [statusFilter, setStatusFilter] = useState<TJobStatus | "">("");
  const [typeFilter, setTypeFilter] = useState<TJobType | "">("");
  const {
    data,
    isLoading,
    isError,
    isFetching,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useJobsInfinite({
    status: statusFilter === "" ? undefined : statusFilter,
    type: typeFilter === "" ? undefined : typeFilter,
  });
  const cancelMutation = useCancelJob();
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);

  const jobs = data !== undefined ? flattenUnique(data.pages) : [];
  const isRefreshing = isFetching && !isFetchingNextPage && !isLoading;

  const cancelJob = (jobId: string): void => {
    cancelMutation.mutate({ jobId });
  };

  const handleRowCancel = (
    event: MouseEvent<HTMLButtonElement>,
    jobId: string,
  ): void => {
    event.stopPropagation();
    cancelJob(jobId);
  };

  return (
    <>
      <Panel
        title="Jobs"
        action={<Chip label={`${jobs.length} loaded`} size="small" />}
      >
        <Stack
          direction={{ xs: "column", sm: "row" }}
          spacing={1.5}
          sx={{ mb: 2 }}
        >
          <TextField
            select
            size="small"
            label="Status"
            value={statusFilter}
            onChange={(event) =>
              setStatusFilter(event.target.value as TJobStatus | "")
            }
            fullWidth
          >
            <MenuItem value="">All statuses</MenuItem>
            {STATUS_OPTIONS.map((status) => (
              <MenuItem key={status} value={status}>
                {titleCase(status)}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            size="small"
            label="Type"
            value={typeFilter}
            onChange={(event) =>
              setTypeFilter(event.target.value as TJobType | "")
            }
            fullWidth
          >
            <MenuItem value="">All types</MenuItem>
            {TYPE_OPTIONS.map((type) => (
              <MenuItem key={type} value={type}>
                {titleCase(type)}
              </MenuItem>
            ))}
          </TextField>
        </Stack>

        <Box sx={{ height: 4, mb: 1 }}>
          {isRefreshing && <LinearProgress />}
        </Box>

        {isLoading ? (
          <Skeleton variant="rounded" height={320} />
        ) : isError || data === undefined ? (
          <Alert severity="error">Failed to load jobs.</Alert>
        ) : jobs.length === 0 ? (
          <Stack alignItems="center" spacing={1.5} sx={{ py: 6 }}>
            <Typography color="text.secondary">
              No jobs match the current filters.
            </Typography>
            <Button
              variant="outlined"
              startIcon={<AddIcon />}
              onClick={onNewJob}
            >
              New job
            </Button>
          </Stack>
        ) : isCompact ? (
          <Stack spacing={1.25}>
            {jobs.map((job) => (
              <JobCard
                key={job.jobId}
                job={job}
                onOpen={setSelectedJobId}
                onCancel={cancelJob}
                cancelDisabled={cancelMutation.isPending}
              />
            ))}
          </Stack>
        ) : (
          <TableContainer sx={{ maxHeight: { xs: 480, md: 640 } }}>
            <Table size="small" stickyHeader>
              <TableHead>
                <TableRow>
                  <TableCell>Job</TableCell>
                  <TableCell>Type</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell>Priority</TableCell>
                  <TableCell>Progress</TableCell>
                  <TableCell>Attempts</TableCell>
                  <TableCell>Created</TableCell>
                  <TableCell align="right">Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {jobs.map((job) => (
                  <TableRow
                    key={job.jobId}
                    hover
                    onClick={() => setSelectedJobId(job.jobId)}
                    sx={{ cursor: "pointer" }}
                  >
                    <TableCell>{shortId(job.jobId)}</TableCell>
                    <TableCell>{titleCase(job.type)}</TableCell>
                    <TableCell>
                      <Chip
                        size="small"
                        color={statusColor(job.status)}
                        label={titleCase(job.status)}
                      />
                    </TableCell>
                    <TableCell>
                      <Chip
                        size="small"
                        variant="outlined"
                        color={priorityColor(job.priority)}
                        label={titleCase(job.priority)}
                      />
                    </TableCell>
                    <TableCell>
                      <ProgressCell job={job} />
                    </TableCell>
                    <TableCell>
                      {formatAttempts(job.attempts, job.maxAttempts)}
                    </TableCell>
                    <TableCell>{formatRelativeTime(job.createdAt)}</TableCell>
                    <TableCell align="right">
                      <Button
                        size="small"
                        color="warning"
                        disabled={
                          !isCancellable(job.status) || cancelMutation.isPending
                        }
                        onClick={(event) => handleRowCancel(event, job.jobId)}
                      >
                        Cancel
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}

        {hasNextPage && (
          <Box sx={{ mt: 1.5, textAlign: "center" }}>
            <Button
              size="small"
              onClick={() => {
                void fetchNextPage();
              }}
              disabled={isFetchingNextPage}
            >
              {isFetchingNextPage ? "Loading..." : "Load older"}
            </Button>
          </Box>
        )}
      </Panel>
      <JobDetailDialog
        jobId={selectedJobId}
        onClose={() => setSelectedJobId(null)}
      />
    </>
  );
}
