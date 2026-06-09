import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import ErrorIcon from "@mui/icons-material/Error";
import Chip from "@mui/material/Chip";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import { useHealth } from "../api/queries";

export function HealthIndicator(): JSX.Element {
  const { data, isError } = useHealth();
  const isOnline = !isError && data?.status === "ok";
  const detail =
    data === undefined ? "" : `db ${data.database} / queue ${data.queue}`;
  return (
    <Stack direction="row" spacing={1.5} alignItems="center">
      {detail.length > 0 && (
        <Typography variant="caption" color="text.secondary">
          {detail}
        </Typography>
      )}
      <Chip
        color={isOnline ? "success" : "error"}
        icon={isOnline ? <CheckCircleIcon /> : <ErrorIcon />}
        label={isOnline ? "API online" : "API offline"}
        size="small"
      />
    </Stack>
  );
}
