import React, { useEffect } from 'react';
import { useSelector, useDispatch } from 'react-redux';
import Sidebar from './components/Sidebar';
import ToastContainer from './components/ToastContainer';
import Dashboard from './pages/Dashboard';
import Accounts from './pages/Accounts';
import Campaigns from './pages/Campaigns';
import Profiles from './pages/Profiles';
import Automation from './pages/Automation';
import { ToastProvider } from './hooks/useToast';
import { setActiveTab } from './store/tabSlice';
import { fetchAccounts } from './store/accountsSlice';

function AppContent() {
  const dispatch = useDispatch();
  const activeTab = useSelector((state) => state.tab.activeTab);

  useEffect(() => {
    // Cargar cuentas globalmente al iniciar la app y mantener sondeo cada 10s
    dispatch(fetchAccounts());
    const interval = setInterval(() => {
      dispatch(fetchAccounts());
    }, 10000);
    return () => clearInterval(interval);
  }, [dispatch]);

  const handleTabChange = (tab) => {
    dispatch(setActiveTab(tab));
  };

  return (
    <div className="app-shell">
      <Sidebar activeTab={activeTab} setActiveTab={handleTabChange} />

      <main className="main-content">
        {activeTab === 'dashboard'  && <Dashboard  activeTab={activeTab} />}
        {activeTab === 'accounts'   && <Accounts   activeTab={activeTab} />}
        {activeTab === 'campaigns'  && <Campaigns  activeTab={activeTab} />}
        {activeTab === 'profiles'   && <Profiles   activeTab={activeTab} />}
        {activeTab === 'automation' && <Automation activeTab={activeTab} />}
      </main>

      <ToastContainer />
    </div>
  );
}

export default function App() {
  return (
    <ToastProvider>
      <AppContent />
    </ToastProvider>
  );
}
