import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Provider } from "react-redux";

import App from "@/App";
import { ApiError } from "@/api/client";
import { store } from "@/store";
import "@/index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 20_000,
      gcTime: 5 * 60_000,
      refetchOnWindowFocus: false,
      retry: (failureCount, error) => {
        if (error instanceof ApiError) {
          if (error.status === 401 || error.status === 403 || error.status === 404) return false;
          if (error.status >= 400 && error.status < 500) return failureCount < 1;
        }
        return failureCount < 2;
      },
    },
    mutations: { retry: 0 },
  },
});

const container = document.getElementById("root");
if (!container) {
  throw new Error("The #root container is missing from index.html");
}

createRoot(container).render(
  <StrictMode>
    <Provider store={store}>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </Provider>
  </StrictMode>,
);
