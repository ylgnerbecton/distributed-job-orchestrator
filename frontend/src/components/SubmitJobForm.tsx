import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import MenuItem from "@mui/material/MenuItem";
import Snackbar from "@mui/material/Snackbar";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import { useState } from "react";
import type { ChangeEvent } from "react";

import { useSubmitJob } from "../api/queries";
import type { IJobSubmitRequest, TJobPriority, TJobType } from "../api/types";
import { titleCase } from "../format";
import { Panel } from "./Panel";

const JOB_TYPES: readonly TJobType[] = [
  "sleep",
  "report",
  "flaky",
  "always_fail",
  "llm_summary",
];

const PRIORITIES: readonly TJobPriority[] = ["low", "normal", "high"];

const DEFAULT_PAYLOADS: Record<TJobType, Record<string, unknown>> = {
  sleep: { duration_seconds: 8, steps: 8 },
  report: { pages: 4 },
  flaky: { fail_times: 2 },
  always_fail: {},
  llm_summary: { prompt: "Summarize the report", tokens: 150 },
};

const TYPE_DESCRIPTIONS: Record<TJobType, string> = {
  sleep: "Long-running task that reports progress and supports cancellation.",
  report: "Multi-step report generation that produces a small result.",
  flaky: "Fails a set number of times, then succeeds (exercises retries).",
  always_fail: "Non-retryable validation failure.",
  llm_summary:
    "Simulated language-model call; a provider rate limit is retryable.",
};

const DEFAULT_TYPE: TJobType = "sleep";
const DEFAULT_PRIORITY: TJobPriority = "normal";
const SNACKBAR_DURATION_MS = 5000;

function stringifyPayload(value: Record<string, unknown>): string {
  return JSON.stringify(value, null, 2);
}

function parsePayload(raw: string): Record<string, unknown> {
  const trimmed = raw.trim();
  const parsed: unknown = trimmed.length === 0 ? {} : JSON.parse(trimmed);
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Payload must be a JSON object.");
  }
  return parsed as Record<string, unknown>;
}

export function SubmitJobForm(): JSX.Element {
  const submitMutation = useSubmitJob();
  const [jobType, setJobType] = useState<TJobType>(DEFAULT_TYPE);
  const [priority, setPriority] = useState<TJobPriority>(DEFAULT_PRIORITY);
  const [payloadText, setPayloadText] = useState<string>(
    stringifyPayload(DEFAULT_PAYLOADS[DEFAULT_TYPE]),
  );
  const [maxAttempts, setMaxAttempts] = useState<string>("");
  const [idempotencyKey, setIdempotencyKey] = useState<string>("");
  const [payloadError, setPayloadError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);

  const handleTypeChange = (event: ChangeEvent<HTMLInputElement>): void => {
    const nextType = event.target.value as TJobType;
    setJobType(nextType);
    setPayloadText(stringifyPayload(DEFAULT_PAYLOADS[nextType]));
    setPayloadError(null);
  };

  const handleSubmit = (): void => {
    let payload: Record<string, unknown>;
    try {
      payload = parsePayload(payloadText);
    } catch (error) {
      setPayloadError(
        error instanceof Error ? error.message : "Invalid JSON payload.",
      );
      return;
    }
    setPayloadError(null);

    const request: IJobSubmitRequest = {
      type: jobType,
      payload,
      priority,
    };
    const parsedMaxAttempts = Number.parseInt(maxAttempts, 10);
    if (maxAttempts.trim().length > 0 && Number.isFinite(parsedMaxAttempts)) {
      request.maxAttempts = parsedMaxAttempts;
    }
    if (idempotencyKey.trim().length > 0) {
      request.idempotencyKey = idempotencyKey.trim();
    }

    submitMutation.mutate(request, {
      onSuccess: (result) => {
        setFeedback(`Submitted job ${result.jobId}`);
      },
    });
  };

  const isSubmitting = submitMutation.isPending;

  return (
    <Panel title="Submit Job">
      <Stack spacing={2}>
        <TextField
          select
          label="Type"
          value={jobType}
          onChange={handleTypeChange}
          helperText={TYPE_DESCRIPTIONS[jobType]}
          fullWidth
          size="small"
        >
          {JOB_TYPES.map((type) => (
            <MenuItem key={type} value={type}>
              {titleCase(type)}
            </MenuItem>
          ))}
        </TextField>

        <TextField
          select
          label="Priority"
          value={priority}
          onChange={(event) => setPriority(event.target.value as TJobPriority)}
          fullWidth
          size="small"
        >
          {PRIORITIES.map((value) => (
            <MenuItem key={value} value={value}>
              {titleCase(value)}
            </MenuItem>
          ))}
        </TextField>

        <TextField
          label="Payload (JSON)"
          value={payloadText}
          onChange={(event) => setPayloadText(event.target.value)}
          error={payloadError !== null}
          helperText={payloadError ?? " "}
          multiline
          minRows={5}
          fullWidth
          size="small"
          sx={{ "& textarea": { fontFamily: "ui-monospace, monospace" } }}
        />

        <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
          <TextField
            label="Max attempts"
            value={maxAttempts}
            onChange={(event) => setMaxAttempts(event.target.value)}
            type="number"
            size="small"
            fullWidth
            slotProps={{ htmlInput: { min: 1 } }}
          />
          <TextField
            label="Idempotency-Key"
            value={idempotencyKey}
            onChange={(event) => setIdempotencyKey(event.target.value)}
            size="small"
            fullWidth
          />
        </Stack>

        {submitMutation.isError && (
          <Alert severity="error">{submitMutation.error.message}</Alert>
        )}

        <Button
          variant="contained"
          onClick={handleSubmit}
          disabled={isSubmitting}
        >
          {isSubmitting ? "Submitting..." : "Submit"}
        </Button>
      </Stack>

      <Snackbar
        open={feedback !== null}
        autoHideDuration={SNACKBAR_DURATION_MS}
        onClose={() => setFeedback(null)}
        anchorOrigin={{ vertical: "bottom", horizontal: "center" }}
      >
        <Alert
          severity="success"
          onClose={() => setFeedback(null)}
          sx={{ width: "100%" }}
        >
          {feedback}
        </Alert>
      </Snackbar>
    </Panel>
  );
}
