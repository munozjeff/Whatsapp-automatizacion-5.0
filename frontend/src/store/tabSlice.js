import { createSlice } from '@reduxjs/toolkit';

const VALID_TABS = ['dashboard', 'accounts', 'campaigns', 'profiles', 'automation'];

const initialTab = () => {
  try {
    const saved = localStorage.getItem('wa_active_tab');
    return VALID_TABS.includes(saved) ? saved : 'dashboard';
  } catch (e) {
    return 'dashboard';
  }
};

const tabSlice = createSlice({
  name: 'tab',
  initialState: {
    activeTab: initialTab(),
  },
  reducers: {
    setActiveTab(state, action) {
      state.activeTab = action.payload;
      try {
        localStorage.setItem('wa_active_tab', action.payload);
      } catch (e) {}
    },
  },
});

export const { setActiveTab } = tabSlice.actions;
export default tabSlice.reducer;
