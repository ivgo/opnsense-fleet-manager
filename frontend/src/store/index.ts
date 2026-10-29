import { configureStore } from "@reduxjs/toolkit";

import authReducer from "./authSlice";
import uiReducer from "./uiSlice";

export const store = configureStore({
  reducer: {
    auth: authReducer,
    ui: uiReducer,
  },
  middleware: (getDefaultMiddleware) =>
    getDefaultMiddleware({
      serializableCheck: {
        ignoredActionPaths: ["meta.arg", "payload.timestamp"],
        ignoredPaths: ["ui.toast"],
      },
    }),
  devTools: import.meta.env.MODE !== "production",
});

export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;
