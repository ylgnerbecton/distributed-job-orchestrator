import AddIcon from "@mui/icons-material/Add";
import AppBar from "@mui/material/AppBar";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import CssBaseline from "@mui/material/CssBaseline";
import Stack from "@mui/material/Stack";
import Toolbar from "@mui/material/Toolbar";
import Typography from "@mui/material/Typography";
import { ThemeProvider } from "@mui/material/styles";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

import { USER_ID } from "./config";
import { HealthIndicator } from "./components/HealthIndicator";
import { JobsTable } from "./components/JobsTable";
import { StatusSummary } from "./components/StatusSummary";
import { SubmitJobDialog } from "./components/SubmitJobDialog";
import { theme } from "./theme";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
    },
  },
});

export default function App(): JSX.Element {
  const [submitOpen, setSubmitOpen] = useState(false);

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <AppBar
          position="sticky"
          color="default"
          elevation={0}
          sx={{ borderBottom: 1, borderColor: "divider" }}
        >
          <Toolbar sx={{ gap: { xs: 1, sm: 2 } }}>
            <Box sx={{ minWidth: 0, flexGrow: 1 }}>
              <Typography variant="h6" noWrap>
                Distributed Job Orchestrator
              </Typography>
              <Typography
                variant="caption"
                color="text.secondary"
                noWrap
                sx={{ display: { xs: "none", md: "block" } }}
              >
                Asynchronous job processing - user {USER_ID}
              </Typography>
            </Box>
            <HealthIndicator />
            <Button
              variant="contained"
              startIcon={<AddIcon />}
              onClick={() => setSubmitOpen(true)}
              sx={{ flexShrink: 0 }}
            >
              New job
            </Button>
          </Toolbar>
        </AppBar>
        <Box
          component="main"
          sx={{
            maxWidth: 1600,
            mx: "auto",
            px: { xs: 1.5, sm: 3, lg: 4 },
            py: { xs: 2, sm: 3 },
          }}
        >
          <Stack spacing={{ xs: 2, sm: 3 }}>
            <StatusSummary />
            <JobsTable onNewJob={() => setSubmitOpen(true)} />
          </Stack>
        </Box>
        <SubmitJobDialog
          open={submitOpen}
          onClose={() => setSubmitOpen(false)}
        />
      </ThemeProvider>
    </QueryClientProvider>
  );
}
