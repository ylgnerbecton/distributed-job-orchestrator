import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import Typography from "@mui/material/Typography";

import { useJobSummary } from "../api/queries";
import type { TJobStatus } from "../api/types";
import { statusColor, titleCase } from "../format";
import type { TChipColor } from "../format";
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

const ACCENT_COLOR: Record<TChipColor, string> = {
  default: "grey.400",
  primary: "primary.main",
  secondary: "secondary.main",
  info: "info.main",
  success: "success.main",
  warning: "warning.main",
  error: "error.main",
};

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
            gridTemplateColumns: "repeat(auto-fit, minmax(112px, 1fr))",
            gap: { xs: 1.25, sm: 2 },
          }}
        >
          {STATUS_ORDER.map((status) => (
            <Box
              key={status}
              sx={{
                borderRadius: 2,
                border: 1,
                borderColor: "divider",
                borderTop: 3,
                borderTopColor: ACCENT_COLOR[statusColor(status)],
                py: 1.5,
                px: 1,
                textAlign: "center",
                bgcolor: "background.paper",
              }}
            >
              <Typography
                variant="h4"
                component="div"
                fontWeight={700}
                sx={{ fontSize: { xs: "1.6rem", sm: "2rem" }, lineHeight: 1.2 }}
              >
                {data.counts[status] ?? 0}
              </Typography>
              <Typography
                variant="caption"
                color="text.secondary"
                sx={{
                  textTransform: "uppercase",
                  letterSpacing: "0.04em",
                  fontWeight: 600,
                }}
              >
                {titleCase(status)}
              </Typography>
            </Box>
          ))}
        </Box>
      )}
    </Panel>
  );
}
