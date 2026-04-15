import React, { createContext, useContext, useState, useEffect } from 'react';
import axios from 'axios';

const SettingsContext = createContext();

export const useSettings = () => useContext(SettingsContext);

export const SettingsProvider = ({ children }) => {
  const [settings, setSettings] = useState({
    platformFee: 2.5,
    enableCrypto: true,
    loading: true
  });

  const fetchSettings = async () => {
    try {
      const apiBase = (import.meta.env.VITE_BASE_URL_BACKEND || '').replace(/\/$/, '');

      // Primary endpoint lives under /tickets router in backend.
      let res;
      try {
        res = await axios.get(`${apiBase}/tickets/settings/global`);
      } catch (primaryError) {
        // Backward compatibility fallback for older deployments.
        res = await axios.get(`${apiBase}/settings/global`);
      }

      setSettings({
        platformFee: res.data.platform_fee ?? 2.5,
        enableCrypto: res.data.enable_crypto ?? true,
        loading: false
      });
    } catch (error) {
      console.error("Failed to load global settings:", error);
      // Fallback to defaults if API fails
      setSettings(prev => ({ ...prev, loading: false }));
    }
  };

  useEffect(() => {
    fetchSettings();
  }, []);

  // Function to refresh settings (called after Admin updates them)
  const refreshSettings = () => {
    fetchSettings();
  };

  return (
    <SettingsContext.Provider value={{ ...settings, refreshSettings }}>
      {children}
    </SettingsContext.Provider>
  );
};