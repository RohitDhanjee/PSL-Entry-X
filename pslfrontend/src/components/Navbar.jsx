import React, { useEffect, useState } from "react";
import { Menu, X } from "lucide-react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Button } from "@mui/material";
import WalletButton from "./WalletButton";
import NetworkSelector from "./NetworkSelector";
import { useAuth } from "../context/AuthContext";
import { useWeb3 } from "../context/Web3Context";

const Navbar = () => {
  const { isAuthenticated, isInitialized, logout, user } = useAuth();
  const { connected, account } = useWeb3();
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();

  const toggleMenu = () => setIsMenuOpen(!isMenuOpen);
  const closeMenu = () => setIsMenuOpen(false);

  const isActive = (path) => location.pathname === path;

  const handleLogout = () => {
    logout();
    navigate("/auth");
  };

  // Debug authentication state
  useEffect(() => {
    console.log("Navbar Auth State:", {
      isInitialized,
      isAuthenticated,
      connected,
      account: account ? `${account.substring(0, 6)}...` : null,
    });
  }, [isInitialized, isAuthenticated, connected, account]);

  // Show wallet button condition: user is authenticated OR wallet is connected
  const shouldShowWalletButton = isAuthenticated || connected;

  if (!isInitialized) {
    return (
      <nav className="bg-white shadow-sm sticky top-0 z-50 py-2">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between h-16">
            <div className="flex items-center">
              <Link to="/" className="flex-shrink-0 flex items-center">
                <img src="/PSL%20Entry%20X.jpeg" alt="PSL Entry X" className="h-12 w-auto ms-1 object-contain" />
              </Link>
            </div>
            {/* Show loading state */}
            <div className="flex items-center">
              <div className="animate-pulse bg-gray-200 h-8 w-20 rounded"></div>
            </div>
          </div>
        </div>
      </nav>
    );
  }

  return (
    <nav className="bg-white shadow-sm sticky top-0 z-50 py-2">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex justify-between h-16">
          {/* Left side logo + nav */}
          <div className="flex items-center">
            <Link to="/" className="flex-shrink-0 flex items-center">
              <img src="/PSL%20Entry%20X.jpeg" alt="PSL Entry X" className="h-12 w-auto ms-1 object-contain" />
            </Link>

            {/* Desktop Navigation */}
            <div className="hidden md:ml-6 md:flex md:space-x-8 !ms-28">
              <Link
                to="/"
                className={`inline-flex items-center px-1 pt-1 border-b-2 text-sm font-medium ${
                  isActive("/")
                    ? "border-emerald-600 text-gray-900"
                    : "border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700"
                }`}
              >
                Home
              </Link>
              <Link
                to="/explorer"
                className={`inline-flex items-center px-1 pt-1 border-b-2 text-sm font-medium ${
                  isActive("/explorer")
                    ? "border-emerald-600 text-gray-900"
                    : "border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700"
                }`}
              >
                Explorer
              </Link>
            </div>
          </div>

          {/* Right side buttons (Desktop) */}
          <div className="hidden md:flex md:items-center md:space-x-4">
            {/* Network selector - only after sign in */}
            {isAuthenticated && (
              <div className="relative z-[9999]">
                <NetworkSelector />
              </div>
            )}

            {/* Wrap wallet button so dropdown shows on top - only show when authenticated */}
            {isAuthenticated && (
              <div className="relative z-[9999]">
                <WalletButton />
              </div>
            )}

            {isAuthenticated ? (
              <div
                style={{ display: "flex", alignItems: "center", gap: "8px" }}
              >
                <Link to="/dashboard" style={{ textDecoration: "none" }}>
                  <Button variant="outlined" color="success" size="small">
                    Dashboard
                  </Button>
                </Link>

                <Button
                  variant="contained"
                  color="error"
                  size="small"
                  onClick={handleLogout}
                >
                  Logout
                </Button>
              </div>
            ) : (
              <Link to="/auth" style={{ textDecoration: "none" }}>
                <Button variant="contained" color="success" size="small">
                  Sign In
                </Button>
              </Link>
            )}
          </div>

          {/* Mobile menu button */}
          <div className="flex items-center md:hidden">
            <button
              onClick={toggleMenu}
              className="inline-flex items-center justify-center p-2 rounded-md text-gray-400 hover:text-gray-500 hover:bg-gray-100 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-emerald-500"
            >
              {isMenuOpen ? (
                <X className="h-6 w-6" aria-hidden="true" />
              ) : (
                <Menu className="h-6 w-6" aria-hidden="true" />
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Mobile Menu */}
      {isMenuOpen && (
        <div className="md:hidden">
          <div className="pt-2 pb-3 space-y-1">
            <Link
              to="/"
              className={`block pl-3 pr-4 py-2 border-l-4 text-base font-medium ${
                isActive("/")
                  ? "border-emerald-600 text-emerald-700 bg-emerald-50"
                  : "border-transparent text-gray-500 hover:bg-gray-50 hover:border-gray-300 hover:text-gray-700"
              }`}
              onClick={closeMenu}
            >
              PSL Entry X Home
            </Link>
            <Link
              to="/explorer"
              className={`block pl-3 pr-4 py-2 border-l-4 text-base font-medium ${
                isActive("/explorer")
                  ? "border-emerald-600 text-emerald-700 bg-emerald-50"
                  : "border-transparent text-gray-500 hover:bg-gray-50 hover:border-gray-300 hover:text-gray-700"
              }`}
              onClick={closeMenu}
            >
              Explorer
            </Link>
          </div>

          {/* Mobile Auth Buttons */}
          <div className="pt-4 pb-3 border-t border-gray-200 px-4 space-y-2">
            {/* Network selector in mobile - only after sign in */}
            {isAuthenticated && (
              <div className="py-2">
                <NetworkSelector />
              </div>
            )}

            {/* Show WalletButton in mobile - only when authenticated */}
            {isAuthenticated && (
              <div className="py-2">
                <WalletButton />
              </div>
            )}

            {isAuthenticated ? (
              <>
                <Link
                  to="/dashboard"
                  style={{ textDecoration: "none" }}
                  onClick={() => {
                    console.log("Dashboard clicked - Auth State:", {
                      isAuthenticated,
                      isInitialized,
                      userRole: user?.role,
                    });
                  }}
                >
                  <Button variant="outlined" color="success" size="small">
                    Dashboard
                  </Button>
                </Link>
                <Button
                  variant="contained"
                  color="error"
                  fullWidth
                  onClick={() => {
                    closeMenu();
                    handleLogout();
                  }}
                >
                  Logout
                </Button>
              </>
            ) : (
              <Link to="/auth" onClick={closeMenu}>
                <Button variant="contained" color="success" fullWidth>
                  Sign In
                </Button>
              </Link>
            )}
          </div>
        </div>
      )}
    </nav>
  );
};

export default Navbar;
