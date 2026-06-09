import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Divider from "@mui/material/Divider";
import LinearProgress from "@mui/material/LinearProgress";
import Skeleton from "@mui/material/Skeleton";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import useMediaQuery from "@mui/material/useMediaQuery";
import { useTheme } from "@mui/material/styles";

import { useCancelJob, useJob, useJobEvents } from "../api/queries";
import type { IJob, IJobEvent } from "../api/types";
import {
  formatAbsoluteTime,
  formatAttempts,
  formatJson,
  formatRelativeTime,
  isCancellable,
  priorityColor,
  shortId,
  statusColor,
  titleCase,
} from "../format";

interface IJobDetailDialogProps {
  jobId: string | null;
  onClose: () => void;
}

function CodeBlock({ value }: { value: string }): JSX.Element {
  return (
    <Box
      component="pre"
      sx={{
        m: 0,
        p: 1.5,
        bgcolor: "grey.100",
        borderRadius: 1,
        fontFamily: "ui-monospace, monospace",
        fontSize: 13,
        overflowX: "auto",
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
      }}
    >
      {value}
    </Box>
  );
}

function MetaRow({
  label,
  value,
}: {
  label: string;
  value: string;
}): JSX.Element {
  return (
    <Stack direction="row" spacing={1} justifyContent="space-between">
      <Typography variant="body2" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="body2" sx={{ textAlign: "right" }}>
        {value}
      </Typography>
    </Stack>
  );
}

function EventTimeline({ events }: { events: IJobEvent[] }): JSX.Element {
  if (events.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary">
        No events recorded.
      </Typography>
    );
  }
  return (
    <Stack spacing={1}>
      {events.map((event, index) => (
        <Box
          key={`${event.eventType}-${event.createdAt}-${index}`}
          sx={{ borderLeft: 3, borderColor: "divider", pl: 1.5 }}
        >
          <Stack direction="row" spacing={1} alignItems="center">
            <Typography variant="body2" fontWeight={700}>
              {titleCase(event.eventType)}
            </Typography>
            <Typography
              variant="caption"
              color="text.secondary"
              sx={{ ml: "auto" }}
            >
              {formatRelativeTime(event.createdAt)}
            </Typography>
          </Stack>
          <Typography variant="caption" color="text.secondary">
            {event.fromStatus ?? "none"} -&gt; {event.toStatus ?? "none"}
          </Typography>
        </Box>
      ))}
    </Stack>
  );
}

function JobBody({ job }: { job: IJob }): JSX.Element {
  return (
    <Stack spacing={2}>
      <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
        <Chip
          label={titleCase(job.status)}
          color={statusColor(job.status)}
          size="small"
        />
        <Chip
          label={titleCase(job.priority)}
          color={priorityColor(job.priority)}
          variant="outlined"
          size="small"
        />
        <Chip label={titleCase(job.type)} variant="outlined" size="small" />
        {job.deadLetteredAt !== null && (
          <Chip label="Dead lettered" color="error" size="small" />
        )}
      </Stack>

      <Box>
        <Stack direction="row" justifyContent="space-between" sx={{ mb: 0.5 }}>
          <Typography variant="body2" color="text.secondary">
            Progress
          </Typography>
          <Typography variant="body2">{job.progress}%</Typography>
        </Stack>
        <LinearProgress
          variant="determinate"
          value={job.progress}
          sx={{ height: 8, borderRadius: 4 }}
        />
      </Box>

      <Stack spacing={0.5}>
        <MetaRow
          label="Attempts"
          value={formatAttempts(job.attempts, job.maxAttempts)}
        />
        <MetaRow label="Created" value={formatAbsoluteTime(job.createdAt)} />
        <MetaRow label="Queued" value={formatAbsoluteTime(job.queuedAt)} />
        <MetaRow label="Started" value={formatAbsoluteTime(job.startedAt)} />
        <MetaRow
          label="Completed"
          value={formatAbsoluteTime(job.completedAt)}
        />
        {job.cancellationRequestedAt !== null && (
          <MetaRow
            label="Cancel requested"
            value={formatAbsoluteTime(job.cancellationRequestedAt)}
          />
        )}
        {job.cancelReason !== null && (
          <MetaRow label="Cancel reason" value={job.cancelReason} />
        )}
      </Stack>

      {job.errorCode !== null || job.errorMessage !== null ? (
        <Alert severity="error">
          <Typography variant="body2" fontWeight={700}>
            {job.errorCode ?? "error"}
          </Typography>
          {job.errorMessage !== null && (
            <Typography variant="body2">{job.errorMessage}</Typography>
          )}
        </Alert>
      ) : null}

      <Box>
        <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
          Payload
        </Typography>
        <CodeBlock value={formatJson(job.payload)} />
      </Box>

      <Box>
        <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
          Result
        </Typography>
        <CodeBlock value={formatJson(job.result)} />
      </Box>
    </Stack>
  );
}

export function JobDetailDialog({
  jobId,
  onClose,
}: IJobDetailDialogProps): JSX.Element {
  const theme = useTheme();
  const fullScreen = useMediaQuery(theme.breakpoints.down("sm"));
  const isOpen = jobId !== null;
  const { data: job, isLoading, isError } = useJob(jobId);
  const { data: events } = useJobEvents(jobId);
  const cancelMutation = useCancelJob();

  const handleCancel = (): void => {
    if (jobId !== null) {
      cancelMutation.mutate({ jobId });
    }
  };

  const canCancel = job !== undefined && isCancellable(job.status);

  return (
    <Dialog
      open={isOpen}
      onClose={onClose}
      maxWidth="sm"
      fullWidth
      fullScreen={fullScreen}
    >
      <DialogTitle>
        {job !== undefined ? `Job ${shortId(job.jobId)}` : "Job"}
      </DialogTitle>
      <DialogContent dividers>
        {isLoading ? (
          <Skeleton variant="rounded" height={320} />
        ) : isError || job === undefined ? (
          <Alert severity="error">Failed to load job.</Alert>
        ) : (
          <Stack spacing={2}>
            <JobBody job={job} />
            <Divider />
            <Box>
              <Typography variant="subtitle2" sx={{ mb: 1 }}>
                Events
              </Typography>
              <EventTimeline events={events ?? []} />
            </Box>
            {cancelMutation.isError && (
              <Alert severity="error">{cancelMutation.error.message}</Alert>
            )}
          </Stack>
        )}
      </DialogContent>
      <DialogActions>
        {canCancel && (
          <Button
            color="warning"
            onClick={handleCancel}
            disabled={cancelMutation.isPending}
          >
            {cancelMutation.isPending ? "Cancelling..." : "Cancel job"}
          </Button>
        )}
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}
