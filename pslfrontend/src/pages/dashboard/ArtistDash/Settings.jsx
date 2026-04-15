import React from 'react';
import SecuritySettings from '../../../components/settings/SecuritySettings';

const Settings = () => {
  console.log('🔄 Settings page rendered'); // ✅ ADD THIS
  console.log('SecuritySettings component:', SecuritySettings); // ✅ ADD THIS
  return (
    <div className="min-h-screen bg-gray-50 py-8">
      <SecuritySettings />
    </div>
  );
};

export default Settings;