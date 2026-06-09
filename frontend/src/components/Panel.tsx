import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Paper from "@mui/material/Paper";
import Skeleton from "@mui/material/Skeleton";
import Typography from "@mui/material/Typography";
import type { ReactNode } from "react";

interface IPanelProps {
  title: string;
  action?: ReactNode;
  isLoading?: boolean;
  isError?: boolean;
  isEmpty?: boolean;
  errorMessage?: string;
  emptyMessage?: string;
  skeletonHeight?: number;
  children: ReactNode;
}

const DEFAULT_SKELETON_HEIGHT = 160;

export function Panel({
  title,
  action,
  isLoading = false,
  isError = false,
  isEmpty = false,
  errorMessage = "Failed to load data.",
  emptyMessage = "Nothing to show yet.",
  skeletonHeight = DEFAULT_SKELETON_HEIGHT,
  children,
}: IPanelProps): JSX.Element {
  return (
    <Paper variant="outlined" sx={{ p: { xs: 1.5, sm: 2.5 } }}>
      <Box
        sx={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: 1,
          mb: 2,
        }}
      >
        <Typography variant="h6">{title}</Typography>
        {action}
      </Box>
      {isLoading ? (
        <Skeleton variant="rounded" height={skeletonHeight} />
      ) : isError ? (
        <Alert severity="error">{errorMessage}</Alert>
      ) : isEmpty ? (
        <Typography color="text.secondary">{emptyMessage}</Typography>
      ) : (
        children
      )}
    </Paper>
  );
}
