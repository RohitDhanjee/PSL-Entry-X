import React from 'react'
import { Navigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext' // Use the hook instead of direct context

const ProtectedRoute = ({ children, requiredRole }) => {
  const { isAuthenticated, isInitialized, user, loading } = useAuth()

  console.log('ProtectedRoute Debug:', {
    isAuthenticated,
    isInitialized, 
    loading,
    userRole: user?.role,
    requiredRole
  });

  // Show loading while auth initializes
  if (!isInitialized || loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="animate-pulse text-lg">Loading...</div>
      </div>
    );
  }

  // Redirect to auth if not authenticated
  if (!isAuthenticated) {
    console.log('User not authenticated, redirecting to /auth');
    return <Navigate to="/auth" replace />;
  }

  // Check role if required (for admin routes)
  if (requiredRole && user?.role !== requiredRole) {
    console.log(`User role ${user?.role} doesn't match required role ${requiredRole}`);
    return <Navigate to="/" replace />;
  }

  console.log('ProtectedRoute: Access granted');
  return children;
}

export default ProtectedRoute