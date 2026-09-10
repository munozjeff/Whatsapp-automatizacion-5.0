import { createSlice, createAsyncThunk } from '@reduxjs/toolkit';

// ── Async Thunks ──────────────────────────────────────────────────

export const fetchAccounts = createAsyncThunk(
  'accounts/fetchAccounts',
  async (_, { rejectWithValue }) => {
    try {
      const res = await fetch('/api/accounts');
      const data = await res.json();
      if (data.status === 'success') {
        return {
          accounts: data.accounts || [],
          diskMetrics: data.disk_metrics || { total_mb: 0, formatted: '0 MB' },
        };
      }
      return rejectWithValue(data.message || 'Error al obtener cuentas');
    } catch (err) {
      return rejectWithValue(err.message || 'Error de conexión');
    }
  }
);

export const updateAccountStatus = createAsyncThunk(
  'accounts/updateStatus',
  async (payload, { dispatch, rejectWithValue }) => {
    try {
      const res = await fetch('/api/accounts/status', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (data.status === 'success') {
        dispatch(fetchAccounts());
        return data;
      }
      return rejectWithValue(data.message);
    } catch (err) {
      return rejectWithValue(err.message);
    }
  }
);

export const openInstance = createAsyncThunk(
  'accounts/openInstance',
  async (accountId, { dispatch, rejectWithValue }) => {
    try {
      const res = await fetch(`/api/accounts/${accountId}/open`, { method: 'POST' });
      const data = await res.json();
      dispatch(fetchAccounts());
      if (data.status === 'success') return data;
      return rejectWithValue(data.message);
    } catch (err) {
      return rejectWithValue(err.message);
    }
  }
);

export const closeInstance = createAsyncThunk(
  'accounts/closeInstance',
  async (accountId, { dispatch, rejectWithValue }) => {
    try {
      const res = await fetch(`/api/accounts/${accountId}/close`, { method: 'POST' });
      const data = await res.json();
      dispatch(fetchAccounts());
      if (data.status === 'success') return data;
      return rejectWithValue(data.message);
    } catch (err) {
      return rejectWithValue(err.message);
    }
  }
);

export const deleteAccount = createAsyncThunk(
  'accounts/deleteAccount',
  async (accountId, { dispatch, rejectWithValue }) => {
    try {
      const res = await fetch(`/api/accounts/${accountId}/delete`, { method: 'DELETE' });
      const data = await res.json();
      if (data.status === 'success') {
        dispatch(fetchAccounts());
        return { accountId, message: data.message };
      }
      return rejectWithValue(data.message);
    } catch (err) {
      return rejectWithValue(err.message);
    }
  }
);

// ── Helper para restaurar cuentas en 0ms al recargar la página ──────
const getInitialAccounts = () => {
  try {
    const saved = localStorage.getItem('wa_cached_accounts');
    return saved ? JSON.parse(saved) : [];
  } catch (e) {
    return [];
  }
};

const accountsSlice = createSlice({
  name: 'accounts',
  initialState: {
    accounts: getInitialAccounts(),
    diskMetrics: { total_mb: 0, formatted: '0 MB' },
    loading: getInitialAccounts().length === 0,
    error: null,
    lastUpdated: null,
  },
  reducers: {
    setLocalAccounts(state, action) {
      state.accounts = action.payload;
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(fetchAccounts.pending, (state) => {
        if (state.accounts.length === 0) {
          state.loading = true;
        }
        state.error = null;
      })
      .addCase(fetchAccounts.fulfilled, (state, action) => {
        state.loading = false;
        state.accounts = action.payload.accounts;
        state.diskMetrics = action.payload.diskMetrics;
        state.lastUpdated = new Date().toISOString();
        try {
          localStorage.setItem('wa_cached_accounts', JSON.stringify(action.payload.accounts));
        } catch (e) {}
      })
      .addCase(fetchAccounts.rejected, (state, action) => {
        state.loading = false;
        state.error = action.payload;
      });
  },
});

export const { setLocalAccounts } = accountsSlice.actions;
export default accountsSlice.reducer;
