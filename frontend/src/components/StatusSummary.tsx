import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { useJobSummary } from "../api/queries";
import type { TJobStatus } from "../api/types";
import { statusColor, titleCase } from "../format";
import { Panel } from "./Panel";

const STATUS_ORDER: readonly TJobStatus[] = [
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

export function StatusSummary(): JSX.Element {
  const { data, isLoading, isError } = useJobSummary();

  return (
    <Panel
      title="Status Summary"
      isLoading={isLoading}
      isError={isError || data === undefined}
      errorMessage="Failed to load status summary."
      skeletonHeight={120}
      action={
        data !== undefined ? (
          <Chip label={`${data.total} total`} color="primary" size="small" />
        ) : undefined
      }
    >
      {data !== undefined && (
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: {
              xs: "repeat(2, 1fr)",
              sm: "repeat(3, 1fr)",
              md: "repeat(5, 1fr)",
            },
            gap: 2,
          }}
        >
          {STATUS_ORDER.map((status) => (
            <Box
              key={status}
              sx={{
                textAlign: "center",
                py: 2,
                borderRadius: 2,
                bgcolor: "action.hover",
              }}
            >
              <Typography variant="h4" component="div" fontWeight={700}>
                {data.counts[status] ?? 0}
              </Typography>
              <Stack alignItems="center" sx={{ mt: 0.5 }}>
                <Chip
                  label={titleCase(status)}
                  color={statusColor(status)}
                  size="small"
                />
              </Stack>
            </Box>
          ))}
        </Box>
      )}
    </Panel>
  );
}
