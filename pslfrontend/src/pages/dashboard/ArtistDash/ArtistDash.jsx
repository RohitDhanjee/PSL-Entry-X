import React, { useState,useEffect } from 'react';
import { Outlet, Link, useLocation } from 'react-router-dom';
import {
  LayoutDashboard,
  Settings,
  Menu,
  X,
  Ticket,
  Scan,
  UploadCloud
} from 'lucide-react';
import { useAuth } from '../../../context/AuthContext';
const ArtistDash = () => {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const location = useLocation();
  const { user } = useAuth();
  const isAdmin=window.location.href.includes('/admin')
  
  // Authorized PSL Issuers (Same as in UploadArtworks)
  const AUTHORIZED_PSL_ISSUERS = ["rohitdhanjee25@gmail.com", "admin@pslentryx.com"];
  const isAuthorizedIssuer = user && AUTHORIZED_PSL_ISSUERS.includes(user.email?.toLowerCase());

  

useEffect(() => {
  if (sidebarOpen) {
    document.body.classList.add('overflow-hidden');
  } else {
    document.body.classList.remove('overflow-hidden');
  }
}, [sidebarOpen]);

  const isActive = (path) => {
    return location.pathname === path || location.pathname.startsWith(path + '/');
  };

  const closeSidebar = () => {
    setSidebarOpen(false);
  };
  
  const navItems = [
    {
      name: 'Dashboard',
      path: '/dashboard',
      icon: <LayoutDashboard className="h-5 w-5" />
    },
    {
      name: 'PSL Tickets',
      path: '/dashboard/psl-tickets',
      icon: <Ticket className="h-5 w-5" />
    },
    ...(isAuthorizedIssuer ? [{
      name: 'Upload PSL',
      path: '/dashboard/upload',
      icon: <UploadCloud className="h-5 w-5" />,
      badge: 'ISSUER'
    }] : []),
    ...(isAuthorizedIssuer ? [{
      name: 'Gate Scanner',
      path: '/dashboard/gate-scanner',
      icon: <Scan className="h-5 w-5" />,
      badge: 'STAFF'
    }] : []),
    {
      name: 'Settings',
      path: '/dashboard/settings',
      icon: <Settings className="h-5 w-5" />
    }
  ];

  const items = navItems;
  return (
    <div className="min-h-screen flex bg-gray-50">
      {/* Mobile sidebar */}
      <div 
        className={`fixed inset-0 z-90 md:hidden  ${sidebarOpen ? 'block ' : 'hidden'}`}
        aria-hidden="true"
      >
        <div 
          className="absolute inset-0 bg-gray-600 bg-opacity-75 transition-opacity"
          onClick={() => setSidebarOpen(false)}
        ></div>
        
        <div className="fixed inset-0 flex z-40">
          <div className="relative flex-1 flex flex-col max-w-xs w-full bg-white">
            <div className="absolute top-0 right-0 -mr-12 pt-2">
              <button
                type="button"
                className="ml-1 flex items-center justify-center h-10 w-10 rounded-full focus:outline-none focus:ring-2 focus:ring-inset focus:ring-white"
                onClick={() => setSidebarOpen(false)}
              >
                <span className="sr-only">Close sidebar</span>
                <X className="h-6 w-6 text-white" aria-hidden="true" />
              </button>
            </div>
            
            <div className="flex-1 h-0 pt-5 pb-4 overflow-y-auto">
            
              <nav className="mt-5 px-2 space-y-1">
                {items.map((item) => (
                  <Link
                    key={item.name}
                    to={item.path}
                    className={`
                      group flex items-center px-2 py-2 text-base font-medium rounded-md
                      ${isActive(item.path) 
                        ? 'bg-emerald-700 text-white' 
                        : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'}
                    `}
                    onClick={closeSidebar}
                  >
                    {item.icon}
                    <span className="ml-3">{item.name}</span>
                    {item.badge && (
                      <span className="ml-auto px-2 py-0.5 text-xs font-medium bg-yellow-500 text-black rounded-full">
                        {item.badge}
                      </span>
                    )}
                  </Link>
                ))}
              </nav>
            </div>
           
          </div>
          <div className="flex-shrink-0 w-14"></div>
        </div>
      </div>
      
      {/* Desktop sidebar */}
      <div className="hidden md:flex md:flex-shrink-0">
        <div className="flex flex-col w-64">
          <div className="flex flex-col h-0 flex-1 border-r border-gray-200 bg-white">
            <div className="flex-1 flex flex-col pt-5 pb-4 overflow-y-auto">
             
              <nav className="mt-5 flex-1 px-2 bg-white space-y-1">
                {items.map((item) => (
                  <Link
                    key={item.name}
                    to={item.path}
                    className={`
                      group flex items-center px-2 py-2 text-sm font-medium rounded-md 
                      ${isActive(item.path) 
                        ? 'bg-emerald-700 text-white' 
                        : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'}
                    `}
                  >
                    {item.icon}
                    <span className="ml-3">{item.name}</span>
                    {item.badge && (
                      <span className="ml-auto px-2 py-0.5 text-xs font-medium bg-yellow-500 text-black rounded-full">
                        {item.badge}
                      </span>
                    )}
                  </Link>
                ))}
              </nav>
            </div>
            
          </div>
        </div>
      </div>
      
      <div className="flex flex-col w-0 flex-1 overflow-hidden">
        <div className="md:hidden pl-1 pt-1 sm:pl-3 sm:pt-3">
          <button
            type="button"
            className="-ml-0.5 -mt-0.5 h-12 w-12 inline-flex items-center justify-center rounded-md text-gray-500 hover:text-gray-900 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-emerald-500"
            onClick={() => setSidebarOpen(true)}
          >
            <span className="sr-only">Open sidebar</span>
            <Menu className="h-6 w-6" aria-hidden="true" />
          </button>
        </div>
        <main className="flex-1 relative z-0 overflow-y-auto focus:outline-none pt-[64px] sm:pt-[80px]">

          <div className="py-6">
            <div className="max-w-7xl mx-auto px-4 sm:px-6 md:px-8">
              <Outlet />
            </div>
          </div>
        </main>
      </div>
    </div>
  );
};

export default ArtistDash;