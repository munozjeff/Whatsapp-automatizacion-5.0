import { configureStore } from '@reduxjs/toolkit';
import accountsReducer from './accountsSlice';
import tabReducer from './tabSlice';

export const store = configureStore({
  reducer: {
    accounts: accountsReducer,
    tab: tabReducer,
  },
});
