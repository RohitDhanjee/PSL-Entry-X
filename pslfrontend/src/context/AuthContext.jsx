import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  useRef,
} from "react";
import { useWeb3 } from "./Web3Context";
import { authAPI } from "../services/api";
import toast from "react-hot-toast";

const AuthContext = createContext(null);

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return context;
};

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(null);
  const [loading, setLoading] = useState(false);
  const [isInitialized, setIsInitialized] = useState(false);
  const [googleAuthInProgress, setGoogleAuthInProgress] = useState(false); // ✅ MOVED INSIDE COMPONENT
  const [is2FAEnabled, setIs2FAEnabled] = useState(false);
  const { account, connected, disconnectWallet: web3Disconnect } = useWeb3();

  // Refs to prevent unnecessary effects
  const loginInProgress = useRef(false);
  const lastAutoLinkAttempt = useRef(null);
  const logoutInProgress = useRef(false);

  useEffect(() => {
  const check2FAStatus = async () => {
    if (user && token) {
      try {
        const response = await authAPI.get2FAStatus();
        setIs2FAEnabled(response.enabled || false);
      } catch (error) {
        console.error('Failed to check 2FA status:', error);
      }
    }
  };

  check2FAStatus();
}, [user, token]);

  // Initialize auth state from localStorage
  useEffect(() => {
    const initializeAuth = () => {
      console.log("🔄 Starting auth initialization...");

      const savedToken = localStorage.getItem("token");
      const savedUser = localStorage.getItem("userData");

      if (savedToken && savedUser) {
        try {
          const parsedUser = JSON.parse(savedUser);

          // Validate token format
          const tokenParts = savedToken.split(".");
          if (tokenParts.length === 3) {
            setToken(savedToken);
            setUser(parsedUser);
            console.log(
              "✅ Auth state restored for user:",
              parsedUser.email,
              "with wallet:",
              parsedUser.wallet_address
            );
          } else {
            console.warn("⚠️ Invalid token format, clearing auth");
            localStorage.removeItem("token");
            localStorage.removeItem("userData");
          }
        } catch (e) {
          console.error("Failed to parse user data:", e);
          localStorage.removeItem("token");
          localStorage.removeItem("userData");
        }
      }

      setIsInitialized(true);
      console.log("✅ Auth initialization complete");
    };

    initializeAuth();
  }, []);

  // Email/password login
  const loginWithCredentials = async (email, password, otpCode= null) => {
    console.log("🔄 Starting login process for:", email);

    if (loginInProgress.current) {
      console.log("⚠️ Login already in progress, ignoring duplicate request");
      return;
    }

    loginInProgress.current = true;
    setLoading(true);

    try {
      const formData = new URLSearchParams();
      formData.append("username", email);
      formData.append("password", password);

      // ✅ NEW: Add OTP code if provided (for 2FA)
      if (otpCode) {
        formData.append("otp_code", otpCode);
      }

      const response = await fetch(
        `${import.meta.env.VITE_BASE_URL_BACKEND}/auth/login`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/x-www-form-urlencoded",
          },
          body: formData,
        }
      );

      // ✅ NEW: Handle 2FA required response
      if (response.status === 403) {
        const errorData = await response.json();
        if (errorData.detail === "2FA code required") {
          console.log("🔐 2FA code required for user:", email);
          loginInProgress.current = false;
          setLoading(false);
          return {
            success: false,
            require2FA: true,
            message: "Please enter your 2FA code"
          };
        }
      }

            // ✅ NEW: Handle invalid 2FA code
      if (response.status === 401) {
        const errorData = await response.json();
        if (errorData.detail === "Invalid 2FA code") {
          console.log("❌ Invalid 2FA code for user:", email);
          loginInProgress.current = false;
          setLoading(false);
          return {
            success: false,
            require2FA: true,
            message: "Invalid 2FA code. Please try again."
          };
        }
      }

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "Login failed");
      }

      const data = await response.json();

      if (data.access_token) {
        const tokenParts = data.access_token.split(".");
        if (tokenParts.length !== 3) {
          throw new Error("Invalid token format received from server");
        }

        localStorage.setItem("token", data.access_token);
        setToken(data.access_token);
      } else {
        throw new Error("No access token received from server");
      }

      const userObj = {
        id: data.user_id,
        email: email,
        role: data.role || "user",
        wallet_address: data.wallet_address || null,
        username: data.username,
        two_factor_enabled: data.two_factor_enabled || false, // ✅ NEW
      };

      localStorage.setItem("userData", JSON.stringify(userObj));
      setUser(userObj);
      setIs2FAEnabled(data.two_factor_enabled || false); // ✅ NEW

      toast.success("Login successful!");

      setTimeout(() => {
        loginInProgress.current = false;
      }, 1000);

      return { success: true, data }; // ✅ UPDATED: Return success object

    } catch (error) {
      console.error("❌ Login failed:", error);
      toast.error("Login failed: " + (error.message || "Unknown error"));
      loginInProgress.current = false;
      throw error;
    } finally {
      setLoading(false);
    }
  };

   // ✅ NEW: Alias for backward compatibility
  const login = loginWithCredentials;

  // Connect wallet
  const connectWallet = async (providedAccount = null) => {
    const currentToken = token || localStorage.getItem("token");

    if (!currentToken) {
      toast.error("Please log in first to connect your wallet");
      return { error: "Not authenticated" };
    }

    let walletAddress = providedAccount || account;

    if (!walletAddress && window.ethereum) {
      try {
        const accounts = await window.ethereum.request({
          method: "eth_accounts",
        });
        if (accounts.length > 0) {
          walletAddress = accounts[0];
        }
      } catch (error) {
        console.warn("Failed to get accounts from MetaMask:", error);
      }
    }

    if (!walletAddress) {
      toast.error("No wallet account available. Please connect MetaMask first.");
      return { error: "No wallet account available" };
    }

    setLoading(true);
    try {
      const response = await authAPI.connectWallet({
        wallet_address: walletAddress,
      });

      if (response.access_token) {
        localStorage.setItem("token", response.access_token);
        setToken(response.access_token);
      }

      if (response.user) {
        localStorage.setItem("userData", JSON.stringify(response.user));
        setUser(response.user);
      } else {
        const updatedUser = { ...user, wallet_address: walletAddress };
        localStorage.setItem("userData", JSON.stringify(updatedUser));
        setUser(updatedUser);
      }

      toast.success("Wallet connected successfully!");
      return response;
    } catch (error) {
      console.error("❌ Wallet connection failed:", error);
      toast.error("Failed to connect wallet: " + (error.message || "Connection failed"));
      return { error: error.message };
    } finally {
      setLoading(false);
    }
  };

  // Auto-link wallet
  useEffect(() => {
    const linkWalletToAccount = async () => {
      const isAuth = !!token;
      const walletConnected = connected && !!account;
      const accountStr = account && typeof account === 'object' ? account.address : account;
      const userWalletStr = user?.wallet_address;
      const isWalletLinked =
        userWalletStr && accountStr && 
        userWalletStr.toLowerCase() === accountStr.toLowerCase();
      const currentAttemptKey = `${isAuth}-${walletConnected}-${accountStr || ''}-${user?.wallet_address || ''}`;

      if (lastAutoLinkAttempt.current === currentAttemptKey) {
        return;
      }

      if (
        isAuth &&
        walletConnected &&
        account &&
        !isWalletLinked &&
        isInitialized &&
        !loginInProgress.current &&
        !loading
      ) {
        lastAutoLinkAttempt.current = currentAttemptKey;
        try {
          await connectWallet(account);
        } catch (error) {
          console.error("❌ Failed to auto-link wallet:", error);
        }
      }
    };

    if (isInitialized && !loginInProgress.current) {
      const timeoutId = setTimeout(linkWalletToAccount, 1000);
      return () => clearTimeout(timeoutId);
    }
  }, [token, connected, account, user?.wallet_address, isInitialized, loading]);

  // ============================================
  // GOOGLE OAUTH FUNCTIONS
  // ============================================

  const verifyGoogleToken = async (idToken) => {
    console.log("🔄 Verifying Google token...");
    setLoading(true);

    try {
      const response = await authAPI.verifyGoogleToken(idToken);

      if (!response.access_token) {
        throw new Error("No access token received");
      }

      localStorage.setItem("token", response.access_token);
      setToken(response.access_token);

      const userObj = {
        id: response.user_id,
        email: response.email,
        role: response.role || "user",
        wallet_address: response.wallet_address || null,
        oauth_provider: "google",
        profile_picture: response.profile_picture || null,
      };

      localStorage.setItem("userData", JSON.stringify(userObj));
      setUser(userObj);

      toast.success("Logged in with Google!");
      console.log("✅ Google token verified:", userObj.email);

      return response;
    } catch (error) {
      console.error("❌ Google token verification failed:", error);
      toast.error("Google login failed: " + (error.message || "Verification failed"));
      throw error;
    } finally {
      setLoading(false);
    }
  };

  const linkGoogleAccount = async (idToken) => {
    if (!token) {
      toast.error("Please log in first to link your Google account");
      return { error: "Not authenticated" };
    }

    setLoading(true);

    try {
      const response = await authAPI.linkGoogleAccount(idToken);

      if (response.profile_picture) {
        const updatedUser = {
          ...user,
          oauth_provider: "google",
          profile_picture: response.profile_picture,
        };
        localStorage.setItem("userData", JSON.stringify(updatedUser));
        setUser(updatedUser);
      }

      toast.success("Google account linked successfully!");
      return response;
    } catch (error) {
      console.error("❌ Google account linking failed:", error);
      toast.error("Failed to link Google account: " + (error.message || "Unknown error"));
      return { error: error.message };
    } finally {
      setLoading(false);
    }
  };

  const unlinkGoogleAccount = async () => {
    if (!token) {
      return;
    }

    setLoading(true);

    try {
      await authAPI.unlinkGoogleAccount();

      const updatedUser = {
        ...user,
        oauth_provider: null,
        profile_picture: null,
      };
      localStorage.setItem("userData", JSON.stringify(updatedUser));
      setUser(updatedUser);

      toast.success("Google account unlinked");
    } catch (error) {
      console.error("❌ Google account unlinking failed:", error);
      toast.error("Failed to unlink Google account");
    } finally {
      setLoading(false);
    }
  };

  // Signup
  const signup = async (userData) => {
    setLoading(true);
    try {
      const response = await authAPI.signup(userData);

      if (response.access_token) {
        localStorage.setItem("token", response.access_token);
        setToken(response.access_token);
      }

      if (response.user || response.email) {
        const userObj = response.user || {
          id: response._id,
          email: response.email,
          role: response.role || "user",
          wallet_address: null,
        };
        localStorage.setItem("userData", JSON.stringify(userObj));
        setUser(userObj);
      }

      toast.success("Account created successfully!");
      return response;
    } catch (error) {
      console.error("❌ Signup failed:", error);
      toast.error("Signup failed: " + (error.message || "Registration failed"));
      throw error;
    } finally {
      setLoading(false);
    }
  };

  // Logout
  const logout = (caller = "unknown") => {
    if (logoutInProgress.current || loginInProgress.current || loading) {
      return;
    }

    logoutInProgress.current = true;

    setUser(null);
    setToken(null);
    setIs2FAEnabled(false); // ✅ NEW: Reset 2FA status
    localStorage.removeItem("token");
    localStorage.removeItem("userData");
    lastAutoLinkAttempt.current = null;

    if (web3Disconnect) {
      web3Disconnect();
    }

    toast.success("Logged out successfully");

    setTimeout(() => {
      logoutInProgress.current = false;
    }, 1000);
  };

  // Get current user
  const getCurrentUser = async () => {
    if (!token) return null;

    try {
      const response = await authAPI.getCurrentUser();
      const userObj = {
        id: response.user_id,
        email: response.email,
        role: response.role,
        wallet_address: response.wallet_address,
      };
      setUser(userObj);
      localStorage.setItem("userData", JSON.stringify(userObj));
      return userObj;
    } catch (error) {
      console.error("Failed to get current user:", error);
      if (error.message.includes("401")) {
        logout("getCurrentUser-401");
      }
      return null;
    }
  };

  // Calculate wallet connection status
  const isWalletConnected =
    connected &&
    !!account &&
    !!user?.wallet_address &&
    (typeof account === 'string' ? user.wallet_address.toLowerCase() === account.toLowerCase() : user.wallet_address.toLowerCase() === account.address?.toLowerCase());

    // ✅ NEW: Refresh 2FA status
  const refresh2FAStatus = async () => {
    if (user && token) {
      try {
        const response = await authAPI.get2FAStatus();
        setIs2FAEnabled(response.enabled || false);
        
        // Update user data in localStorage
        const updatedUser = {
          ...user,
          two_factor_enabled: response.enabled || false
        };
        setUser(updatedUser);
        localStorage.setItem("userData", JSON.stringify(updatedUser));
      } catch (error) {
        console.error('Failed to refresh 2FA status:', error);
      }
    }
  };

  const refreshUser = async () => {
    try {
        const response = await authAPI.getCurrentUser();
        if (response) {
            const updatedUser = {
                id: response.user_id || response.id,
                email: response.email,
                role: response.role || "user",
                wallet_address: response.wallet_address || null,
                username: response.username,
                two_factor_enabled: response.two_factor_enabled || false,
                oauth_provider: response.oauth_provider || null,
                hashed_password: response.hashed_password || null, // ✅ Important!
            };
            
            localStorage.setItem('userData', JSON.stringify(updatedUser));
            setUser(updatedUser);
            
            console.log('✅ User data refreshed');
        }
    } catch (error) {
        console.error('Failed to refresh user data:', error);
    }
};


  const value = {
    user,
    token,
    loading,
    isInitialized,
    is2FAEnabled, // ✅ ADD THIS
    isAuthenticated: isInitialized && !!token,
    isWalletConnected,
    isFullyConnected: !!token && isWalletConnected,
    loginWithCredentials,
    connectWallet,
    logout,
    refresh2FAStatus, // ✅ NEW: Expose refresh function
    getCurrentUser,
    signup,
    verifyGoogleToken,
    linkGoogleAccount,
    unlinkGoogleAccount,
    googleAuthInProgress,
    refreshUser, // ✅ NEW: Add this
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export default AuthContext;