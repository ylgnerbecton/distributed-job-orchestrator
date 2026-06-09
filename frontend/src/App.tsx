import AppBar from "@mui/material/AppBar";
import Box from "@mui/material/Box";
import Container from "@mui/material/Container";
import CssBaseline from "@mui/material/CssBaseline";
import Stack from "@mui/material/Stack";
import Toolbar from "@mui/material/Toolbar";
import Typography from "@mui/material/Typography";
import { ThemeProvider } from "@mui/material/styles";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { USER_ID } from "./config";
import { HealthIndicator } from "./components/HealthIndicator";
import { JobsTable } from "./components/JobsTable";
import { StatusSummary } from "./components/StatusSummary";
import { SubmitJobForm } from "./components/SubmitJobForm";
import { theme } from "./theme";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
    },
  },
});

export default function App(): JSX.Element {
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
          <Toolbar sx={{ justifyContent: "space-between", gap: 1 }}>
            <Box sx={{ minWidth: 0 }}>
              <Typography variant="h6" noWrap>
                Distributed Job Orchestrator
              </Typography>
              <Typography
                variant="caption"
                color="text.secondary"
                noWrap
                sx={{ display: { xs: "none", sm: "block" } }}
              >
                Asynchronous job processing - user {USER_ID}
              </Typography>
            </Box>
            <HealthIndicator />
          </Toolbar>
        </AppBar>
        <Container
          maxWidth="lg"
          sx={{ py: { xs: 2, sm: 3 }, px: { xs: 1.5, sm: 3 } }}
        >
          <Stack spacing={{ xs: 2, sm: 3 }}>
            <StatusSummary />
            <Box
              sx={{
                display: "grid",
                gridTemplateColumns: {
                  xs: "1fr",
                  md: "minmax(280px, 1fr) 2fr",
                },
                gap: { xs: 2, sm: 3 },
                alignItems: "start",
              }}
            >
              <SubmitJobForm />
              <JobsTable />
            </Box>
          </Stack>
        </Container>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
