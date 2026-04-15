import React, { useState, useEffect, useRef, useMemo, useCallback, memo } from "react";
import { Link } from "react-router-dom";
import { useWeb3 } from "../context/Web3Context";
import { useAuth } from "../context/AuthContext";
import { ticketsAPI } from "../services/api";

// Removed backend dependency for recommendations
const recommendationAPI = {
  getRecommendations: async () => ({ results: [] }),
  searchArtworks: async () => { throw new Error("Semantic Search Disabled, Force Local."); },
  trackArtworkView: async () => ({})
};
import {
  Palette,
  FileText,
  Search,
  ArrowRight,
  ArrowLeft,
  ShoppingCart,
  Sparkles,
  History,
  TrendingUp,
  Wallet,
  CreditCard,
  Database,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import LoadingSpinner from "../components/common/LoadingSpinner";
import toast from "react-hot-toast";
import { CurrencyConverter, ArtworkStatus } from "../utils/currencyUtils"; // Moved this import up
import { useImageProtection } from "../hooks/useImageProtection";
import ProtectedImage from "../components/common/ProtectedImage";
import { cacheService } from "../services/cacheService";

// ✅ OPTIMIZATION: Skeleton loader for better perceived performance
const TicketSkeleton = () => (
  <div className="bg-white rounded-lg shadow-md overflow-hidden border border-gray-200 animate-pulse">
    <div className="bg-gradient-to-br from-gray-200 to-gray-300 h-48"></div>
    <div className="p-6">
      <div className="flex justify-between items-start mb-2">
        <div className="h-5 bg-gray-200 rounded w-2/3"></div>
        <div className="h-5 bg-gray-200 rounded-full w-20"></div>
      </div>
      <div className="space-y-2 mb-4">
        <div className="h-3 bg-gray-200 rounded w-full"></div>
        <div className="h-3 bg-gray-200 rounded w-4/5"></div>
      </div>
      <div className="flex justify-between items-center mb-4">
        <div className="h-10 bg-gray-200 rounded w-1/4"></div>
        <div className="h-10 bg-gray-200 rounded w-1/4"></div>
        <div className="h-10 bg-gray-200 rounded w-1/4"></div>
      </div>
      <div className="flex gap-2">
        <div className="h-10 bg-gray-200 rounded flex-1"></div>
        <div className="h-10 bg-gray-200 rounded w-16"></div>
        <div className="h-10 bg-gray-200 rounded w-20"></div>
      </div>
    </div>
  </div>
);

// ArtworkCard component definition - moved before Explorer component
// ✅ OPTIMIZED: Memoized to prevent unnecessary re-renders
const TicketCard = memo(({ ticket, currentAccount, isRecommended, currentUserId, selectedNetwork, isAuthenticated }) => {
  // ✅ Image error state for fallback
  const [imageError, setImageError] = useState(false);
  const isTicket = ticket?.is_psl_ticket === true;
  const pslMeta = ticket?.psl_metadata || {};

  const formatTimeTo12Hour = (rawTime) => {
    if (!rawTime || typeof rawTime !== "string") return "TBD";

    const value = rawTime.trim();
    if (!value) return "TBD";

    // If already in AM/PM style, normalize casing and return.
    if (/am|pm/i.test(value)) {
      return value.replace(/\s+/g, " ").toUpperCase();
    }

    // Handle HH:mm or HH:mm:ss formats.
    const timeMatch = value.match(/^(\d{1,2}):(\d{2})(?::\d{2})?$/);
    if (timeMatch) {
      const hour24 = Number(timeMatch[1]);
      const minute = timeMatch[2];

      if (Number.isNaN(hour24) || hour24 < 0 || hour24 > 23) {
        return value;
      }

      const suffix = hour24 >= 12 ? "PM" : "AM";
      const hour12 = hour24 % 12 || 12;
      return `${hour12}:${minute} ${suffix}`;
    }

    // Fallback: attempt Date parsing for datetime-like strings.
    const parsed = new Date(value);
    if (!Number.isNaN(parsed.getTime())) {
      return parsed.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", hour12: true });
    }

    return value;
  };

  const pslMatchSchedule = useMemo(() => {
    let dateValue = pslMeta.match_date || ticket?.match_date || "";
    let timeValue = pslMeta.match_time || ticket?.match_time || "";
    const dateTimeValue = pslMeta.match_datetime || ticket?.match_datetime || "";

    // Fallback: derive date/time from ISO datetime when explicit fields are missing.
    if ((!dateValue || !timeValue) && dateTimeValue) {
      const parsed = new Date(dateTimeValue);
      if (!Number.isNaN(parsed.getTime())) {
        if (!dateValue) {
          dateValue = parsed.toLocaleDateString();
        }
        if (!timeValue) {
          timeValue = parsed.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", hour12: true });
        }
      } else if (typeof dateTimeValue === "string" && dateTimeValue.includes("T")) {
        const [datePart, timePart] = dateTimeValue.split("T");
        if (!dateValue && datePart) {
          dateValue = datePart;
        }
        if (!timeValue && timePart) {
          timeValue = timePart.slice(0, 5);
        }
      }
    }

    return {
      date: dateValue || "TBD",
      time: formatTimeTo12Hour(timeValue),
    };
  }, [pslMeta.match_date, pslMeta.match_time, pslMeta.match_datetime, ticket?.match_date, ticket?.match_time, ticket?.match_datetime]);

  // Resale should only be shown when current owner is different from original creator.
  const isSecondaryOwnerTicket = useMemo(() => {
    if (typeof ticket?.is_secondary_owner === "boolean") {
      return ticket.is_secondary_owner;
    }

    const normalize = (v) => String(v || "").trim().toLowerCase();

    const creatorIdentifiers = [
      normalize(ticket?.creator_id),
      normalize(ticket?.creator_email),
      normalize(ticket?.creator_address),
    ].filter(Boolean);

    const ownerIdentifiers = [
      normalize(ticket?.owner_id),
      normalize(ticket?.owner_email),
      normalize(ticket?.owner_address),
    ].filter(Boolean);

    if (!creatorIdentifiers.length || !ownerIdentifiers.length) {
      return false;
    }

    return !ownerIdentifiers.some((id) => creatorIdentifiers.includes(id));
  }, [
    ticket?.is_secondary_owner,
    ticket?.creator_id,
    ticket?.creator_email,
    ticket?.creator_address,
    ticket?.owner_id,
    ticket?.owner_email,
    ticket?.owner_address,
  ]);

  const showPslResaleListing = isTicket && ticket?.is_for_sale && isSecondaryOwnerTicket;
  
  // ✅ OPTIMIZED: Memoized ownership check
  const isOwner = useMemo(() => {
    // If not authenticated, they cannot "own" the ticket in the context of the platform UI
    if (!isAuthenticated) return false;

    const isCryptoOwner = 
      currentAccount &&
      ticket.owner_address &&
      currentAccount.toLowerCase() === ticket.owner_address.toLowerCase();
    
    const isPayPalOwner = 
      currentUserId &&
      ticket.owner_id &&
      String(currentUserId).trim() === String(ticket.owner_id).trim();
    
    return isCryptoOwner || isPayPalOwner;
  }, [currentAccount, ticket.owner_address, currentUserId, ticket.owner_id, isAuthenticated]);

  // ✅ OPTIMIZED: Memoized image URL
  const imageUrl = useMemo(() => {
    const artworkId = ticket._id || ticket.id || ticket.token_id;
    if (artworkId) {
      const baseUrl = import.meta.env.VITE_BASE_URL_BACKEND || '';
      const cleanBaseUrl = baseUrl.endsWith('/') ? baseUrl.slice(0, -1) : baseUrl;
      return `${cleanBaseUrl}/tickets/${artworkId}/image`;
    }
    return null;
  }, [ticket._id, ticket.id, ticket.token_id]);

  // ✅ OPTIMIZED: Memoized price formatting
  const priceDisplay = useMemo(() => {
    if (!ticket.price) return null;
    
    const ethPrice = ticket.price;
    const usdPrice = CurrencyConverter.ethToUsd(ethPrice);
    
    return (
      <div className="text-center">
        <p className="text-xs text-gray-500">Price</p>
        <p className="text-sm font-semibold text-gray-900">
          {CurrencyConverter.formatCrypto(ethPrice, ticket.network)}
        </p>
        <p className="text-xs text-gray-400">
          ≈ {CurrencyConverter.formatUsd(usdPrice)}
        </p>
      </div>
    );
  }, [ticket.price]);

  // ✅ OPTIMIZED: Memoized registration badge
  const registrationBadge = useMemo(() => {
    const registrationMethod = ArtworkStatus.getRegistrationMethod(ticket);
    
    if (registrationMethod === "on-chain") {
      return (
        <span className="absolute top-2 right-2 bg-blue-500 text-white text-xs px-2 py-1 rounded flex items-center gap-1 z-20 whitespace-nowrap">
          <Wallet className="w-3 h-3" />
          On-chain
        </span>
      );
    } else {
      return (
        <span className="absolute top-2 right-2 bg-green-500 text-white text-xs px-2 py-1 rounded flex items-center gap-1 z-20 whitespace-nowrap">
          <CreditCard className="w-3 h-3" />
          Off-chain
        </span>
      );
    }
  }, [ticket]);

  return (
    <div className="bg-white rounded-lg shadow-md overflow-hidden border border-gray-200 hover:shadow-xl transition-all relative">
      {/* Recommended Badge - positioned on left to avoid overlap */}
      {isRecommended && (
        <div className="absolute top-2 left-2 z-30">
          <div className="bg-gradient-to-r from-green-600 to-green-700 text-white px-3 py-1.5 rounded-full text-xs font-bold flex items-center shadow-lg border-2 border-white">
            <Sparkles className="w-3.5 h-3.5 mr-1.5 animate-pulse" />
            FOR YOU
          </div>
        </div>
      )}
      
      <div 
        className="bg-gray-100 h-48 flex items-center justify-center relative overflow-hidden image-container"
        style={{
          userSelect: 'none',
          WebkitUserSelect: 'none',
          MozUserSelect: 'none',
          msUserSelect: 'none',
          WebkitTouchCallout: 'none'
        }}
      >
        {imageUrl ? (
          <>
            {/* Registration Badge - top right */}
            {registrationBadge}
            {/* DB Badge - below registration badge */}
            <div className="absolute top-10 right-2 z-20">
              <div className="bg-blue-500 text-white text-xs px-2 py-1 rounded-full flex items-center shadow-md">
                <Database className="w-3 h-3 mr-1" />
                DB
              </div>
            </div>
            
            {/* Protected Canvas Image */}
            <ProtectedImage
              imageUrl={imageUrl}
              alt={ticket.title || `Ticket ${ticket.token_id}`}
              className="w-full h-full"
              aspectRatio="auto"
              showToast={false}
              onError={() => {
                setImageError(true);
              }}
            />
            
            {/* Error placeholder */}
            {imageError && (
              <div className="absolute inset-0 flex flex-col items-center justify-center bg-gray-100">
                <Palette className="w-12 h-12 text-gray-400 mx-auto mb-2" />
                <p className="text-sm text-gray-500">Image unavailable</p>
              </div>
            )}
          </>
        ) : (
          <div className="text-center">
            <Palette className="w-16 h-16 text-gray-400 mx-auto mb-2" />
            <p className="text-sm text-gray-500">Ticket #{ticket.token_id}</p>
            <p className="text-xs text-gray-400">{ticket.title}</p>
          </div>
        )}
      </div>
      <div className="p-6">
        <div className="flex justify-between items-start mb-2">
          <h3 className="text-lg font-semibold text-gray-900">
            {ticket.title || `Ticket #${ticket.token_id}`}
          </h3>
          <span className={`px-2 py-1 text-xs rounded-full ${
            showPslResaleListing
              ? "bg-emerald-100 text-emerald-700 border border-emerald-200"
              : "bg-gray-100 text-gray-800"
          }`}>
            {showPslResaleListing ? "PSL Resale" : "Available"}
          </span>
        </div>
        <p className="text-sm text-gray-500 mb-4 line-clamp-2">
          {ticket.description || "No description available"}
        </p>

        {ticket.is_psl_ticket && (
          <div className="mb-4 min-h-[32px]">
            {showPslResaleListing ? (
              <div className="inline-flex items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700">
                <ShoppingCart className="w-3.5 h-3.5" />
                Resale listing from owner
              </div>
            ) : (
              <div className="invisible inline-flex items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-semibold">
                <ShoppingCart className="w-3.5 h-3.5" />
                Resale listing from owner
              </div>
            )}
          </div>
        )}
        
        {/* PSL Ticket Details */}
        {ticket.is_psl_ticket && ticket.psl_metadata && (
          <div className="mb-4 p-3 bg-green-50 rounded-lg border border-green-100">
            <div className="flex items-center gap-2 mb-2 text-green-700 font-semibold text-sm">
              <Sparkles className="w-4 h-4" />
              <span>PSL Smart-Ticket</span>
            </div>
            <div className="grid grid-cols-2 gap-y-2 text-xs">
              <div className="text-gray-500">Venue:</div>
              <div className="font-medium text-gray-900">{pslMeta.venue || "TBD"}</div>
              <div className="text-gray-500">Date:</div>
              <div className="font-medium text-gray-900">{pslMatchSchedule.date}</div>
              <div className="text-gray-500">Time:</div>
              <div className="font-medium text-gray-900">{pslMatchSchedule.time}</div>
              <div className="text-gray-500">Stand:</div>
              <div className="font-medium text-gray-900">{pslMeta.stand || "TBD"}</div>
              <div className="text-gray-500">Seat:</div>
              <div className="font-medium text-gray-900">{pslMeta.seat_number || pslMeta.seat || "TBD"}</div>
            </div>
          </div>
        )}
        
        {/* Creator, Price, and Royalty in one line */}
        <div className="flex justify-between items-center mb-4">
          <div className="text-center flex-1">
            <p className="text-xs text-gray-500">Creator</p>
            <p className="text-sm font-mono">
              {ticket.creator_address 
                ? `${ticket.creator_address.substring(0, 6)}...${ticket.creator_address.substring(38)}`
                : ticket.creator_id || "N/A"}
            </p>
          </div>
          
          {/* Price in the middle */}
          {ticket.price && (
            <div className="text-center flex-1 mx-6">
              {priceDisplay}
            </div>
          )}
          
          {!isTicket && (
            <div className="text-center flex-1">
              <p className="text-xs text-gray-500">Royalty</p>
              <p className="text-sm font-semibold">
                {ticket.royalty_percentage
                  ? `${(ticket.royalty_percentage / 100).toFixed(2)}%`
                  : "N/A"}
              </p>
            </div>
          )}
        </div>

        {/* Action Buttons */}
        <div className="flex gap-2">
          <Link
            to={`/ticket/${ticket._id || ticket.id || ticket.token_id}`}
            className="flex-1 inline-flex items-center justify-center text-sm font-medium text-green-600 hover:text-green-800 border border-green-200 rounded-lg px-3 py-2 hover:bg-green-50 transition-colors"
          >
            View details <ArrowRight className="w-4 h-4 ml-1" />
          </Link>

          {isOwner ? (
            <div className="inline-flex items-center justify-center px-3 py-2 text-sm font-medium text-blue-700 bg-blue-100 border border-blue-300 rounded-lg">
              {isTicket ? "This is your ticket" : "This is your ticket"}
            </div>
          ) : (
            <>
              <Link
                to={`/sale/${ticket._id || ticket.id || ticket.token_id}`}
                className={`inline-flex items-center justify-center px-3 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors ${isTicket ? "flex-1" : ""}`}
                title="Purchase this ticket"
              >
                <ShoppingCart className="w-4 h-4 mr-1" />
                Buy
              </Link>

            </>
          )}
        </div>
      </div>
    </div>
  );
}, (prevProps, nextProps) => {
  // ✅ Custom comparison function for better memoization
  return (
    prevProps.ticket._id === nextProps.ticket._id &&
    prevProps.ticket.is_for_sale === nextProps.ticket.is_for_sale &&
    prevProps.ticket.is_secondary_owner === nextProps.ticket.is_secondary_owner &&
    prevProps.ticket.owner_id === nextProps.ticket.owner_id &&
    prevProps.ticket.owner_address === nextProps.ticket.owner_address &&
    prevProps.ticket.creator_id === nextProps.ticket.creator_id &&
    prevProps.ticket.creator_address === nextProps.ticket.creator_address &&
    prevProps.currentAccount === nextProps.currentAccount &&
    prevProps.currentUserId === nextProps.currentUserId &&
    prevProps.isRecommended === nextProps.isRecommended
  );
});

TicketCard.displayName = 'TicketCard';

const normalizeNetworkKey = (network) => {
  const net = String(network || "").toLowerCase().trim();

  if (!net) return "wirefluid";
  if (["wirefluid", "wire", "wire-fluid"].includes(net)) return "wirefluid";

  return "wirefluid";
};

const shouldShowArtworkForSelectedNetwork = (ticket, selectedNetworkKey) => {
  if (!ticket) return false;

  // Off-chain tickets should always be visible regardless of selected network.
  if (!ArtworkStatus.isOnChainArtwork(ticket)) {
    return true;
  }

  if (!selectedNetworkKey) {
    return true;
  }

  // Legacy on-chain records without explicit network are treated as WireFluid.
  const artworkNetwork = normalizeNetworkKey(
    ticket.network || ticket.blockchain_network || ticket.chain || "wirefluid"
  );

  return artworkNetwork === selectedNetworkKey;
};

// Main Explorer component
const Explorer = () => {
  // ✅ OPTIMIZATION: Feature flags for easy enable/disable
  const ENABLE_PROGRESSIVE_LOADING = true; // Fast first page load
  const ENABLE_CACHING = true; // LocalStorage caching
  const ENABLE_SKELETON_UI = true; // Skeleton loaders
  const CACHE_DURATION = 5 * 60 * 1000; // 5 minutes cache
  const CACHE_KEY_PREFIX = 'explorer_cache_'; // ✅ MATCHES cacheService.js prefix
  
  const { account, isCorrectNetwork, selectedNetwork } = useWeb3();
  const { isAuthenticated, user } = useAuth();

  // ✅ Add image protection hook
  useImageProtection(true);
  const [isLoading, setIsLoading] = useState(true);
  const [isSearching, setIsSearching] = useState(false);
  const [refreshTrigger, setRefreshTrigger] = useState(0); // ✅ NEW: Force re-fetch on cache invalidation
  
  // ✅ NEW: Listen for global cache invalidation
  useEffect(() => {
    const handleInvalidation = () => {
      console.log('🔔 Explorer notified of cache invalidation - Triggering re-fetch');
      setRefreshTrigger(prev => prev + 1); // Increment to trigger re-fetch
    };
    
    window.addEventListener('ticket-cache-invalidated', handleInvalidation);
    return () => window.removeEventListener('ticket-cache-invalidated', handleInvalidation);
  }, []);
  
  // All tickets data
  const [allArtworks, setAllArtworks] = useState([]); // ✅ Store ALL tickets for proper reordering
  const [recommendedArtworks, setRecommendedArtworks] = useState([]);
  
  // Display data (reordered: recommended first + remaining tickets)
  const [displayedArtworks, setDisplayedArtworks] = useState([]);
  
  const [searchTerm, setSearchTerm] = useState("");
  const [filters, setFilters] = useState({
    royalty: "all",
  });
  const [viewMode, setViewMode] = useState("unified"); // "unified" or "search"
  const [hasRecommendations, setHasRecommendations] = useState(false);
  const [retryCount, setRetryCount] = useState(0);
  const [recommendationAttempts, setRecommendationAttempts] = useState(0);
  
  // ✅ Registration method filter state (on-chain/off-chain)
  const [activeRegistrationFilter, setActiveRegistrationFilter] = useState("psl"); // locked to "psl"
  const [artworkCounts, setArtworkCounts] = useState({ total: 0, crypto: 0, paypal: 0, psl: 0 });
  const [networkScopedTabCounts, setNetworkScopedTabCounts] = useState({
    all: null,
    onChain: null,
    offChain: null,
    psl: null,
  });
  
  // 🎫 PSL Smart-Ticket filter (Hackathon Demo)
  const [showPSLOnly, setShowPSLOnly] = useState(false);
  const [pslTicketCount, setPslTicketCount] = useState(0);

  const selectedNetworkKey = useMemo(
    () => normalizeNetworkKey(selectedNetwork || "wirefluid"),
    [selectedNetwork]
  );
  
  // ✅ OPTIMIZED: Pagination state for progressive loading
  const [currentPage, setCurrentPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [totalPages, setTotalPages] = useState(1);
  const itemsPerPage = 10;
  const currentPageRef = useRef(1);
  const allArtworksRef = useRef([]);
  const recommendedArtworksRef = useRef([]);
  
  // ✅ Ref to track if initial load has completed (prevent filter useEffect from running on mount)
  const isInitialMount = useRef(true);
  
  // ✅ FIXED: Helper function to update page and keep ref in sync
  const updatePage = useCallback((newPage) => {
    setCurrentPage(newPage);
    currentPageRef.current = newPage;
  }, []);

  const setAllArtworksWithRef = (tickets) => {
    allArtworksRef.current = tickets;
    setAllArtworks(tickets);
  };
  
  const setRecommendedArtworksWithRef = (tickets) => {
    recommendedArtworksRef.current = tickets;
    setRecommendedArtworks(tickets);
  };
  
  // ✅ OPTIMIZATION: Caching helper functions
  const getCacheKey = useCallback((filter) => {
    return `${CACHE_KEY_PREFIX}${filter}_${selectedNetworkKey || 'wirefluid'}_${user?.id || 'guest'}`;
  }, [CACHE_KEY_PREFIX, selectedNetworkKey, user?.id]);
  
  const getCachedData = useCallback((filter) => {
    if (!ENABLE_CACHING) return null;
    
    try {
      const cacheKey = getCacheKey(filter);
      const cached = localStorage.getItem(cacheKey);
      if (!cached) return null;
      
      const { data, timestamp } = JSON.parse(cached);
      const age = Date.now() - timestamp;
      
      if (age < CACHE_DURATION) {
        console.log(`✅ Cache hit: ${cacheKey} (${Math.round(age / 1000)}s old)`);
        return data;
      } else {
        console.log(`🗑️ Cache expired: ${cacheKey}`);
        localStorage.removeItem(cacheKey);
        return null;
      }
    } catch (error) {
      console.error('❌ Cache read error:', error);
      return null;
    }
  }, [ENABLE_CACHING, getCacheKey, CACHE_DURATION]);
  
  const setCachedData = useCallback((filter, data) => {
    if (!ENABLE_CACHING || !data || data.length === 0) return;
    
    try {
      const cacheKey = getCacheKey(filter);
      const cacheData = {
        data,
        timestamp: Date.now(),
        version: '1.0'
      };
      localStorage.setItem(cacheKey, JSON.stringify(cacheData));
      console.log(`💾 Cached ${data.length} tickets: ${cacheKey}`);
    } catch (error) {
      console.error('❌ Cache write error:', error);
      // Clear old cache if quota exceeded
      if (error.name === 'QuotaExceededError') {
        console.log('🗑️ Clearing old cache due to quota...');
        Object.keys(localStorage)
          .filter(key => key.startsWith(CACHE_KEY_PREFIX))
          .forEach(key => localStorage.removeItem(key));
      }
    }
  }, [ENABLE_CACHING, getCacheKey, CACHE_KEY_PREFIX]);
  
  const clearCache = useCallback(() => {
    try {
      Object.keys(localStorage)
        .filter(key => key.startsWith(CACHE_KEY_PREFIX))
        .forEach(key => localStorage.removeItem(key));
      console.log('🗑️ Cache cleared');
    } catch (error) {
      console.error('❌ Cache clear error:', error);
    }
  }, [CACHE_KEY_PREFIX]);
  
  // ✅ OPTIMIZATION: Request deduplication - track in-flight requests
  const inFlightRequests = useRef(new Map());
  const abortControllers = useRef(new Map());
  
  // ✅ OPTIMIZATION: Create AbortController for request cancellation
  const createAbortController = (key) => {
    // Cancel previous request with same key
    const prevController = abortControllers.current.get(key);
    if (prevController) {
      prevController.abort();
    }
    
    const controller = new AbortController();
    abortControllers.current.set(key, controller);
    return controller;
  };
  
  // ✅ OPTIMIZED: Memoized user ID to prevent unnecessary recalculations
  const effectiveUserId = useMemo(() => {
    // Priority 1: Direct user ID from auth context
    if (user?.id) {
      return user.id;
    }
    
    // Priority 2: Check for user ID in different properties
    if (user?._id) {
      return user._id;
    }
    
    // Priority 3: Extract from JWT token if available
    const token = localStorage.getItem('token') || sessionStorage.getItem('token');
    if (token) {
      try {
        const payload = JSON.parse(atob(token.split('.')[1]));
        const userIdFromToken = payload.userId || payload.user_id || payload.sub || payload.id;
        if (userIdFromToken) {
          return userIdFromToken;
        }
      } catch (error) {
        console.error('Error decoding token:', error);
      }
    }
    
    // Priority 4: Use wallet address as fallback (if your backend supports it)
    if (account) {
      return account.toLowerCase();
    }
    
    return null;
  }, [user?.id, user?._id, account]);
  
  // ✅ OPTIMIZED: Memoized recommended ticket IDs Set for O(1) lookup
  const recommendedIdsSet = useMemo(() => {
    const ids = new Set();
    recommendedArtworks.forEach(art => {
      const id = art._id || art.id;
      if (id) ids.add(id.toString());
    });
    return ids;
  }, [recommendedArtworks]);

  // ✅ Keep counters accurate for the currently active registration filter
  const activeFilterTotalCount = useMemo(() => {
    const totalFromState = Array.isArray(allArtworks) ? allArtworks.length : 0;
    const onChainFromCounts = Number(artworkCounts.on_chain || artworkCounts.crypto || 0);
    const offChainFromCounts = Number(artworkCounts.off_chain || artworkCounts.paypal || 0);
    const allFromScoped = networkScopedTabCounts.all;
    const normalizedTotalFromCounts = Math.max(
      Number(artworkCounts.total || 0),
      onChainFromCounts + offChainFromCounts
    );

    if (activeRegistrationFilter === "psl") {
      return totalFromState || pslTicketCount || artworkCounts.psl || 0;
    }

    if (activeRegistrationFilter === "on-chain") {
      return totalFromState || artworkCounts.on_chain || artworkCounts.crypto || 0;
    }

    if (activeRegistrationFilter === "off-chain") {
      return totalFromState || artworkCounts.off_chain || artworkCounts.paypal || 0;
    }

    if (allFromScoped != null) {
      return allFromScoped;
    }

    return totalFromState || normalizedTotalFromCounts || 0;
  }, [
    activeRegistrationFilter,
    allArtworks.length,
    networkScopedTabCounts.all,
    pslTicketCount,
    artworkCounts.psl,
    artworkCounts.on_chain,
    artworkCounts.crypto,
    artworkCounts.off_chain,
    artworkCounts.paypal,
    artworkCounts.total,
  ]);

  const tabCounts = useMemo(() => {
    const fallbackOnChain = Number(artworkCounts.on_chain || artworkCounts.crypto || 0);
    const fallbackOffChain = Number(artworkCounts.off_chain || artworkCounts.paypal || 0);
    const fallbackPsl = Number(pslTicketCount || artworkCounts.psl || 0);

    const baseOnChain = networkScopedTabCounts.onChain ?? fallbackOnChain;
    const baseOffChain = networkScopedTabCounts.offChain ?? fallbackOffChain;
    const basePsl = networkScopedTabCounts.psl ?? fallbackPsl;
    const baseTotal = networkScopedTabCounts.all ?? (baseOnChain + baseOffChain);

    const onChain = activeRegistrationFilter === "on-chain" ? activeFilterTotalCount : baseOnChain;
    const offChain = activeRegistrationFilter === "off-chain" ? activeFilterTotalCount : baseOffChain;
    const psl = activeRegistrationFilter === "psl" ? activeFilterTotalCount : basePsl;
    const total = activeRegistrationFilter === "all"
      ? activeFilterTotalCount
      : (networkScopedTabCounts.all ?? (onChain + offChain));

    return {
      all: total,
      onChain,
      offChain,
      psl,
    };
  }, [
    networkScopedTabCounts.all,
    networkScopedTabCounts.onChain,
    networkScopedTabCounts.offChain,
    networkScopedTabCounts.psl,
    artworkCounts.on_chain,
    artworkCounts.crypto,
    artworkCounts.off_chain,
    artworkCounts.paypal,
    artworkCounts.psl,
    artworkCounts.total,
    pslTicketCount,
    activeRegistrationFilter,
    activeFilterTotalCount,
  ]);

  const activeItemLabelPlural = useMemo(
    () => (activeRegistrationFilter === "psl" ? "tickets" : "tickets"),
    [activeRegistrationFilter]
  );

  const activeFilterLabel = useMemo(() => {
    if (activeRegistrationFilter === "all") return `all ${activeItemLabelPlural}`;
    if (activeRegistrationFilter === "on-chain") return "on-chain";
    if (activeRegistrationFilter === "off-chain") return "off-chain";
    if (activeRegistrationFilter === "psl") return "PSL tickets";
    return activeRegistrationFilter;
  }, [activeRegistrationFilter, activeItemLabelPlural]);

  // Fetch all tickets
  // ✅ Fetch ticket counts - FIXED: Wrapped in useCallback
  const fetchArtworkCounts = useCallback(async () => {
    try {
      console.log("🔄 Fetching ticket counts...");
      const counts = await ticketsAPI.getCounts();
      console.log("✅ Ticket counts received:", counts);
      setArtworkCounts(counts);
      
      // ✅ Set PSL count for UI
      if (counts.psl !== undefined) {
        setPslTicketCount(counts.psl);
      }
      
      return counts;
    } catch (error) {
      console.error("❌ Error fetching ticket counts:", error);
      toast.error("Failed to load ticket counts");
      return { total: 0, on_chain: 0, off_chain: 0, crypto: 0, paypal: 0 };
    }
  }, []);

  // ✅ SIMPLE: Fetch ALL tickets
  const fetchAllArtworksComplete = useCallback(async () => {
    try {
      const counts = await fetchArtworkCounts();
      const total = counts.total || 0;
      if (total === 0) return [];
      
      // Fetch all pages
      const pageSize = 100;
      const totalPages = Math.ceil(total / pageSize);
      const fetchPromises = [];
      
      for (let page = 1; page <= totalPages; page++) {
        const params = { page, size: pageSize };
        if (activeRegistrationFilter === "on-chain") params.is_on_chain = true;
        else if (activeRegistrationFilter === "off-chain") params.is_on_chain = false;
        else if (activeRegistrationFilter === "psl") params.is_psl_ticket = true;
        fetchPromises.push(ticketsAPI.getAll(params));
      }
      
      const responses = await Promise.all(fetchPromises);
      let allArtworks = [];
      
      responses.forEach(response => {
        const tickets = response?.data || response?.tickets || response?.results || (Array.isArray(response) ? response : []);
        allArtworks = [...allArtworks, ...tickets];
      });
      
      // Filter for sale and remove duplicates
      const seenIds = new Set();
      const filteredArtworks = allArtworks.filter(art => {
        if (!art || art.is_for_sale === false) return false;
        if (!shouldShowArtworkForSelectedNetwork(art, selectedNetworkKey)) return false;
        const id = (art._id || art.id)?.toString();
        if (!id || seenIds.has(id)) return false;
        seenIds.add(id);
        return true;
      });

      // Keep tab badges network-scoped and coherent for the selected network.
      setNetworkScopedTabCounts(prev => {
        const next = { ...prev };

        if (activeRegistrationFilter === "all") {
          next.all = filteredArtworks.length;
          next.onChain = filteredArtworks.filter(art => ArtworkStatus.isOnChainArtwork(art)).length;
          next.offChain = filteredArtworks.filter(art => ArtworkStatus.isOffChainArtwork(art)).length;
          next.psl = filteredArtworks.filter(art => art?.is_psl_ticket === true).length;
        } else if (activeRegistrationFilter === "on-chain") {
          next.onChain = filteredArtworks.length;
        } else if (activeRegistrationFilter === "off-chain") {
          next.offChain = filteredArtworks.length;
        } else if (activeRegistrationFilter === "psl") {
          next.psl = filteredArtworks.length;
        }

        if (next.all == null && next.onChain != null && next.offChain != null) {
          next.all = next.onChain + next.offChain;
        }

        return next;
      });

      return filteredArtworks;
    } catch (error) {
      console.error("❌ Error fetching all tickets:", error);
      return [];
    }
  }, [activeRegistrationFilter, fetchArtworkCounts, selectedNetworkKey]);

  // ✅ OPTIMIZED: useCallback to prevent function recreation with request deduplication
  const fetchAllArtworks = useCallback(async (page = 1, append = false) => {
    // ✅ OPTIMIZATION: Request deduplication - prevent duplicate requests
    const requestKey = `tickets-${page}-${activeRegistrationFilter}-${selectedNetworkKey || 'wirefluid'}`;
    
    // Check if request is already in flight
    if (inFlightRequests.current.has(requestKey)) {
      console.log(`⏭️ Skipping duplicate request: ${requestKey}`);
      return inFlightRequests.current.get(requestKey);
    }
    
    // Create abort controller for this request
    const abortController = createAbortController(requestKey);
    
    try {
      // ✅ OPTIMIZED: Reduced initial page size for faster loading
      const params = { page, size: 10 }; // Reduced to 10 for faster initial load
      if (activeRegistrationFilter === "on-chain") {
        params.is_on_chain = true;
      } else if (activeRegistrationFilter === "off-chain") {
        params.is_on_chain = false;
      } else if (activeRegistrationFilter === "psl") {
        params.is_psl_ticket = true;
      }
      
      // Create request promise
      const requestPromise = ticketsAPI.getAll(params);
      inFlightRequests.current.set(requestKey, requestPromise);
      
      const response = await requestPromise;
      
      // Remove from in-flight after completion
      inFlightRequests.current.delete(requestKey);
      
      // ✅ Handle multiple response formats - simplified
      let tickets = [];
      if (Array.isArray(response)) {
        tickets = response;
      } else if (response?.data) {
        tickets = Array.isArray(response.data) ? response.data : [];
      } else if (response?.tickets) {
        tickets = Array.isArray(response.tickets) ? response.tickets : [];
      } else if (response?.results) {
        tickets = Array.isArray(response.results) ? response.results : [];
      }
      
      // ✅ Update pagination state
      if (response?.has_next !== undefined) {
        setHasMore(response.has_next);
      } else {
        setHasMore(tickets.length === params.size);
      }
      
      // ✅ Calculate total pages based on total count
      if (response?.total !== undefined) {
        const calculatedPages = Math.ceil(response.total / itemsPerPage);
        setTotalPages(calculatedPages);
      } else if (response?.count !== undefined) {
        const calculatedPages = Math.ceil(response.count / itemsPerPage);
        setTotalPages(calculatedPages);
      } else if (artworkCounts.total > 0) {
        const calculatedPages = Math.ceil(artworkCounts.total / itemsPerPage);
        setTotalPages(calculatedPages);
      }
      
      // ✅ Filter out tickets that are not for sale (is_for_sale = false)
      // Backend should already filter, but add frontend filter as safety check
      const artworksForSale = tickets.filter(ticket => {
        return ticket && ticket.is_for_sale !== false && shouldShowArtworkForSelectedNetwork(ticket, selectedNetworkKey);
      });
      
      if (append) {
        setAllArtworks(prev => {
          // ✅ Prevent duplicates when appending
          const existingIds = new Set(prev.map(a => (a._id || a.id)?.toString()));
          const newArtworks = artworksForSale.filter(a => {
            const id = (a._id || a.id)?.toString();
            return id && !existingIds.has(id);
          });
          const updated = [...prev, ...newArtworks];
          allArtworksRef.current = updated;
          return updated;
        });
      } else {
        setAllArtworksWithRef(artworksForSale);
      }
      
      return artworksForSale;
    } catch (error) {
      // Remove from in-flight on error
      inFlightRequests.current.delete(requestKey);
      
      // Don't show error if request was aborted (cancelled)
      if (error.name === 'AbortError' || abortController.signal.aborted) {
        console.log(`🚫 Request cancelled: ${requestKey}`);
        return [];
      }
      
      // Only show error toast if it's not a network error or if it's a real API error
      if (error.response?.status !== 401) {
        toast.error("Failed to load tickets. Please try refreshing the page.");
      }
      
      // Return empty array to prevent crashes
      if (!append) {
        setAllArtworks([]);
      }
      setHasMore(false);
      return [];
    }
  }, [activeRegistrationFilter, selectedNetworkKey]);

  // ✅ OPTIMIZED: useCallback for recommendations
  const fetchRecommendations = useCallback(async (userId = null) => {
    const targetUserId = userId || effectiveUserId;
    
    if (!targetUserId) {
      console.log('⚠️ No user ID available - skipping recommendations');
      setRecommendedArtworksWithRef([]);
      setHasRecommendations(false);
      return [];
    }

    // ✅ FIXED: Prevent duplicate recommendation requests
    const requestKey = `recommendations-${targetUserId}-${activeRegistrationFilter}-${selectedNetworkKey || 'wirefluid'}`;
    
    // Check if request is already in flight
    if (inFlightRequests.current.has(requestKey)) {
      console.log(`⏭️ Skipping duplicate recommendation request: ${requestKey}`);
      return inFlightRequests.current.get(requestKey);
    }
    
    console.log(`🎯 Fetching recommendations for user: ${targetUserId} (registration filter: ${activeRegistrationFilter})`);
    
    // Create and track the request promise
    const requestPromise = (async () => {
    try {
      // ✅ Convert registration_method filter to backend API parameter
      // Note: Backend API still uses "payment_method" parameter name for backward compatibility,
      // but it actually filters by registration_method (on-chain/off-chain)
      let registrationFilterParam = null;
      if (activeRegistrationFilter === "on-chain") {
        registrationFilterParam = "crypto"; // Maps to on-chain tickets
      } else if (activeRegistrationFilter === "off-chain") {
        registrationFilterParam = "paypal"; // Maps to off-chain tickets
      }
      
      const response = await recommendationAPI.getRecommendations(targetUserId, 10, registrationFilterParam);
      console.log('📦 Recommendations response:', response);
      
      // Handle different response formats
      let allRecommended = [];
      
      if (response?.recommendations) {
        // New format with categorized recommendations
        allRecommended = [
          ...(response.recommendations.recommended_for_you || []),
          ...(response.recommendations.search_based || []),
          ...(response.recommendations.purchase_based || []),
          ...(response.recommendations.upload_based || []),
          ...(response.recommendations.view_based || [])
        ];
      } else if (response?.results) {
        // Legacy format
        allRecommended = Array.isArray(response.results) ? response.results : [];
      } else if (Array.isArray(response)) {
        // Direct array response
        allRecommended = response;
      }
      
      console.log(`📊 Combined recommendations: ${allRecommended.length} tickets`);
      
      // ✅ STEP 1: Remove duplicates FIRST (before filtering by is_for_sale)
      // This prevents the same ticket from being counted multiple times
      const seenIds = new Set();
      const deduplicatedRecommended = [];
      const duplicates = [];
      
      allRecommended.forEach((ticket, index) => {
        if (!ticket) {
          console.warn(`⚠️ Recommendation ${index} is null/undefined`);
          return;
        }
        
        // Must have an ID to deduplicate
        const artId = (ticket._id || ticket.id || ticket.token_id)?.toString();
        if (!artId) {
          console.warn(`⚠️ Recommendation ${index} missing ID:`, {
            ticket,
            title: ticket.title,
            _id: ticket._id,
            id: ticket.id,
            token_id: ticket.token_id
          });
          return;
        }
        
        if (seenIds.has(artId)) {
          duplicates.push({
            index,
            id: artId,
            title: ticket.title
          });
          console.log(`🔄 Duplicate recommendation found (removed):`, {
            id: artId,
            title: ticket.title,
            index
          });
        } else {
          seenIds.add(artId);
          deduplicatedRecommended.push(ticket);
        }
      });
      
      if (duplicates.length > 0) {
        console.log(`🔄 Removed ${duplicates.length} duplicate recommendations:`, duplicates);
      }
      console.log(`✅ After deduplication: ${deduplicatedRecommended.length} unique tickets`);
      
      // ✅ STEP 2: Filter out invalid tickets and ensure they're for sale
      const validRecommended = deduplicatedRecommended.filter((ticket, index) => {
        // Must be for sale
        if (ticket.is_for_sale === false) {
          console.warn(`🚫 Filtered out recommendation not for sale:`, {
            id: ticket._id || ticket.id || ticket.token_id,
            title: ticket.title,
            is_for_sale: ticket.is_for_sale
          });
          return false;
        }

        if (!shouldShowArtworkForSelectedNetwork(ticket, selectedNetworkKey)) {
          console.warn(`🚫 Filtered out on-chain recommendation for different network:`, {
            id: ticket._id || ticket.id || ticket.token_id,
            title: ticket.title,
            artwork_network: ticket.network,
            selected_network: selectedNetworkKey,
          });
          return false;
        }

        return true;
      });
      
      console.log(`✅ After validation (is_for_sale check): ${validRecommended.length} valid recommendations`);
      
      console.log(`✅ Final unique valid recommendations: ${validRecommended.length} tickets`);
      if (validRecommended.length > 0) {
        console.log('🆔 Recommended ticket IDs:', validRecommended.map(a => ({
          _id: a._id,
          id: a.id,
          token_id: a.token_id,
          title: a.title,
          is_for_sale: a.is_for_sale
        })));
      }
      
      // Log the difference
      if (allRecommended.length !== validRecommended.length) {
        const filteredCount = allRecommended.length - validRecommended.length;
        console.log(`📊 Recommendation filtering summary: ${allRecommended.length} total → ${deduplicatedRecommended.length} after deduplication → ${validRecommended.length} after validation`);
        console.log(`   Removed: ${duplicates.length} duplicates + ${filteredCount - duplicates.length} not for sale = ${filteredCount} total filtered`);
      }
      
      // ✅ Debug: Log ticket status for recommendations
      if (validRecommended.length > 0) {
        const onChainCount = validRecommended.filter(art => ArtworkStatus.isOnChainArtwork(art)).length;
        const offChainCount = validRecommended.filter(art => ArtworkStatus.isOffChainArtwork(art)).length;
        
        if (activeRegistrationFilter === "all") {
          console.log(`🔍 Recommendations breakdown (all filter): ${onChainCount} on-chain, ${offChainCount} off-chain tickets`);
        } else {
          console.log(`🔍 Checking ${validRecommended.length} recommendations for registration filter: ${activeRegistrationFilter}`);
          console.log(`   Breakdown: ${onChainCount} on-chain, ${offChainCount} off-chain`);
        }
      }
      
      setRecommendedArtworksWithRef(validRecommended);
      setHasRecommendations(validRecommended.length > 0);
      return validRecommended;
    } catch (error) {
      console.error("❌ Failed to fetch recommendations:", error);
      console.error("Recommendation error details:", {
        message: error.message,
        response: error.response?.data,
        status: error.response?.status
      });
      
      // If it's a 404 or user not found, don't retry - this is normal for new users
      if (error.response?.status === 404) {
        console.log('👤 User not found in recommendation system - this is normal for new users');
        // Don't show toast for 404 - it's expected for new users
      } else if (error.response?.status !== 401) {
        // Only log warning, don't show error toast - recommendations are not critical
        console.warn('⚠️ Recommendations unavailable, continuing without them');
      }
      
      setRecommendedArtworksWithRef([]);
      setHasRecommendations(false);
      return [];
      }
    })();
    
    // Track the in-flight request
    inFlightRequests.current.set(requestKey, requestPromise);
    
    try {
      const result = await requestPromise;
      return result;
    } finally {
      // Clean up in-flight request
      inFlightRequests.current.delete(requestKey);
    }
  }, [effectiveUserId, activeRegistrationFilter, selectedNetworkKey]);

// ✅ FIXED: Reorder - recommendations first on page 1 (max 10), remaining recommended on page 2, then regular tickets
const reorderArtworks = useCallback((recommended, all, page = 1, maxItems = 10) => {
  const recommendedIds = new Set(recommended.map(art => (art._id || art.id)?.toString()).filter(Boolean));
  
  const recommendedList = [];
  const otherList = [];
  
  all.forEach(art => {
    const id = (art._id || art.id)?.toString();
    if (id && recommendedIds.has(id)) {
      recommendedList.push(art);
    } else {
      otherList.push(art);
    }
  });
  
  console.log(`📊 Reordering for page ${page}: ${recommendedList.length} recommended, ${otherList.length} regular, maxItems: ${maxItems}`);
  
  // ✅ FIXED: Page 1 - Show max 10 recommended tickets, then fill remaining slots with regular tickets
  if (page === 1) {
    // Limit recommended tickets to maxItems (10)
    const recommendedToShow = recommendedList.slice(0, maxItems);
    const recommendedRemaining = recommendedList.length - recommendedToShow.length;
    
    // Calculate remaining slots for regular tickets
    const remainingSlots = maxItems - recommendedToShow.length;
    const regularToShow = otherList.slice(0, remainingSlots);
    
    const result = [...recommendedToShow, ...regularToShow];
    console.log(`📄 Page 1: Showing ${recommendedToShow.length} recommended + ${regularToShow.length} regular = ${result.length} total (${recommendedRemaining} recommended remaining for page 2)`);
    return result;
  }
  
  // ✅ FIXED: Page 2 - Show remaining recommended tickets (if any), then fill with regular tickets
  if (page === 2) {
    const recommendedOnPage1 = Math.min(recommendedList.length, maxItems);
    const recommendedRemaining = recommendedList.length - recommendedOnPage1;
    
    if (recommendedRemaining > 0) {
      // Show remaining recommended tickets first
      const recommendedToShow = recommendedList.slice(recommendedOnPage1, recommendedOnPage1 + recommendedRemaining);
      const remainingSlots = maxItems - recommendedToShow.length;
      const regularToShow = otherList.slice(0, remainingSlots);
      
      const result = [...recommendedToShow, ...regularToShow];
      console.log(`📄 Page 2: Showing ${recommendedToShow.length} remaining recommended + ${regularToShow.length} regular = ${result.length} total`);
      return result;
    } else {
      // No remaining recommended, show regular tickets
      const regularToShow = otherList.slice(0, maxItems);
      console.log(`📄 Page 2: No remaining recommended, showing ${regularToShow.length} regular tickets`);
      return regularToShow;
    }
  }
  
  // ✅ FIXED: Page 3+ - Calculate offset correctly including recommended tickets from previous pages
  // Total recommended shown on page 1 and 2
  const recommendedOnPage1 = Math.min(recommendedList.length, maxItems);
  const recommendedRemaining = Math.max(0, recommendedList.length - recommendedOnPage1);
  const recommendedOnPage2 = Math.min(recommendedRemaining, maxItems);
  
  // Regular tickets shown on page 1
  const regularOnPage1 = maxItems - recommendedOnPage1;
  // Regular tickets shown on page 2
  const regularOnPage2 = maxItems - recommendedOnPage2;
  
  // Calculate starting index for regular tickets on current page
  const regularStart = regularOnPage1 + regularOnPage2 + (page - 3) * maxItems;
  const regularToShow = otherList.slice(regularStart, regularStart + maxItems);
  
  console.log(`📄 Page ${page}: Showing ${regularToShow.length} regular tickets (starting from index ${regularStart})`);
  return regularToShow;
}, []);

  // Perform semantic search
  const performSearch = async (query) => {
    if (!query.trim()) {
      // Reset to unified view
      setViewMode("unified");
      // ✅ Re-fetch tickets with current registration filter when resetting from search
      const tickets = await fetchAllArtworks(1, false);
      updatePage(1); // ✅ FIXED: Use helper to keep ref in sync
      const reordered = reorderArtworks(recommendedArtworks, tickets, 1, itemsPerPage);
      applyFiltersToArtworks(reordered);
      return;
    }

    setIsSearching(true);
    try {
      const response = await recommendationAPI.searchArtworks(query, 10); // ✅ Reduced to 10 for faster search
      const searchResults = response.results || [];
      
      // ✅ Filter out tickets that are not for sale (is_for_sale = false)
      const searchResultsForSale = searchResults.filter(ticket => {
        return ticket.is_for_sale !== false && shouldShowArtworkForSelectedNetwork(ticket, selectedNetworkKey);
      });
      
      setViewMode("search");
      applyFiltersToArtworks(searchResultsForSale);
      
      if (searchResults.length === 0) {
        toast.success("No tickets found matching your search");
      } else {
        toast.success(`Found ${searchResults.length} tickets`);
      }
    } catch (error) {
      // Force fallback to lightning fast local search
      handleLocalSearch(query);
    } finally {
      setIsSearching(false);
    }
  };

  // Fallback local search
  const handleLocalSearch = (query) => {
    const searchLower = query.toLowerCase();
    const results = allArtworks.filter((ticket) => {
      if (!ticket) return false;
      
      // ✅ Filter out tickets that are not for sale (is_for_sale = false)
      if (ticket.is_for_sale === false) return false;
      if (!shouldShowArtworkForSelectedNetwork(ticket, selectedNetworkKey)) return false;

      const title = ticket.title || "";
      const description = ticket.description || "";
      const creator = ticket.creator_address || "";
      const tokenId = ticket.token_id?.toString() || "";

      return (
        title.toLowerCase().includes(searchLower) ||
        description.toLowerCase().includes(searchLower) ||
        creator.toLowerCase().includes(searchLower) ||
        tokenId.includes(query)
      );
    });

    setViewMode("search");
    applyFiltersToArtworks(results);
    
    if (results.length === 0) {
      toast.success("No tickets found matching your search");
    } else {
      toast.success(`Found ${results.length} tickets`);
    }
  };

  // ✅ OPTIMIZED: useCallback for filter function
  // ✅ FIXED: Accept optional page parameter and skipRecommendedFilter flag to avoid double filtering
  const applyFiltersToArtworks = useCallback((tickets, explicitPage = null, skipRecommendedFilter = false) => {
    console.log('🔍 applyFiltersToArtworks called with:', {
      inputArtworks: tickets?.length,
      explicitPage,
      currentPage,
      skipRecommendedFilter
    });
    
    if (!tickets || tickets.length === 0) {
      setDisplayedArtworks([]);
      return;
    }

    // ✅ Use explicit page if provided, otherwise use currentPage from state
    const pageToUse = explicitPage !== null ? explicitPage : currentPage;
    let results = tickets;

    console.log('📊 Starting filter with:', results.length, 'tickets');

    // ✅ Filter out tickets that are not for sale
    results = results.filter(ticket => {
      return ticket && ticket.is_for_sale !== false && shouldShowArtworkForSelectedNetwork(ticket, selectedNetworkKey);
    });
    console.log('📊 After is_for_sale filter:', results.length);
    // Remove duplicates by ID (optimized with Map for O(n) instead of O(n²))
    const seenIds = new Map();
    const uniqueResults = [];
    
    for (const ticket of results) {
      const artId = ticket?._id || ticket?.id;
      if (!artId) continue;
      
      const idStr = artId.toString();
      if (!seenIds.has(idStr)) {
        seenIds.set(idStr, true);
        uniqueResults.push(ticket);
      }
    }
    
    results = uniqueResults;
    console.log('📊 After deduplication:', results.length);

    // ✅ Registration method filter (On-chain/Off-chain)
    // Filter is already applied in fetchAllArtworks and fetchRecommendations
    // But apply it here as a safety check for merged tickets
    // ✅ FIXED: Only preserve recommendations on page 1
    if (activeRegistrationFilter !== "all") {
      const beforeFilter = results.length;
      // ✅ OPTIMIZED: Use memoized recommendedIdsSet instead of recalculating
      const recommendedIds = recommendedIdsSet;
      
      // Separate recommended and non-recommended tickets
      const recommendedArtworksList = [];
      const otherArtworks = [];
      
      for (const ticket of results) {
        const artworkId = (ticket._id || ticket.id)?.toString();
        const isRecommended = artworkId && recommendedIds.has(artworkId);
        
        // ✅ FIXED: Only preserve recommendations on page 1
        if (isRecommended && pageToUse === 1) {
          // Only include recommendations on page 1 (they're already filtered by backend)
          recommendedArtworksList.push(ticket);
          console.log(`✅ Preserving recommended ticket on page 1: ${ticket.title || ticket._id}`, {
            is_on_chain: ticket.is_on_chain,
            registration_method: ticket.registration_method,
            payment_method: ticket.payment_method,
            isOffChain: ArtworkStatus.isOffChainArtwork(ticket),
            isOnChain: ArtworkStatus.isOnChainArtwork(ticket)
          });
        } else if (isRecommended && pageToUse !== 1) {
          // ✅ FIXED: Exclude recommended tickets on page 2+
          console.log(`🚫 Excluding recommended ticket on page ${pageToUse}: ${ticket.title || ticket._id}`);
          continue; // Skip this ticket
        } else {
          // Filter non-recommended tickets by registration_method
          let shouldInclude = true;
          
          if (activeRegistrationFilter === "on-chain") {
            shouldInclude = ArtworkStatus.isOnChainArtwork(ticket);
            if (!shouldInclude) {
              console.debug(`🚫 Filtered out off-chain ticket: ${ticket.title || ticket._id}`);
            }
          } else if (activeRegistrationFilter === "off-chain") {
            shouldInclude = ArtworkStatus.isOffChainArtwork(ticket);
            if (!shouldInclude) {
              console.warn(`🚫 Filtered out on-chain ticket from off-chain filter: ${ticket.title || ticket._id}`, {
                is_on_chain: ticket.is_on_chain,
                registration_method: ticket.registration_method
              });
            }
          }
          
          if (shouldInclude) {
            otherArtworks.push(ticket);
          }
        }
      }
      
      // Merge: recommended first (only on page 1), then filtered others
      results = pageToUse === 1 
        ? [...recommendedArtworksList, ...otherArtworks]
        : otherArtworks; // ✅ FIXED: No recommendations on page 2+
      
      const afterFilter = results.length;
      if (beforeFilter !== afterFilter) {
        console.log(`🔍 Registration filter "${activeRegistrationFilter}": ${beforeFilter} → ${afterFilter} tickets (${recommendedArtworksList.length} recommended preserved)`);
      }
      
      // Log recommended tickets count
      console.log(`📊 Recommended tickets in results: ${recommendedArtworksList.length} out of ${recommendedIdsSet.size} total recommendations`);
    } else {
      // ✅ NO FILTERING: reorderArtworks already handles excluding recommendations on page 2+
      // We're only reordering, not excluding - so don't filter here
      // Log recommended tickets count when no filter is applied
      const recommendedCount = results.filter(ticket => {
        const artworkId = (ticket._id || ticket.id)?.toString();
        return artworkId && recommendedIdsSet.has(artworkId);
      }).length;
      console.log(`📊 Recommended tickets in results (no filter): ${recommendedCount} out of ${recommendedIdsSet.size} total recommendations`);
    }

    if (filters.royalty !== "all") {
      results = results.filter((ticket) => {
        if (!ticket || !ticket.royalty_percentage) return false;
        const royalty = ticket.royalty_percentage / 100;
        switch (filters.royalty) {
          case "low":
            return royalty < 5;
          case "medium":
            return royalty >= 5 && royalty < 15;
          case "high":
            return royalty >= 15;
          default:
            return true;
        }
      });
    }
    console.log('✅ Setting displayedArtworks:', results.length);
    setDisplayedArtworks(results);
  }, [activeRegistrationFilter, filters, recommendedArtworks, recommendedIdsSet, currentPage, selectedNetworkKey]);

  // Handle search input with debounce
  useEffect(() => {
    const delayDebounceFn = setTimeout(() => {
      if (searchTerm.trim()) {
        performSearch(searchTerm);
      } else if (viewMode === "search") {
        // Reset to unified view
        setViewMode("unified");
        // ✅ Re-fetch tickets with current registration filter when resetting from search
        fetchAllArtworks(1, false).then((tickets) => {
          updatePage(1); // ✅ FIXED: Use helper to keep ref in sync
          const reordered = reorderArtworks(recommendedArtworks, tickets, 1, itemsPerPage);
          applyFiltersToArtworks(reordered);
        });
      }
    }, 500);

    return () => clearTimeout(delayDebounceFn);
  }, [searchTerm, selectedNetworkKey]);

  // Initial load - OPTIMIZED for maximum speed with progressive loading + caching
  useEffect(() => {
    // ✅ FIXED: Track mount time for deduplication
    window.explorerMountTime = Date.now();
    
    let isMounted = true;
    let backgroundLoadInProgress = false;
    
    const initializeExplorer = async () => {
      if (!isMounted) return;
      setIsLoading(true);
      
      try {
        const filterKey = activeRegistrationFilter;
        
        // ✅ OPTIMIZATION STEP 1: Check cache first (instant if available)
        // ✅ OPTIMIZATION STEP 1: Check cache first (instant if available)
// ✅ OPTIMIZATION STEP 1: Check cache first (instant if available)
if (ENABLE_CACHING) {
  const cacheKey = getCacheKey(filterKey);
  const cachedItem = localStorage.getItem(cacheKey);
  
  if (cachedItem) {
    try {
      // ✅ FIXED: Parse cache to get both data and timestamp
      const { data: cachedArtworks, timestamp } = JSON.parse(cachedItem);
      const cacheAge = Date.now() - timestamp;
      
      // Check if cache is still valid (within CACHE_DURATION)
      if (cacheAge < CACHE_DURATION && cachedArtworks && cachedArtworks.length > 0) {
        console.log(`⚡ Using cached data: ${cachedArtworks.length} tickets (${Math.round(cacheAge / 1000)}s old)`);
        setAllArtworksWithRef(cachedArtworks);
        
        // ✅ Calculate and set totalPages from cached data
        const calculatedPages = Math.ceil(cachedArtworks.length / itemsPerPage);
        setTotalPages(calculatedPages);
        setArtworkCounts({
          total: cachedArtworks.length,
          on_chain: cachedArtworks.filter(a => ArtworkStatus.isOnChainArtwork(a)).length,
          off_chain: cachedArtworks.filter(a => ArtworkStatus.isOffChainArtwork(a)).length,
          crypto: cachedArtworks.filter(a => ArtworkStatus.isOnChainArtwork(a)).length,
          paypal: cachedArtworks.filter(a => ArtworkStatus.isOffChainArtwork(a)).length
        });
        console.log(`📊 Ticket counts set from cache: ${cachedArtworks.length} total`);
        
        setIsLoading(false);
        updatePage(1);
        
        const reordered = reorderArtworks([], cachedArtworks, 1, itemsPerPage);
        applyFiltersToArtworks(reordered, 1);


        console.log('=== CACHE LOAD COMPLETE ===');
        console.log('  allArtworks set:', cachedArtworks.length);
        console.log('  totalPages set:', calculatedPages);
        console.log('  Filters applied for page 1');
        isInitialMount.current = false;
        
        // ✅ SMART: Only fetch counts in background if cache is older than 2 minutes
        const twoMinutes = 2 * 60 * 1000;
        if (cacheAge > twoMinutes) {
          console.log(`📊 Cache is ${Math.round(cacheAge / 1000)}s old, fetching fresh counts in background...`);
          fetchArtworkCounts().catch(() => {});
        } else {
          console.log(`✅ Cache is fresh (${Math.round(cacheAge / 1000)}s old), skipping background fetch`);
        }
        
        // Still fetch recommendations in background
        if (effectiveUserId && isMounted) {
          fetchRecommendations(effectiveUserId).then(recommended => {
            if (!isMounted || currentPageRef.current !== 1) return;
            if (recommended.length > 0) {
              const reordered = reorderArtworks(recommended, cachedArtworks, 1, itemsPerPage);
              applyFiltersToArtworks(reordered, 1);
            }
          }).catch(() => {});
        }
        
        return; // Exit early - cached data shown
      } else {
        // Cache expired, remove it
        console.log(`🗑️ Cache expired (${Math.round(cacheAge / 1000)}s old), removing...`);
        localStorage.removeItem(cacheKey);
      }
    } catch (error) {
      console.error('❌ Error parsing cache:', error);
      // Continue to normal fetch if cache parsing fails
      localStorage.removeItem(cacheKey);
    }
  }
}
        // ✅ OPTIMIZATION STEP 2: Progressive loading - Fast first page (1-2 seconds)
        if (ENABLE_PROGRESSIVE_LOADING) {
          console.log('🚀 Progressive load: Fetching first page only...');
          const firstPageArtworks = await fetchAllArtworks(1, false);
          
          if (!isMounted) return;
          
          if (firstPageArtworks && firstPageArtworks.length > 0) {
            console.log(`✅ Fast load complete: ${firstPageArtworks.length} tickets`);
            
            // Show first page immediately
            setAllArtworksWithRef(firstPageArtworks);
            setIsLoading(false);
            updatePage(1);
            
            const reordered = reorderArtworks([], firstPageArtworks, 1, itemsPerPage);
            applyFiltersToArtworks(reordered, 1);
            isInitialMount.current = false;
            
            // Fetch recommendations in parallel with background load
            if (effectiveUserId && isMounted) {
              fetchRecommendations(effectiveUserId).then(recommended => {
                if (!isMounted || currentPageRef.current !== 1) return;
                if (recommended.length > 0) {
                  // Use current allArtworks state (might be full dataset by now)
                  const currentArtworks = allArtworks.length > firstPageArtworks.length 
                    ? allArtworks 
                    : firstPageArtworks;
                  const reordered = reorderArtworks(recommended, currentArtworks, 1, itemsPerPage);
                  applyFiltersToArtworks(reordered, 1);
                }
              }).catch(() => {});
            }
            
            // ✅ OPTIMIZATION STEP 3: Background load remaining tickets (non-blocking)
            if (!backgroundLoadInProgress && isMounted) {
              backgroundLoadInProgress = true;
              console.log('🔄 Background load: Fetching all tickets...');
              
              fetchAllArtworksComplete().then(allArtworksData => {
                if (!isMounted) return;
                
                if (allArtworksData && allArtworksData.length > 0) {
                  console.log(`✅ Background load complete: ${allArtworksData.length} total tickets`);
                  
                  // Update with full dataset
                  setAllArtworksWithRef(allArtworksData);
                  setTotalPages(Math.max(1, Math.ceil(allArtworksData.length / itemsPerPage)));
                  
                  // Cache the full dataset
                  setCachedData(filterKey, allArtworksData);
                  
                  // Re-apply filters if still on page 1
                  if (currentPageRef.current === 1) {
                    const reordered = reorderArtworks(
                      recommendedArtworks,
                      allArtworksData,
                      1,
                      itemsPerPage
                    );
                    applyFiltersToArtworks(reordered, 1);
                  }
                }
                backgroundLoadInProgress = false;
              }).catch(error => {
                console.error('❌ Background load failed:', error);
                backgroundLoadInProgress = false;
              });
            }
          } else {
            // ✅ FIX: Fallback if first page fetch fails - try full fetch
            console.warn('⚠️ First page fetch returned no data, trying full fetch...');
        const allArtworksData = await fetchAllArtworksComplete();
        
        if (!isMounted) return;
        
            if (allArtworksData && allArtworksData.length > 0) {
              console.log(`✅ Fallback load complete: ${allArtworksData.length} tickets`);
          setAllArtworksWithRef(allArtworksData);
              setTotalPages(Math.max(1, Math.ceil(allArtworksData.length / itemsPerPage)));
              setCachedData(filterKey, allArtworksData);
              setIsLoading(false);
              updatePage(1);
          
          const reordered = reorderArtworks([], allArtworksData, 1, itemsPerPage);
              applyFiltersToArtworks(reordered, 1);
              isInitialMount.current = false;
              
              // Load recommendations
              if (effectiveUserId && isMounted) {
                fetchRecommendations(effectiveUserId).then(recommended => {
                  if (!isMounted || currentPageRef.current !== 1) return;
                  if (recommended.length > 0) {
                    const reordered = reorderArtworks(recommended, allArtworksData, 1, itemsPerPage);
                    applyFiltersToArtworks(reordered, 1);
                  }
                }).catch(() => {});
              }
            } else {
              // No data is a valid state. Show empty UI instead of treating it as a fatal error.
              setAllArtworksWithRef([]);
              setDisplayedArtworks([]);
              setRecommendedArtworksWithRef([]);
              setTotalPages(1);
              setIsLoading(false);
              isInitialMount.current = false;
              return;
            }
          }
        } else {
          // Fallback if first page fetch fails - try full fetch
          console.warn('⚠️ First page fetch failed, trying full fetch...');
          const allArtworksData = await fetchAllArtworksComplete();
          
          if (!isMounted) return;
          
          if (allArtworksData && allArtworksData.length > 0) {
            console.log(`✅ Fallback load complete: ${allArtworksData.length} tickets`);
            setAllArtworksWithRef(allArtworksData);
            setTotalPages(Math.max(1, Math.ceil(allArtworksData.length / itemsPerPage)));
            setCachedData(filterKey, allArtworksData);
            setIsLoading(false);
            updatePage(1);
            
            const reordered = reorderArtworks([], allArtworksData, 1, itemsPerPage);
            applyFiltersToArtworks(reordered, 1);
            isInitialMount.current = false;
            
            // Load recommendations
        if (effectiveUserId && isMounted) {
          fetchRecommendations(effectiveUserId).then(recommended => {
                if (!isMounted || currentPageRef.current !== 1) return;
                if (recommended.length > 0) {
              const reordered = reorderArtworks(recommended, allArtworksData, 1, itemsPerPage);
                  applyFiltersToArtworks(reordered, 1);
                }
              }).catch(() => {});
            }
          } else {
            // No data is a valid state. Show empty UI instead of treating it as a fatal error.
            setAllArtworksWithRef([]);
            setDisplayedArtworks([]);
            setRecommendedArtworksWithRef([]);
            setTotalPages(1);
            setIsLoading(false);
            isInitialMount.current = false;
            return;
          }
        }
        
      } catch (error) {
        console.error('❌ Explorer initialization error:', error);
        if (isMounted) {
          setIsLoading(false);
          isInitialMount.current = false;
          
          // ✅ FIX: Clear potentially stale data on error
          setAllArtworksWithRef([]);
          setDisplayedArtworks([]);
          setRecommendedArtworksWithRef([]);
          
          // Clear cache if there's an error loading
          console.log('🗑️ Clearing cache due to initialization error');
          clearCache();
          
          toast.error('Failed to load tickets. Please refresh the page.');
        }
      }
    };

    initializeExplorer();
    
    return () => {
      isMounted = false;
      backgroundLoadInProgress = false;
      // ✅ OPTIMIZATION: Cancel all in-flight requests on unmount
      abortControllers.current.forEach(controller => controller.abort());
      abortControllers.current.clear();
      inFlightRequests.current.clear();
    };
  }, [user?.id, isAuthenticated, account, activeRegistrationFilter, selectedNetworkKey, refreshTrigger]); // ✅ Added activeRegistrationFilter and selected network for cache key

// ✅ FIX: Clear stale cache ONLY when user actually changes
useEffect(() => {
  const currentUserId = user?.id?.toString();
  
  // ✅ IMPORTANT: Initialize on first mount
  if (window.lastExplorerUserId === undefined) {
    console.log('🎬 First auth check, initializing:', currentUserId || 'guest');
    window.lastExplorerUserId = currentUserId;
    return; // Don't do anything on first mount
  }
  
  const lastUserId = window.lastExplorerUserId;
  
  // ✅ Check if user actually changed
  if (currentUserId === lastUserId) {
    console.log('✅ Same user, no cache cleanup needed');
    return; // Same user, do nothing
  }
  
  // User changed!
  console.log('👤 User changed! Cleanup starting...');
  console.log(`   From: ${lastUserId || 'guest'} → To: ${currentUserId || 'guest'}`);
  
  // Scenario 1: Different user logged in (User A → User B)
  if (currentUserId && lastUserId && currentUserId !== lastUserId) {
    console.log('🔄 Different user - clearing old user cache');
    Object.keys(localStorage)
      .filter(key => {
        if (!key.startsWith(CACHE_KEY_PREFIX)) return false;
        const parts = key.split('_');
        const keyUserId = parts[parts.length - 1];
        return keyUserId === lastUserId; // Only clear LAST user's cache
      })
      .forEach(key => {
        console.log(`🗑️ Removing old user cache: ${key}`);
        localStorage.removeItem(key);
      });
  }
  
  // Scenario 2: User logged out (User → Guest)
  else if (!currentUserId && lastUserId) {
    console.log('👋 User logged out - clearing user caches');
    Object.keys(localStorage)
      .filter(key => key.startsWith(CACHE_KEY_PREFIX) && !key.endsWith('_guest'))
      .forEach(key => {
        console.log(`🗑️ Removing user cache: ${key}`);
        localStorage.removeItem(key);
      });
  }
  
  // Scenario 3: User logged in (Guest → User)
  else if (currentUserId && !lastUserId) {
    console.log('🔐 User logged in - clearing guest cache');
    Object.keys(localStorage)
      .filter(key => key.startsWith(CACHE_KEY_PREFIX) && key.endsWith('_guest'))
      .forEach(key => {
        console.log(`🗑️ Removing guest cache: ${key}`);
        localStorage.removeItem(key);
      });
  }
  
  // Update last user ID
  window.lastExplorerUserId = currentUserId;
  console.log('✅ Cleanup complete, updated lastUserId to:', currentUserId);
  
}, [user?.id, CACHE_KEY_PREFIX]);

  // ✅ FIX: Force refetch if no tickets loaded after mount
  useEffect(() => {
    // Wait a bit for initial load to complete
    const timer = setTimeout(() => {
      if (allArtworks.length === 0 && !isLoading) {
        console.warn('⚠️ No tickets loaded 3 seconds after mount, forcing refetch');
        console.log('State check:', {
          isLoading,
          isInitialMount: isInitialMount.current,
          allArtworksLength: allArtworks.length,
          displayedArtworksLength: displayedArtworks.length
        });
        
        // Clear cache and force reload
        clearCache();
        setRetryCount(prev => prev + 1);
        
        // Manually trigger initialization
        setIsLoading(true);
        isInitialMount.current = true;
      }
    }, 3000); // 3 second timeout
    
    return () => clearTimeout(timer);
  }, []); // Run only once on mount

  // Retry recommendations if needed
  useEffect(() => {
      // ✅ FIXED: Don't run immediately on mount
  if (isInitialMount.current) {
    return;
  }
    const retryRecommendations = async () => {
      // ✅ FIXED: Use ref to avoid stale closure
      const currentArtworks = allArtworksRef.current;
      
      if (isAuthenticated && user?.id && currentArtworks.length > 0 && 
          !hasRecommendations && recommendationAttempts < 3) {
        
        console.log('🔄 Retrying recommendations... Attempt:', recommendationAttempts + 1);
        setRecommendationAttempts(prev => prev + 1);
        
        if (effectiveUserId) {
          const recommended = await fetchRecommendations(effectiveUserId);
          if (recommended.length > 0) {
            // ✅ FIXED: Only apply if user is still on page 1
            if (currentPageRef.current === 1) {
              const reordered = reorderArtworks(recommended, allArtworksRef.current, 1, itemsPerPage);
              applyFiltersToArtworks(reordered, 1); // ✅ Explicit page parameter
            } else {
              console.log('⏭️ User navigated away from page 1, skipping recommendation merge');
            }
          }
        }
        
        // Add delay between retries
        await new Promise(resolve => setTimeout(resolve, 2000));
      }
    };

    // Add delay before retry
    const timer = setTimeout(() => {
    retryRecommendations();
    }, 2000); // 2 second delay
    
    return () => clearTimeout(timer);
  }, [user?.id, isAuthenticated, hasRecommendations]);

  // ✅ Re-fetch counts, tickets, and recommendations when registration filter changes
  useEffect(() => {
    const timer = setTimeout(() => {
    // Skip on initial mount (handled by initial load useEffect)
    if (isInitialMount.current) {
      console.log('⏭️ Skipping filter change on initial mount');
      return;
    }
    
    // Don't run if tickets haven't been loaded yet
    if (allArtworks.length === 0) {
      console.log('⏳ Tickets not loaded yet, waiting for initial load...');
      return;
    }
    
    // ✅ FIXED: Don't run if we just mounted (within 1 second)
    const timeSinceMount = Date.now() - (window.explorerMountTime || 0);
    if (timeSinceMount < 1000) {
      console.log('⏭️ Just mounted, skipping filter effect');
      return;
    }
    
    // ✅ OPTIMIZATION: Prevent concurrent filter changes
    const filterKey = `filter-${activeRegistrationFilter}-${selectedNetworkKey || 'wirefluid'}-${viewMode}`;
    if (inFlightRequests.current.has(filterKey)) {
      console.log(`⏭️ Filter change already in progress: ${filterKey}`);
      return;
    }
    
    const refetchData = async () => {
      // Mark filter change as in progress
      inFlightRequests.current.set(filterKey, Promise.resolve());
      
      try {
        // ✅ Always re-fetch counts when filter changes to ensure accuracy
        console.log('🔄 Registration filter changed to:', activeRegistrationFilter);
        
        // ✅ OPTIMIZATION: Check cache first for new filter
        if (ENABLE_CACHING) {
          const cachedData = getCachedData(activeRegistrationFilter);
          if (cachedData && cachedData.length > 0) {
            console.log(`⚡ Using cached data for filter: ${activeRegistrationFilter}`);
            setAllArtworksWithRef(cachedData);
            
            // ✅ FIX: Calculate totalPages here too
            const calculatedPages = Math.ceil(cachedData.length / itemsPerPage);
            setTotalPages(calculatedPages);
            
            updatePage(1);
            
            if (viewMode === "unified") {
              const reordered = reorderArtworks([], cachedData, 1, itemsPerPage);
              applyFiltersToArtworks(reordered, 1);
              
              if (isAuthenticated && effectiveUserId) {
                fetchRecommendations(effectiveUserId).then(recommended => {
                  if (recommended.length > 0 && currentPageRef.current === 1) {
                    const reorderedWithRecs = reorderArtworks(recommended, cachedData, 1, itemsPerPage);
                    applyFiltersToArtworks(reorderedWithRecs, 1);
                  }
                }).catch(() => {});
              }
            }

            // Show cached data immediately for fast UX, then revalidate from API.
            console.log('🔄 Revalidating cached explorer data from API...');
        }
        }
        
        // ✅ FIXED: Simplified - only fetch counts and ALL tickets (no duplicate fetching)
        await fetchArtworkCounts();
        
        console.log('🔄 Fetching all tickets for new filter...');
        const allArtworksData = await fetchAllArtworksComplete();
        
        if (allArtworksData.length === 0) {
          console.warn('⚠️ No tickets returned for filter');
          setAllArtworksWithRef([]);
          setDisplayedArtworks([]);
          setTotalPages(1);
          inFlightRequests.current.delete(filterKey);
          return;
        }
        
        console.log(`📚 Fetched ${allArtworksData.length} tickets with registration filter: ${activeRegistrationFilter}`);
        
        // ✅ OPTIMIZATION: Cache the fetched data
        setCachedData(activeRegistrationFilter, allArtworksData);
        
        // ✅ Update allArtworks state with all fetched tickets
        setAllArtworksWithRef(allArtworksData);
        setTotalPages(Math.max(1, Math.ceil(allArtworksData.length / itemsPerPage)));
        updatePage(1); // ✅ FIXED: Reset to page 1 when filter changes (keep ref in sync)
        
        if (viewMode === "unified") {
          if (isAuthenticated && effectiveUserId) {
            console.log('🔄 Re-fetching recommendations for new filter...');
            // ✅ Show tickets immediately, load recommendations in background
            // ✅ Reorder: ALL tickets, recommendations first (NO EXCLUSIONS)
            const reordered = reorderArtworks([], allArtworksData, 1, itemsPerPage);
            applyFiltersToArtworks(reordered, 1);
            
            // Load recommendations in background (only for page 1)
            fetchRecommendations(effectiveUserId).then(recommended => {
              if (recommended.length > 0 && currentPageRef.current === 1) {
                // ✅ Reorder: ALL recommendations first, then ALL other tickets (NO EXCLUSIONS)
                const reorderedWithRecs = reorderArtworks(recommended, allArtworksData, 1, itemsPerPage);
                applyFiltersToArtworks(reorderedWithRecs, 1);
              }
            }).catch(error => {
              console.warn('⚠️ Recommendations failed:', error);
            });
          } else {
            // If no user or not authenticated, just re-apply filters
            // ✅ Reorder: ALL tickets, recommendations first (if any), then all others (NO EXCLUSIONS)
            const reordered = reorderArtworks(recommendedArtworks, allArtworksData, 1, itemsPerPage);
            applyFiltersToArtworks(reordered, 1);
          }
        }
      } catch (error) {
        console.error('❌ Error refetching data for filter change:', error);
        toast.error('Failed to update filter');
      } finally {
        // Remove from in-flight after completion
        inFlightRequests.current.delete(filterKey);
      }
    };
    
    refetchData();
  }, 100); // 100ms delay
  return () => clearTimeout(timer);
}, [activeRegistrationFilter, selectedNetworkKey, viewMode]); // ✅ FIXED: Removed function dependencies

  // Apply filters when filters (licensed/royalty) change
  // Note: This doesn't re-fetch tickets, just re-applies the filter logic
  // ✅ IMPORTANT: Only runs when filters change, NOT when page/displayedArtworks change
  // Pagination is handled by goToPage function
  useEffect(() => {
    // Skip if no tickets loaded yet
    if (allArtworks.length === 0) return;
    
    if (viewMode === "unified") {
      const reordered = reorderArtworks(recommendedArtworks, allArtworks, currentPage, itemsPerPage);
      applyFiltersToArtworks(reordered, currentPage);
    } else if (viewMode === "search" && displayedArtworks.length > 0) {
      // Reapply filters to current displayed tickets
      applyFiltersToArtworks(displayedArtworks);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters]); // ✅ FIXED: Only trigger on filter changes to prevent infinite loops

  const resetFilters = () => {
    setSearchTerm("");
    setFilters({ royalty: "all" });
    setViewMode("unified");
    // ✅ Always pass full recommendedArtworks - function handles page logic internally
    const reordered = reorderArtworks(recommendedArtworks, allArtworks, currentPage, itemsPerPage);
    applyFiltersToArtworks(reordered, currentPage);
  };

  // ✅ OPTIMIZED: useCallback for click handler
  const handleArtworkClick = useCallback(async (artworkId) => {
    if (effectiveUserId) {
      // Don't await - fire and forget for better performance
      recommendationAPI.trackArtworkView(artworkId).catch(() => {
        // Silently fail - tracking is not critical
      });
    }
  }, [effectiveUserId]);
  
  // ✅ OPTIMIZED: Navigate to specific page
  // ✅ FIXED: Fetch additional tickets if filtering removes recommended ones
  const goToPage = useCallback(async (page) => {
    if (isLoadingMore || page < 1 || page > totalPages || page === currentPage || viewMode !== "unified") {
      return;
    }
    
    setIsLoadingMore(true);
    try {
      // Scroll to top when changing pages
      window.scrollTo({ top: 0, behavior: 'smooth' });
      
      // ✅ FIXED: Use refs to access latest state
      const currentArtworks = allArtworksRef.current || allArtworks;
      const currentRecommended = recommendedArtworksRef.current || recommendedArtworks;
      
      // If no tickets, fetch them
      if (!currentArtworks || currentArtworks.length === 0) {
        console.log('⚠️ No tickets in state, fetching...');
        const allArtworksData = await fetchAllArtworksComplete();
        setAllArtworksWithRef(allArtworksData);
        setTotalPages(Math.max(1, Math.ceil(allArtworksData.length / itemsPerPage)));
        
        updatePage(page);
        
        const reordered = reorderArtworks(currentRecommended || [], allArtworksData, page, itemsPerPage);
        console.log(`📊 Reordered tickets for page ${page}: ${reordered.length} items`);
        applyFiltersToArtworks(reordered, page, false);
      } else {
        console.log(`📄 Going to page ${page} with ${currentArtworks?.length || 0} total tickets`);
        
        updatePage(page);
        
        // Reorder with current values
        const reordered = reorderArtworks(currentRecommended || [], currentArtworks, page, itemsPerPage);
        console.log(`📊 Reordered tickets for page ${page}: ${reordered.length} items`);
        applyFiltersToArtworks(reordered, page, false);
      }
    } catch (error) {
      console.error('Failed to load page:', error);
      toast.error('Failed to load page');
    } finally {
      setIsLoadingMore(false);
    }
  }, [
    isLoadingMore,
    currentPage,
    totalPages, 
    viewMode, 
    itemsPerPage, 
    updatePage,
    reorderArtworks,
    applyFiltersToArtworks,
    fetchAllArtworksComplete
  ]); // ✅ FIXED: Using refs, so allArtworks/recommendedArtworks not needed in deps // ✅ FIXED: Using functional setState to avoid stale closures
  
  // ✅ OPTIMIZED: Load more tickets (for infinite scroll - kept for backward compatibility)
  const loadMoreArtworks = useCallback(async () => {
    if (isLoadingMore || !hasMore || viewMode !== "unified") return;
    
    const nextPage = currentPage + 1;
    await goToPage(nextPage);
  }, [isLoadingMore, hasMore, currentPage, viewMode, goToPage]);
  
  // ✅ OPTIMIZED: Previous page navigation
  const goToPreviousPage = useCallback(() => {
    if (currentPage > 1) {
      goToPage(currentPage - 1);
    }
  }, [currentPage, goToPage]);
  
  // ✅ OPTIMIZED: Next page navigation
  const goToNextPage = useCallback(() => {
    if (currentPage < totalPages) {
      goToPage(currentPage + 1);
    }
  }, [currentPage, totalPages, goToPage]);

  // ✅ OPTIMIZED: useCallback and useMemo for recommended check
// ✅ FIXED: Show "FOR YOU" badge on all pages where recommended tickets appear
const isRecommended = useCallback((artworkId) => {
  if (!artworkId) return false;
  const artworkIdStr = artworkId.toString();
  // Check if ticket is in recommended set (works for all pages)
  const isRecommendedArtwork = recommendedIdsSet.has(artworkIdStr);
  return isRecommendedArtwork;
}, [recommendedIdsSet]);

  // ✅ OPTIMIZED: Intersection Observer for infinite scroll (optional - disabled for page-based navigation)
  // Note: Commented out to use page-based navigation instead
  // Uncomment if you want to enable infinite scroll alongside page navigation
  /*
  const loadMoreRef = useRef(null);
  
  useEffect(() => {
    if (!loadMoreRef.current || !hasMore || isLoadingMore || viewMode !== "unified") return;
    
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting) {
          loadMoreArtworks();
        }
      },
      { threshold: 0.1 }
    );
    
    observer.observe(loadMoreRef.current);
    
    return () => {
      if (loadMoreRef.current) {
        observer.unobserve(loadMoreRef.current);
      }
    };
  }, [hasMore, isLoadingMore, viewMode, loadMoreArtworks]);
  */

  return (
    <div className="bg-white min-h-screen">
      {/* Hero Section */}
      <div className="relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-r from-green-900 to-green-700 opacity-90"></div>
        <div
          className="absolute inset-0 bg-cover bg-center opacity-20"
          style={{
            backgroundImage:
              "url('https://images.pexels.com/photos-373965/pexels-photo-373965.jpeg?auto=compress&cs=tinysrgb&w=1600')",
          }}
        ></div>
        <div className="relative max-w-4xl mx-auto py-20 px-6 text-center">
          <h1 className="text-4xl font-extrabold text-white mb-4">
            Smart-Ticket Explorer
          </h1>
          <p className="text-lg text-green-100 max-w-2xl mx-auto">
            Discover and explore verified PSL smart-tickets on the blockchain.
          </p>
          <p className="text-md text-green-200 mt-2">
            {viewMode === "search" 
              ? `Search results for "${searchTerm}"`
              : hasRecommendations
              ? `${recommendedArtworks.length} personalized recommendations • ${activeFilterTotalCount} total available`
              : isAuthenticated
              ? `${activeFilterTotalCount} tickets in our network`
              : `${activeFilterTotalCount} tickets in our network`
            }
          </p>

          {isAuthenticated && (
            <div className="mt-6">
              {/* <Link
                to="/dashboard/upload"
                className="inline-flex items-center px-8 py-3 text-lg font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors shadow-md"
              >
                Issue New Ticket
                <ArrowRight className="ml-2 w-5 h-5" />
              </Link> */}
            </div>
          )}
        </div>
      </div>

      {/* Recommendations Info Banner - Only show on page 1 */}
      {hasRecommendations && viewMode === "unified" && currentPage === 1 ? (
        <div className="max-w-6xl mx-auto px-6 mt-8 mb-4">
          <div className="p-4 bg-green-50 rounded-lg border border-green-200">
            <div className="flex items-center text-green-800">
              <Sparkles className="w-5 h-5 mr-2" />
              <span className="font-medium">
                Showing {recommendedArtworks.length} personalized recommendations ({activeFilterLabel}) first, followed by other {activeItemLabelPlural}
              </span>
            </div>
          </div>
        </div>
      ) : (
        <div className="mt-8"></div>
      )}

      {/* Search + Filters */}
      <div className="max-w-6xl mx-auto px-6 mb-8 mt-5">
        <div className="bg-white p-4 sm:p-5 rounded-xl shadow-md border border-gray-200">
          <div className="flex flex-col xl:flex-row xl:items-center gap-3">
            <div className="relative w-full shrink-0">
              <div className="absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none">
              <Search className="h-5 w-5 text-gray-600" />
              </div>
              <input
                type="text"
                placeholder="Search by venue, team, date or token ID..."
                className="block w-full h-12 pl-10 pr-10 border border-gray-400 rounded-lg focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-green-500"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
              />
              {isSearching && (
                <div className="absolute right-3 top-1/2 -translate-y-1/2 flex items-center">
                  <LoadingSpinner size="small" />
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Ticket Grid */}
      <div className="max-w-7xl mx-auto px-6 pb-16">
  {/* ✅ FIXED: Show loading while data is being processed */}
  {(isLoading || (displayedArtworks.length === 0 && allArtworks.length > 0)) ? (
    ENABLE_SKELETON_UI ? (
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6 mb-8">
        {[...Array(6)].map((_, i) => (
          <TicketSkeleton key={`skeleton-${i}`} />
        ))}
      </div>
    ) : (
          <div className="flex justify-center p-12">
            <LoadingSpinner size="large" />
          </div>
    )
        ) : displayedArtworks.length === 0 ? (
          <div className="text-center py-12 bg-white rounded-lg shadow border border-gray-200">
            <FileText className="w-12 h-12 text-gray-400 mx-auto mb-4" />
            <p className="text-gray-500 mb-4">
              {viewMode === "search" 
                ? `No ${activeItemLabelPlural} found for "${searchTerm}"`
                : `No ${activeItemLabelPlural} found matching your criteria`
              }
            </p>
            <button
              onClick={resetFilters}
              className="text-green-600 hover:text-green-800 font-medium"
            >
              {viewMode === "search" ? "Clear search" : "Clear all filters"}
            </button>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6 mb-8">
              {displayedArtworks.map((ticket) => {
                const artworkId = ticket._id || ticket.id;
                return (
                  <div key={artworkId} onClick={() => handleArtworkClick(artworkId)}>
                    <TicketCard
                      ticket={ticket}
                      currentAccount={account}
                      isRecommended={isRecommended(artworkId)}
                      currentUserId={effectiveUserId}
                      selectedNetwork={selectedNetwork}
                      isAuthenticated={isAuthenticated}
                    />
                  </div>
                );
              })}
            </div>
            
            {/* ✅ OPTIMIZED: Modern Pagination controls with page numbers */}
            {viewMode === "unified" && totalPages > 1 && (
              <div className="flex flex-col items-center mt-12 mb-8 gap-6">
                {/* Page Navigation Controls - Enhanced Styling */}
                <div className="flex items-center gap-3 flex-wrap justify-center bg-white rounded-xl shadow-lg border border-gray-200 p-4">
                  {/* Previous Button */}
                  <button
                    onClick={goToPreviousPage}
                    disabled={currentPage === 1 || isLoadingMore}
                    className="px-5 py-2.5 bg-gradient-to-r from-gray-50 to-gray-100 border border-gray-300 rounded-lg hover:from-gray-100 hover:to-gray-200 disabled:opacity-40 disabled:cursor-not-allowed transition-all duration-200 flex items-center gap-2 text-sm font-semibold text-gray-700 shadow-sm hover:shadow-md disabled:hover:shadow-sm active:scale-95"
                  >
                    <ChevronLeft className="w-4 h-4" />
                    <span>Previous</span>
                  </button>
                  
                  {/* Page Numbers */}
                  <div className="flex items-center gap-2">
                    {(() => {
                      const pages = [];
                      const maxVisiblePages = 7;
                      let startPage = Math.max(1, currentPage - Math.floor(maxVisiblePages / 2));
                      let endPage = Math.min(totalPages, startPage + maxVisiblePages - 1);
                      
                      // Adjust start if we're near the end
                      if (endPage - startPage < maxVisiblePages - 1) {
                        startPage = Math.max(1, endPage - maxVisiblePages + 1);
                      }
                      
                      // First page
                      if (startPage > 1) {
                        pages.push(
                          <button
                            key={1}
                            onClick={() => goToPage(1)}
                            disabled={isLoadingMore}
                            className="px-4 py-2.5 min-w-[40px] bg-white border-2 border-gray-300 rounded-lg hover:border-green-400 hover:bg-green-50 disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-200 text-sm font-semibold text-gray-700 shadow-sm hover:shadow-md active:scale-95"
                          >
                            1
                          </button>
                        );
                        if (startPage > 2) {
                          pages.push(
                            <span key="ellipsis-start" className="px-2 text-gray-400 font-semibold">
                              ...
                            </span>
                          );
                        }
                      }
                      
                      // Page numbers
                      for (let i = startPage; i <= endPage; i++) {
                        pages.push(
                          <button
  key={i}
  onClick={() => goToPage(i)}
  disabled={isLoadingMore}
  className={`px-4 py-2.5 min-w-[40px] rounded-lg transition-all duration-200 text-sm font-semibold shadow-sm active:scale-95 ${
    i === currentPage
      ? 'bg-gradient-to-br from-green-600 to-green-700 !text-white hover:from-green-700 hover:to-green-800 shadow-md ring-2 ring-green-300 ring-offset-2'
      : 'bg-white border-2 border-gray-300 text-gray-700 hover:border-green-400 hover:bg-green-50 disabled:opacity-50 disabled:cursor-not-allowed hover:shadow-md'
  }`}
>
  {i}
</button>
                        );
                      }
                      
                      // Last page
                      if (endPage < totalPages) {
                        if (endPage < totalPages - 1) {
                          pages.push(
                            <span key="ellipsis-end" className="px-2 text-gray-400 font-semibold">
                              ...
                            </span>
                          );
                        }
                        pages.push(
                          <button
                            key={totalPages}
                            onClick={() => goToPage(totalPages)}
                            disabled={isLoadingMore}
                            className="px-4 py-2.5 min-w-[40px] bg-white border-2 border-gray-300 rounded-lg hover:border-green-400 hover:bg-green-50 disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-200 text-sm font-semibold text-gray-700 shadow-sm hover:shadow-md active:scale-95"
                          >
                            {totalPages}
                          </button>
                        );
                      }
                      
                      return pages;
                    })()}
                  </div>
                  
                  {/* Next Button */}
                  <button
                    onClick={goToNextPage}
                    disabled={currentPage === totalPages || isLoadingMore}
                    className="px-5 py-2.5 bg-gradient-to-r from-gray-50 to-gray-100 border border-gray-300 rounded-lg hover:from-gray-100 hover:to-gray-200 disabled:opacity-40 disabled:cursor-not-allowed transition-all duration-200 flex items-center gap-2 text-sm font-semibold text-gray-700 shadow-sm hover:shadow-md disabled:hover:shadow-sm active:scale-95"
                  >
                    <span>Next</span>
                    <ChevronRight className="w-4 h-4" />
                  </button>
                </div>
                
                {/* Pagination Info - Enhanced Styling */}
                <div className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-green-50 to-blue-50 rounded-lg border border-green-200">
                  <div className="flex items-center gap-2">
                    <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse"></div>
                    <span className="text-sm font-medium text-gray-700">
                      Page <span className="font-bold text-green-600">{currentPage}</span> of <span className="font-bold text-green-600">{totalPages}</span>
                    </span>
                  </div>
                  {activeFilterTotalCount > 0 && (
                    <span className="text-xs text-gray-500">
                      • {displayedArtworks.length} on this page • {activeFilterTotalCount} total
                    </span>
                  )}
                </div>
                
                {/* Loading Indicator - Enhanced */}
                {/* {isLoadingMore && (
                  <div className="flex items-center gap-3 px-4 py-2 bg-blue-50 rounded-lg border border-blue-200">
                    <LoadingSpinner size="small" />
                    <span className="text-sm font-medium text-blue-700">Loading page {currentPage}...</span>
                  </div>
                )} */}
              </div>
            )}
            
            {/* Fallback: Show simple info if only one page or no pagination needed */}
            {viewMode === "unified" && totalPages <= 1 && (
              <div className="flex flex-col items-center mt-8 gap-2">
                <div className="text-sm text-gray-600">
                  Showing all {displayedArtworks.length} {activeItemLabelPlural}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
};

export default Explorer;