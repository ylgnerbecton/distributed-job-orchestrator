import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import LinearProgress from "@mui/material/LinearProgress";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Typography from "@mui/material/Typography";
import { useState } from "react";
import type { MouseEvent } from "react";

import { useCancelJob, useJobsInfinite } from "../api/queries";
import type { IJobSummary } from "../api/types";
import {
  formatAttempts,
  formatRelativeTime,
  isActiveStatus,
  isCancellable,
  priorityColor,
  progressColor,
  shortId,
  statusColor,
  titleCase,
} from "../format";
import { JobDetailDialog } from "./JobDetailDialog";
import { Panel } from "./Panel";

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
  if (isActiveStatus(job.status)) {
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

export function JobsTable(): JSX.Element {
  const {
    data,
    isLoading,
    isError,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useJobsInfinite({});
  const cancelMutation = useCancelJob();
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);

  const jobs = data !== undefined ? flattenUnique(data.pages) : [];

  const handleCancel = (
    event: MouseEvent<HTMLButtonElement>,
    jobId: string,
  ): void => {
    event.stopPropagation();
    cancelMutation.mutate({ jobId });
  };

  return (
    <>
      <Panel
        title="Jobs"
        isLoading={isLoading}
        isError={isError || data === undefined}
        isEmpty={!isLoading && !isError && jobs.length === 0}
        errorMessage="Failed to load jobs."
        emptyMessage="No jobs yet. Submit one to get started."
        skeletonHeight={320}
        action={
          jobs.length > 0 ? (
            <Chip label={`${jobs.length} loaded`} size="small" />
          ) : undefined
        }
      >
        <TableContainer sx={{ maxHeight: 520 }}>
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
                      onClick={(event) => handleCancel(event, job.jobId)}
                    >
                      Cancel
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
        {hasNextPage && (
          <Box sx={{ mt: 1, textAlign: "center" }}>
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
