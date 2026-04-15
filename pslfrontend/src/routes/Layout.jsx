import React, { useEffect } from 'react';
import { Outlet } from 'react-router-dom';
import Navbar from '../components/Navbar';
import Footer from '../components/Footer';
import PageTransition from '../components/PageTransition';
import NavigationLoader from '../components/NavigationLoader';
import { useAuth } from '../context/AuthContext';
import axios from 'axios';

const MainLayout = () => {
  const { isAuthenticated, logout, isInitialized, user } = useAuth();

  useEffect(() => {
    // Only run this effect once the auth context is initialized
    if (!isInitialized) return;

    const token = localStorage.getItem('token');
    
    // If we have a token, validate it by checking if it's a proper JWT
    if (token) {
      try {
        // Basic JWT validation - check if it has 3 parts
        const tokenParts = token.split('.');
        if (tokenParts.length !== 3) {
          console.warn('Invalid JWT format, clearing token');
          localStorage.removeItem('token');
          localStorage.removeItem('userData');
          if (isAuthenticated) {
            logout('MainLayout-invalidJWT');
          }
          return;
        }

        // Decode the payload to check expiration
        const payload = JSON.parse(atob(tokenParts[1]));
        const currentTime = Math.floor(Date.now() / 1000);
        
        // Check if token is expired (exp is in seconds, not milliseconds)
        if (payload.exp && payload.exp < currentTime) {
          console.warn('Token expired, clearing auth');
          localStorage.removeItem('token');
          localStorage.removeItem('userData');
          if (isAuthenticated) {
            logout('MainLayout-tokenExpired');
          }
          return;
        }

        // Token is valid, ensure axios has the auth header
        axios.defaults.headers.common['Authorization'] = `Bearer ${token}`;
        
      } catch (error) {
        console.error('Error validating token:', error);
        // If we can't parse the token, it's invalid
        localStorage.removeItem('token');
        localStorage.removeItem('userData');
        if (isAuthenticated) {
          logout('MainLayout-tokenParseError');
        }
      }
    } else {
      // No token found, clear any existing auth headers
      delete axios.defaults.headers.common['Authorization'];
      
      // If auth context thinks we're authenticated but there's no token, logout
      if (isAuthenticated) {
        console.warn('No token found but auth context shows authenticated, logging out');
        logout('MainLayout-noToken');
      }
    }
  }, [isInitialized, isAuthenticated, logout]);

  // Set up axios interceptor for automatic token management (only once)
  useEffect(() => {
    const requestInterceptor = axios.interceptors.request.use(
      (config) => {
        const safeConfig = config || {};
        safeConfig.headers = safeConfig.headers || {};
        safeConfig.method = safeConfig.method || 'get';

        const token = localStorage.getItem('token');
        if (token) {
          safeConfig.headers.Authorization = `Bearer ${token}`;
        }
        return safeConfig;
      },
      (error) => Promise.reject(error)
    );

    const responseInterceptor = axios.interceptors.response.use(
      (response) => response,
      (error) => {
        // Handle 401 errors globally
        if (error.response?.status === 401 && !error.config?.url?.includes('/auth/')) {
          console.warn('Received 401, clearing auth');
          localStorage.removeItem('token');
          localStorage.removeItem('userData');
          if (isAuthenticated) {
            logout('MainLayout-401Response');
          }
        }
        return Promise.reject(error);
      }
    );

    // Cleanup interceptors
    return () => {
      axios.interceptors.request.eject(requestInterceptor);
      axios.interceptors.response.eject(responseInterceptor);
    };
  }, [isAuthenticated, logout]);

  return (
    <div className="flex flex-col min-h-screen">
      <NavigationLoader />
      <Navbar />
      <main className="flex-grow">
        <PageTransition>
          <Outlet />
        </PageTransition>
      </main>
      <Footer />
    </div>
  );
};

export default MainLayout;