import React from 'react';
import { AuthProvider } from './AuthContext';

// This is just a wrapper component that provides the AuthContext
const AuthContextProvider = ({ children }) => {
  return (
    <AuthProvider>
      {children}
    </AuthProvider>
  );
};

export default AuthContextProvider;