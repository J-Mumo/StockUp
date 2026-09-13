import { Outlet } from 'react-router-dom';
import Sidebar from './Sidebar';
import { Toaster } from 'react-hot-toast';
import LearnCard from './learn/LearnCard';

export default function Layout() {
  return (
    <div className="min-h-screen bg-dark-bg">
      <Toaster
        position="top-center"
        containerStyle={{ top: 72 }}
        toastOptions={{
          className: 'bg-dark-surface text-white border border-dark-border',
          duration: 4000,
        }}
      />
      <Sidebar />
      <main className="lg:ml-64 min-h-screen p-4 sm:p-6 pt-16 lg:pt-6">
        <Outlet />
      </main>
      <LearnCard />
    </div>
  );
}
