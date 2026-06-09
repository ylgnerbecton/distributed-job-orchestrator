import { createTheme } from "@mui/material/styles";

export const theme = createTheme({
  palette: {
    mode: "light",
    primary: { main: "#2563eb" },
    secondary: { main: "#7c3aed" },
    background: { default: "#f1f5f9", paper: "#ffffff" },
    divider: "#e2e8f0",
    text: { primary: "#0f172a", secondary: "#64748b" },
  },
  shape: { borderRadius: 12 },
  typography: {
    fontFamily: 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
    h6: { fontWeight: 700 },
    subtitle2: { fontWeight: 700 },
    button: { textTransform: "none", fontWeight: 600 },
  },
  components: {
    MuiPaper: {
      styleOverrides: {
        outlined: { borderColor: "#e2e8f0" },
      },
    },
    MuiTableCell: {
      styleOverrides: {
        root: { borderColor: "#eef2f7" },
        head: { fontWeight: 700, color: "#475569", backgroundColor: "#f8fafc" },
      },
    },
    MuiChip: {
      styleOverrides: {
        sizeSmall: { fontWeight: 600 },
      },
    },
    MuiAppBar: {
      styleOverrides: {
        colorDefault: { backgroundColor: "#ffffff" },
      },
    },
  },
});
