import React, { useState, useEffect } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { useWeb3 } from "../context/Web3Context";
import { useAuth } from "../context/AuthContext";
import { ticketsAPI } from "../services/api";
import { UserIdentifier, CurrencyConverter, ArtworkStatus } from "../utils/currencyUtils";
import {
  Palette,
  User,
  Clock,
  DollarSign,
  ArrowLeft,
  Copy,
  ExternalLink,
  CheckCircle,
  XCircle,
  Wallet,
  CreditCard,
  ShoppingCart,
  Database,
} from "lucide-react";
import LoadingSpinner from "../components/common/LoadingSpinner";
import toast from "react-hot-toast";
import { useImageProtection } from "../hooks/useImageProtection";
import ProtectedImage from "../components/common/ProtectedImage";
import axios from "axios";

const API_BASE = import.meta.env.VITE_BASE_URL_BACKEND || '';

// Date formatting utility functions
const formatDate = (dateString) => {
  if (!dateString) return "N/A";

  try {
    const date = new Date(dateString);
    if (isNaN(date.getTime())) {
      const altDate = new Date(dateString.replace(/\.\d+Z$/, "Z"));
      if (!isNaN(altDate.getTime())) {
        return altDate.toLocaleDateString();
      }
      return "Invalid Date";
    }

    return date.toLocaleDateString();
  } catch (error) {
    console.error("Error formatting date:", error, dateString);
    return "Invalid Date";
  }
};

const formatDateTime = (dateString) => {
  if (!dateString) return "N/A";

  try {
    const date = new Date(dateString);
    if (isNaN(date.getTime())) {
      const altDate = new Date(dateString.replace(/\.\d+Z$/, "Z"));
      if (!isNaN(altDate.getTime())) {
        return altDate.toLocaleString();
      }
      return "Invalid Date";
    }

    return date.toLocaleString();
  } catch (error) {
    console.error("Error formatting date:", error, dateString);
    return "Invalid Date";
  }
};

const formatTimeOnly = (dateString) => {
  if (!dateString) return "TBD";

  try {
    const date = new Date(dateString);
    if (isNaN(date.getTime())) {
      return "TBD";
    }
    return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", hour12: true });
  } catch (error) {
    console.error("Error formatting time:", error, dateString);
    return "TBD";
  }
};

const getExplorerForNetwork = (network) => {
  return {
    name: "WireFluid Scan",
    addressUrl: (address) => `https://wirefluidscan.com/address/${address}`,
    txUrl: (txHash) => `https://wirefluidscan.com/tx/${txHash}`,
  };
};

const TicketDetail = () => {
  const { artworkId } = useParams();
  const tokenId = artworkId; // Legacy alias for compatibility
  const navigate = useNavigate();
  const { account, isCorrectNetwork, selectedNetwork } = useWeb3();
  const { isAuthenticated, user } = useAuth();
  const [isLoading, setIsLoading] = useState(true);
  const [ticket, setTicket] = useState(null);
  const [activeTab, setActiveTab] = useState("details");
  const [blockchainInfo, setBlockchainInfo] = useState(null);
  useImageProtection(true, artworkId);

  // ✅ Get user identifier with fallback to JWT token (for better reliability)
  const getUserIdentifierWithFallback = () => {
    // Try UserIdentifier first
    const identifier = UserIdentifier.getUserIdentifier(user);
    if (identifier) {
      return identifier;
    }

    // ✅ Fallback: Extract from JWT token
    const token = localStorage.getItem('token') || sessionStorage.getItem('token');
    if (token) {
      try {
        const payload = JSON.parse(atob(token.split('.')[1]));
        const userIdFromToken = payload.userId || payload.user_id || payload.sub || payload.id;
        if (userIdFromToken) {
          console.log('✅ Using user ID from JWT token:', userIdFromToken);
          return String(userIdFromToken);
        }
      } catch (error) {
        console.error('Error decoding token:', error);
      }
    }

    return null;
  };

  const userIdentifier = getUserIdentifierWithFallback();
  // ✅ Use capability checks instead of user type
  const hasWallet = user ? UserIdentifier.hasWalletAddress(user) : false;
  const hasPayPal = user ? UserIdentifier.hasPaymentMethod(user, "paypal") : false;

  // drmfrontend/src/pages/ArtworkDetail.jsx - Line 108-208

  useEffect(() => {
    const fetchArtworkData = async () => {
      if (!artworkId) {
        setIsLoading(false);
        return;
      }

      setIsLoading(true);
      try {
        // ✅ Fetch both ticket and blockchain data
        const [artworkRes, blockchainRes] = await Promise.allSettled([
          ticketsAPI.getByTokenId(artworkId),
          ticketsAPI.getBlockchainInfo(artworkId),
        ]);

        let artworkData = null;
        let blockchainData = null;

        // Handle ticket data
        if (artworkRes.status === "fulfilled") {
          const artworkResponse = artworkRes.value;
          if (artworkResponse && artworkResponse.data) {
            artworkData = artworkResponse.data;
            setTicket(artworkData);

            // ✅ Log ticket ownership data for debugging
            console.log('📦 Ticket Data Loaded:', {
              token_id: artworkData.token_id,
              owner_id: artworkData.owner_id,
              creator_id: artworkData.creator_id,
              owner_address: artworkData.owner_address,
              payment_method: artworkData.payment_method,
              current_userIdentifier: userIdentifier
            });

            // ✅ Log view event to DRM analytics
            try {
              const token = localStorage.getItem("token") || sessionStorage.getItem("token") || "";
              const API_BASE = import.meta.env.VITE_BASE_URL_BACKEND || "http://localhost:8000/api/v1";
              fetch(`${API_BASE}/drm/usage/view/${artworkId}`, {
                method: 'POST',
                headers: token ? { Authorization: `Bearer ${token}` } : {}
              }).catch(e => console.error("Silent fail on view log:", e));
            } catch (e) {}
          } else {
            console.error("Invalid ticket response:", artworkResponse);
            setTicket(null);
          }
        } else {
          console.error("❌ Failed to fetch ticket:", artworkRes.reason);
          setTicket(null);
        }

        // Handle blockchain data
        if (blockchainRes.status === "fulfilled") {
          blockchainData = blockchainRes.value;
          console.log("✅ Blockchain data received:", blockchainData);

          // Validate blockchain data before setting
          if (
            blockchainData.error ||
            blockchainData.blockchain_status === "error"
          ) {
            console.warn("⚠️ Blockchain data has errors:", blockchainData.error);
            setBlockchainInfo(blockchainData);
          } else {
            setBlockchainInfo(blockchainData);
          }
        } else {
          console.warn("⚠️ Failed to fetch blockchain data:", blockchainRes.reason);
          // ✅ Create fallback blockchain data from ticket
          const fallbackBlockchainData = {
            token_id: parseInt(tokenId),
            owner: artworkData?.owner_address || artworkData?.owner_id || "Unknown",
            creator: artworkData?.creator_address || artworkData?.creator_id || "Unknown",
            royalty_percentage: artworkData?.royalty_percentage || 0,
            metadata_uri: artworkData?.metadata_uri || "",
            is_licensed: false,
            blockchain_status: "fallback",
            source: "database_fallback",
          };
          console.log("📦 Using fallback blockchain data:", fallbackBlockchainData);
          setBlockchainInfo(fallbackBlockchainData);
        }

      } catch (error) {
        console.error("Error fetching ticket:", error);
        toast.error("Failed to load ticket details");
        setTicket(null);
      } finally {
        setIsLoading(false);
      }
    };

    fetchArtworkData();
  }, [tokenId, userIdentifier]); // ✅ Re-fetch when userIdentifier changes // ✅ Re-fetch when userIdentifier changes (after login/purchase)

  const copyToClipboard = (text) => {
    if (!text) {
      toast.error("Nothing to copy");
      return;
    }
    navigator.clipboard.writeText(text);
    toast.success("Copied to clipboard");
  };

  const formatAddress = (address) => {
    if (!address) return "N/A";
    return `${address.substring(0, 8)}...${address.substring(address.length - 6)}`;
  };

  const explorerNetwork = (ticket?.network || blockchainInfo?.network || selectedNetwork || "wirefluid").toLowerCase();
  const explorer = getExplorerForNetwork(explorerNetwork);

  // ✅ Check if current user is owner (supports both crypto and PayPal users)
  // ✅ For crypto tickets: check owner_address
  // ✅ For PayPal tickets: check owner_id (NOT creator_id - after purchase, owner_id is updated)
  const isOwner = isAuthenticated && ticket && (() => {
    if (!userIdentifier && !account) {
      return false; // No user identifier available
    }

    // Crypto owner check
    const isCryptoOwner = account && ticket.owner_address &&
      account.toLowerCase() === ticket.owner_address.toLowerCase();

    // ✅ PayPal owner check (owner_id) - this is the current owner after purchase
    // ✅ Use multiple comparison methods to handle different ID formats
    let isPayPalOwner = false;
    if (userIdentifier && ticket.owner_id) {
      const userIdStr = String(userIdentifier).trim();
      const ownerIdStr = String(ticket.owner_id).trim();

      // Direct string comparison
      isPayPalOwner = userIdStr === ownerIdStr;

      // ✅ Also try ObjectId comparison (remove ObjectId wrapper if present)
      if (!isPayPalOwner) {
        const userIdClean = userIdStr.replace(/^ObjectId\(|\)$/g, '');
        const ownerIdClean = ownerIdStr.replace(/^ObjectId\(|\)$/g, '');
        isPayPalOwner = userIdClean === ownerIdClean;
      }

      // ✅ Also try comparing last 24 chars (MongoDB ObjectId length)
      if (!isPayPalOwner && userIdStr.length >= 24 && ownerIdStr.length >= 24) {
        isPayPalOwner = userIdStr.slice(-24) === ownerIdStr.slice(-24);
      }
    }

    // ✅ Only check creator_id if owner_id is not set (initial state before first sale)
    // After purchase, owner_id will be set to buyer's ID, so creator check should not apply
    let isPayPalCreator = false;
    if (!ticket.owner_id && userIdentifier && ticket.creator_id && ticket.payment_method === "paypal") {
      const userIdStr = String(userIdentifier).trim();
      const creatorIdStr = String(ticket.creator_id).trim();
      isPayPalCreator = userIdStr === creatorIdStr;

      if (!isPayPalCreator) {
        const userIdClean = userIdStr.replace(/^ObjectId\(|\)$/g, '');
        const creatorIdClean = creatorIdStr.replace(/^ObjectId\(|\)$/g, '');
        isPayPalCreator = userIdClean === creatorIdClean;
      }
    }

    const result = isCryptoOwner || isPayPalOwner || isPayPalCreator;

    // ✅ Enhanced debug logging
    if (ticket) {
      console.log("🔍 Owner Check Debug (TicketDetail):", {
        artwork_id: ticket.token_id,
        payment_method: ticket.payment_method,
        userIdentifier: userIdentifier || 'NULL',
        userIdentifier_type: typeof userIdentifier,
        artwork_owner_id: ticket.owner_id || 'NULL',
        artwork_owner_id_type: typeof ticket.owner_id,
        artwork_creator_id: ticket.creator_id || 'NULL',
        artwork_owner_address: ticket.owner_address || 'NULL',
        account: account || 'NULL',
        isCryptoOwner,
        isPayPalOwner,
        isPayPalCreator,
        isOwner: result,
        comparison_details: {
          userIdStr: userIdentifier ? String(userIdentifier).trim() : 'NULL',
          ownerIdStr: ticket.owner_id ? String(ticket.owner_id).trim() : 'NULL',
          direct_match: userIdentifier && ticket.owner_id ?
            String(userIdentifier).trim() === String(ticket.owner_id).trim() : false
        }
      });
    }

    return result;
  })();

  const isTicket = ticket?.is_psl_ticket === true;
  const pslMeta = ticket?.psl_metadata || {};
  const pslVenue = pslMeta.venue || "National Stadium, Karachi";
  const pslMatchDate = pslMeta.match_date || formatDate(ticket?.match_datetime);
  const pslMatchTime = pslMeta.match_time || formatTimeOnly(ticket?.match_datetime);
  const pslStand = ticket?.stand || pslMeta.stand || "TBD";
  const pslSeat = ticket?.seat_number || pslMeta.seat_number || pslMeta.seat || "TBD";
  const accentLinkClass = isTicket ? "text-emerald-600 hover:text-emerald-800" : "text-purple-600 hover:text-purple-800";
  const accentTabClass = isTicket ? "border-emerald-600 text-emerald-600" : "border-purple-600 text-purple-600";
  const itemLabel = isTicket ? "Ticket" : "Ticket";
  const itemLabelLower = isTicket ? "ticket" : "ticket";

  // Format price display based on user type
  const formatPrice = (price) => {
    if (!price && price !== 0) return 'Not set';

    if (hasPayPal && !hasWallet) {
      // PayPal users see USD
      const usdAmount = CurrencyConverter.ethToUsd(price);
      return CurrencyConverter.formatUsd(usdAmount);
    }

    // Crypto users see both
    const usdAmount = CurrencyConverter.ethToUsd(price);
    return (
      <div>
        <div className="text-2xl font-bold text-green-900">
          {CurrencyConverter.formatCrypto(price, ticket?.network)}
        </div>
        <div className="text-sm text-green-700 mt-1">
          ≈ {CurrencyConverter.formatUsd(usdAmount)}
        </div>
      </div>
    );
  };


  if (isLoading) {
    return (
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
        <div className="flex justify-center p-12">
          <LoadingSpinner size="large" />
        </div>
      </div>
    );
  }

  if (!ticket) {
    return (
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
        <div className="text-center bg-red-50 border border-red-200 rounded-lg p-8">
          <XCircle className="w-16 h-16 text-red-400 mx-auto mb-4" />
          <h2 className="text-2xl font-bold text-gray-900 mb-4">
            Item Not Found
          </h2>
          <p className="text-gray-600 mb-6">
            The item with ID {artworkId} could not be found.
          </p>
          <Link
            to="/explorer"
            className="inline-flex items-center px-4 py-2 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700"
          >
            <ArrowLeft className="w-5 h-5 mr-2" />
            Back to Explorer
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      {/* Navigation */}
      <div className="mb-6">
        <Link
          to="/explorer"
          className={`inline-flex items-center font-medium ${accentLinkClass}`}
        >
          <ArrowLeft className="w-5 h-5 mr-2" />
          Back to Explorer
        </Link>
      </div>

      <div className="bg-white rounded-xl shadow-lg overflow-hidden border border-gray-200">
        {/* Header Section */}
        <div className={`p-6 border-b border-gray-200 ${isTicket ? "bg-gradient-to-r from-emerald-50 to-green-50" : ""}`}>
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div>
              <h1 className="text-3xl font-bold text-gray-900">
                {ticket.title || `${itemLabel} #${ticket.token_id}`}
              </h1>
              <p className="text-gray-600 mt-2">
                {isTicket ? "Ticket ID" : "Token ID"}: #{ticket.token_id}
              </p>
              {isTicket && (
                <div className="mt-3 inline-flex items-center gap-2 bg-emerald-100 text-emerald-800 px-3 py-1 rounded-full text-sm font-medium border border-emerald-200">
                  PSL Smart-Ticket
                </div>
              )}
              {/* ✅ Registration Method Badge */}
              {ticket.payment_method && (
                <div className="mt-3">
                  {(() => {
                    const isOnChain = ArtworkStatus.isOnChainArtwork(ticket);
                    const label = ArtworkStatus.getRegistrationLabel(ticket);

                    return isOnChain ? (
                      <div className="inline-flex items-center gap-2 bg-blue-100 text-blue-800 px-3 py-1 rounded-full text-sm font-medium">
                        <Wallet className="w-4 h-4" />
                        <span>{label}</span>
                      </div>
                    ) : (
                      <div className="inline-flex items-center gap-2 bg-green-100 text-green-800 px-3 py-1 rounded-full text-sm font-medium">
                        <CreditCard className="w-4 h-4" />
                        <span>{label}</span>
                      </div>
                    );
                  })()}
                </div>
              )}
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <span
                className={`px-3 py-1 rounded-full text-sm font-medium ${ticket.is_licensed
                    ? "bg-green-100 text-green-800"
                    : "bg-gray-100 text-gray-800"
                  }`}
              >
                {ticket.is_licensed ? "Licensed" : isTicket ? "Available Ticket" : "Available for Purchase"}
              </span>
              {isOwner && (
                <span className={`px-3 py-1 rounded-full text-sm font-medium ${isTicket ? "bg-emerald-100 text-emerald-800" : "bg-blue-100 text-blue-800"}`}>
                  Your {itemLabel}
                </span>
              )}
              {ticket.payment_method && (
                <span className={`px-3 py-1 rounded-full text-sm font-medium flex items-center ${ticket.payment_method === 'paypal'
                    ? 'bg-yellow-100 text-yellow-800'
                    : 'bg-blue-100 text-blue-800'
                  }`}>
                  {ticket.payment_method === 'paypal' ? <CreditCard className="w-3 h-3 mr-1" /> : <Wallet className="w-3 h-3 mr-1" />}
                  {ticket.payment_method === 'paypal' ? 'PayPal' : 'Crypto'}
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Main Content */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 p-6">
          {/* Image Section */}
          <div className="lg:sticky lg:top-6 self-start">
            <div
              className="bg-gray-100 rounded-lg overflow-hidden aspect-square flex items-center justify-center relative image-container"
              style={{
                userSelect: 'none',
                WebkitUserSelect: 'none',
                MozUserSelect: 'none',
                msUserSelect: 'none',
                WebkitTouchCallout: 'none'
              }}
            >
              {(() => {
                const baseUrl = import.meta.env.VITE_BASE_URL_BACKEND || '';
                const cleanBaseUrl = baseUrl.endsWith('/') ? baseUrl.slice(0, -1) : baseUrl;
                const artworkIdForImage = ticket._id || ticket.id || ticket.token_id;
                const imageUrl = artworkIdForImage
                  ? `${cleanBaseUrl}/tickets/${artworkIdForImage}/image`
                  : null;

                return imageUrl ? (
                  <>
                    {/* DB Badge */}
                    <div className="absolute top-2 right-2 z-20">
                      <div className="bg-blue-500 text-white text-xs px-2 py-1 rounded-full flex items-center shadow-md">
                        <Database className="w-3 h-3 mr-1" />
                        DB
                      </div>
                    </div>

                    {/* Protected Canvas Image */}
                    <ProtectedImage
                      imageUrl={imageUrl}
                      alt={ticket.title || `${itemLabel} ${ticket.token_id}`}
                      className="w-full h-full"
                      aspectRatio="square"
                      showToast={true}
                      onError={() => {
                        const placeholder = document.querySelector('.image-placeholder');
                        if (placeholder) placeholder.style.display = 'flex';
                      }}
                    />

                    {/* Error placeholder */}
                    <div className="image-placeholder text-center absolute inset-0 flex flex-col items-center justify-center" style={{ display: 'none' }}>
                      <Palette className="w-12 h-12 text-gray-400 mx-auto mb-2" />
                      <p className="text-sm text-gray-500">Image unavailable</p>
                    </div>
                  </>
                ) : (
                  <div className="text-center">
                    <Palette className="w-12 h-12 text-gray-400 mx-auto mb-2" />
                    <p className="text-sm text-gray-500">No image available</p>
                  </div>
                );
              })()}
            </div>

            {/* Action Buttons */}
            {isAuthenticated && !isOwner && (
              <div className="mt-6 grid grid-cols-1 gap-3">
                <Link
                  to={`/sale/${ticket.token_id}`}
                  className={`flex items-center justify-center text-white py-3 px-4 rounded-lg text-center font-medium transition-colors ${isTicket ? "bg-emerald-600 hover:bg-emerald-700" : "bg-blue-600 hover:bg-blue-700"}`}
                >
                  <ShoppingCart className="w-4 h-4 mr-2" />
                  Purchase
                </Link>
              </div>
            )}
            {/* Download Button — hidden for tickets */}
            {isAuthenticated && !isTicket && (
              <div className="mt-3">
                <button
                  onClick={async () => {
                    try {
                      const token = localStorage.getItem('token') || sessionStorage.getItem('token');
                      if (!token) {
                        toast.error('Please login to download');
                        return;
                      }
                      // Step 1: Get download token
                      const artworkIdForDownload = ticket._id || ticket.id || ticket.token_id;
                      const tokenRes = await axios.post(
                        `${API_BASE}/drm/download/${artworkIdForDownload}/token`,
                        {},
                        { headers: { Authorization: `Bearer ${token}` } }
                      );
                      const data = tokenRes.data;
                      if (!data.success) {
                        toast.error(data.error || 'Cannot generate download link');
                        return;
                      }

                      // Step 2: Trigger download using signed token
                      const downloadUrl = `${API_BASE}/drm/download/${artworkIdForDownload}?token=${encodeURIComponent(data.download_token)}`;
                      const a = document.createElement('a');
                      a.href = downloadUrl;
                      a.download = `${ticket.title || 'ticket'}.jpg`;
                      document.body.appendChild(a);
                      a.click();
                      document.body.removeChild(a);

                      toast.success(
                        `Download started! ${data.downloads_remaining} downloads remaining this hour.`,
                        { duration: 3000, icon: '⬇️' }
                      );
                    } catch (err) {
                      const msg = err?.response?.data?.detail || 'Download failed';
                      toast.error(msg);
                    }
                  }}
                  className="w-full flex items-center justify-center bg-green-600 hover:bg-green-700 text-white py-3 px-4 rounded-lg font-medium transition-colors"
                >
                  ⬇️ Download {itemLabel}
                </button>
              </div>
            )}
            {isAuthenticated && isOwner && (
              <div className="mt-6">
                <div className={`${isTicket ? "bg-emerald-50 border-emerald-200" : "bg-blue-50 border-blue-200"} border rounded-lg p-4`}>
                  <div className="flex items-center">
                    <CheckCircle className={`w-5 h-5 mr-2 ${isTicket ? "text-emerald-600" : "text-blue-600"}`} />
                    <p className={`${isTicket ? "text-emerald-800" : "text-blue-800"} font-medium`}>
                      This is your {itemLabelLower}. You cannot purchase your own {itemLabelLower}.
                    </p>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* Details Section */}
          <div>
            {/* Tabs */}
            <div className="flex border-b border-gray-200 mb-6">
              <button
                className={`py-3 px-6 font-medium text-sm border-b-2 transition-colors ${activeTab === "details"
                    ? accentTabClass
                    : "border-transparent text-gray-500 hover:text-gray-700"
                  }`}
                onClick={() => setActiveTab("details")}
              >
                Details
              </button>
            </div>

            {/* Details Tab */}
            {activeTab === "details" && (
              <div className="space-y-6">
                {/* Description */}
                {ticket.description && (
                  <div>
                    <h3 className="text-lg font-semibold text-gray-900 mb-2">Description</h3>
                    <p className="text-gray-600 leading-relaxed">{ticket.description}</p>
                  </div>
                )}

                {isTicket && (
                  <div>
                    <h3 className="text-lg font-semibold text-gray-900 mb-3">PSL Match Details</h3>
                    <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-4">
                      <div className="grid grid-cols-2 gap-y-2 text-sm">
                        <span className="text-gray-600">Venue</span>
                        <span className="font-semibold text-gray-900 text-right">{pslVenue}</span>
                        <span className="text-gray-600">Date</span>
                        <span className="font-semibold text-gray-900 text-right">{pslMatchDate}</span>
                        <span className="text-gray-600">Time</span>
                        <span className="font-semibold text-gray-900 text-right">{pslMatchTime}</span>
                        <span className="text-gray-600">Stand</span>
                        <span className="font-semibold text-gray-900 text-right">{pslStand}</span>
                        <span className="text-gray-600">Seat</span>
                        <span className="font-semibold text-gray-900 text-right">{pslSeat}</span>
                      </div>
                    </div>
                  </div>
                )}

                {/* Price */}
                {ticket.price && (
                  <div>
                    <h3 className="text-lg font-semibold text-gray-900 mb-3 flex items-center">
                      <DollarSign className="w-5 h-5 mr-2 text-green-600" />
                      {itemLabel} Price
                    </h3>
                    <div className="bg-green-50 rounded-lg p-4">
                      {formatPrice(ticket.price)}
                    </div>
                  </div>
                )}

                {/* Creator Info */}
                <div>
                  <h3 className="text-lg font-semibold text-gray-900 mb-3 flex items-center">
                    <User className={`w-5 h-5 mr-2 ${isTicket ? "text-emerald-600" : "text-purple-600"}`} />
                    Creator Information
                  </h3>
                  <div className="bg-gray-50 rounded-lg p-4">
                    {/* ✅ For PayPal tickets, show name and email */}
                    {ticket.payment_method === "paypal" && (ticket.creator_name || ticket.creator_email) ? (
                      <>
                        {ticket.creator_name && (
                          <div className="mb-3">
                            <span className="text-sm text-gray-600">Name</span>
                            <p className="text-sm font-medium text-gray-900 mt-1">{ticket.creator_name}</p>
                          </div>
                        )}
                        {ticket.creator_email && (
                          <div className="mb-3">
                            <span className="text-sm text-gray-600">Email</span>
                            <div className="flex items-center justify-between mt-1">
                              <p className="text-sm text-gray-900">{ticket.creator_email}</p>
                              <button
                                onClick={() => copyToClipboard(ticket.creator_email)}
                                className="text-gray-400 hover:text-gray-600 transition-colors"
                                title="Copy email"
                              >
                                <Copy className="w-4 h-4" />
                              </button>
                            </div>
                          </div>
                        )}
                      </>
                    ) : (
                      <>
                        {/* For crypto tickets, show wallet address */}
                        <div className="flex justify-between items-center mb-2">
                          <span className="text-sm text-gray-600">
                            Wallet Address
                          </span>
                          {ticket.creator_address && (
                            <button
                              onClick={() => copyToClipboard(ticket.creator_address)}
                              className="text-gray-400 hover:text-gray-600 transition-colors"
                              title="Copy address"
                            >
                              <Copy className="w-4 h-4" />
                            </button>
                          )}
                        </div>
                        <p className="font-mono text-sm break-all text-gray-900">
                          {ticket.creator_address || "N/A"}
                        </p>
                        {ticket.creator_address && (
                          <a
                            href={explorer.addressUrl(ticket.creator_address)}
                            target="_blank"
                            rel="noopener noreferrer"
                            className={`inline-flex items-center text-sm mt-2 ${accentLinkClass}`}
                          >
                            View on {explorer.name}{" "}
                            <ExternalLink className="w-4 h-4 ml-1" />
                          </a>
                        )}
                      </>
                    )}
                  </div>
                </div>

                {/* Current Owner */}
                <div>
                  <h3 className="text-lg font-semibold text-gray-900 mb-3">
                    Current Owner
                  </h3>
                  <div className="bg-gray-50 rounded-lg p-4">
                    {/* ✅ For PayPal tickets, show name and email */}
                    {ticket.payment_method === "paypal" && (ticket.owner_name || ticket.owner_email) ? (
                      <>
                        {ticket.owner_name && (
                          <div className="mb-3">
                            <span className="text-sm text-gray-600">Name</span>
                            <p className="text-sm font-medium text-gray-900 mt-1">{ticket.owner_name}</p>
                          </div>
                        )}
                        {ticket.owner_email && (
                          <div className="mb-3">
                            <span className="text-sm text-gray-600">Email</span>
                            <div className="flex items-center justify-between mt-1">
                              <p className="text-sm text-gray-900">{ticket.owner_email}</p>
                              <button
                                onClick={() => copyToClipboard(ticket.owner_email)}
                                className="text-gray-400 hover:text-gray-600 transition-colors"
                                title="Copy email"
                              >
                                <Copy className="w-4 h-4" />
                              </button>
                            </div>
                          </div>
                        )}
                        {isOwner && (
                          <p className="text-sm text-blue-600 font-medium mt-2">
                            This is your {itemLabelLower}
                          </p>
                        )}
                      </>
                    ) : (
                      <>
                        {/* For crypto tickets, show wallet address */}
                        <div className="flex justify-between items-center mb-2">
                          <span className="text-sm text-gray-600">
                            Wallet Address
                          </span>
                          {ticket.owner_address && (
                            <button
                              onClick={() => copyToClipboard(ticket.owner_address)}
                              className="text-gray-400 hover:text-gray-600 transition-colors"
                              title="Copy address"
                            >
                              <Copy className="w-4 h-4" />
                            </button>
                          )}
                        </div>


                        <p className="font-mono text-sm break-all text-gray-900">
                          {(() => {
                            // ✅ Priority: database owner_address > blockchain owner > owner_id > fallback
                            if (ticket.owner_address) {
                              return ticket.owner_address;
                            } else if (blockchainInfo?.owner && blockchainInfo.owner !== "Unknown") {
                              return blockchainInfo.owner;
                            } else if (ticket.owner_id) {
                              return ticket.owner_id;
                            } else {
                              return "N/A";
                            }
                          })()}
                        </p>
                        {isOwner && (
                          <p className="text-sm text-blue-600 font-medium mt-2">
                            This is your {itemLabelLower}
                          </p>
                        )}
                        {ticket.owner_address && (
                          <a
                            href={explorer.addressUrl(ticket.owner_address)}
                            target="_blank"
                            rel="noopener noreferrer"
                            className={`inline-flex items-center text-sm mt-2 ${accentLinkClass}`}
                          >
                            View on {explorer.name}{" "}
                            <ExternalLink className="w-4 h-4 ml-1" />
                          </a>
                        )}
                      </>
                    )}
                  </div>
                </div>

                {/* Royalty Information */}
                {!isTicket && (
                  <div>
                    <h3 className="text-lg font-semibold text-gray-900 mb-3 flex items-center">
                      <DollarSign className="w-5 h-5 mr-2 text-green-600" />
                      Royalty Information
                    </h3>
                    <div className="bg-green-50 rounded-lg p-4">
                      <div className="flex justify-between items-center">
                        <span className="text-sm text-green-800">
                          Royalty Percentage
                        </span>
                        <span className="text-lg font-bold text-green-900">
                          {ticket.royalty_percentage
                            ? (ticket.royalty_percentage / 100).toFixed(2)
                            : 0}
                          %
                        </span>
                      </div>
                      <p className="text-sm text-green-700 mt-2">
                        The creator receives this percentage from every secondary
                        sale.
                      </p>
                    </div>
                  </div>
                )}

                {/* Categories */}
                {!isTicket && (ticket.medium_category || ticket.style_category || ticket.subject_category) && (
                  <div>
                    <h3 className="text-lg font-semibold text-gray-900 mb-3 flex items-center">
                      <Palette className="w-5 h-5 mr-2 text-emerald-600" />
                      Categories
                    </h3>
                    <div className="bg-gray-50 rounded-lg p-4">
                      <div className="flex flex-wrap gap-2">
                        {ticket.medium_category && (
                          <span className="px-3 py-1 bg-blue-100 text-blue-800 rounded-full text-sm font-medium">
                            🎨 {ticket.medium_category}
                          </span>
                        )}
                        {ticket.style_category && (
                          <span className="px-3 py-1 bg-emerald-100 text-emerald-800 rounded-full text-sm font-medium">
                            🖼 {ticket.style_category}
                          </span>
                        )}
                        {ticket.subject_category && (
                          <span className="px-3 py-1 bg-green-100 text-green-800 rounded-full text-sm font-medium">
                            🌍 {ticket.subject_category}
                          </span>
                        )}
                      </div>
                      {(ticket.other_medium || ticket.other_style || ticket.other_subject) && (
                        <div className="mt-3 pt-3 border-t border-gray-200">
                          <p className="text-xs text-gray-600 mb-2">Additional Details:</p>
                          {ticket.other_medium && (
                            <p className="text-sm text-gray-700">Medium: {ticket.other_medium}</p>
                          )}
                          {ticket.other_style && (
                            <p className="text-sm text-gray-700">Style: {ticket.other_style}</p>
                          )}
                          {ticket.other_subject && (
                            <p className="text-sm text-gray-700">Subject: {ticket.other_subject}</p>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {/* Metadata */}
                <div>
                  <h3 className="text-lg font-semibold text-gray-900 mb-3">
                    Metadata
                  </h3>
                  <div className="bg-gray-50 rounded-lg p-4">
                    <div className="flex justify-between items-center mb-2">
                      <span className="text-sm text-gray-600">IPFS URI</span>
                      {ticket.metadata_uri && (
                        <button
                          onClick={() => copyToClipboard(ticket.metadata_uri)}
                          className="text-gray-400 hover:text-gray-600 transition-colors"
                          title="Copy URI"
                        >
                          <Copy className="w-4 h-4" />
                        </button>
                      )}
                    </div>
                    <p className="font-mono text-sm break-all mb-4 text-gray-900">
                      {ticket.metadata_uri || "N/A"}
                    </p>
                    {ticket.metadata_uri?.includes("ipfs://") && (
                      <a
                        href={`https://ipfs.io/ipfs/${ticket.metadata_uri.replace("ipfs://", "")}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className={`inline-flex items-center text-sm ${accentLinkClass}`}
                      >
                        View on IPFS <ExternalLink className="w-4 h-4 ml-1" />
                      </a>
                    )}
                  </div>
                </div>

                {/* Dates */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <h3 className="text-lg font-semibold text-gray-900 mb-3 flex items-center">
                      <Clock className="w-5 h-5 mr-2 text-blue-600" />
                      Registration Date
                    </h3>
                    <div className="bg-blue-50 rounded-lg p-4">
                      <p className="text-sm text-blue-900">
                        {formatDate(ticket.created_at)}
                      </p>
                    </div>
                  </div>
                  <div>
                    <h3 className="text-lg font-semibold text-gray-900 mb-3 flex items-center">
                      <Clock className="w-5 h-5 mr-2 text-gray-600" />
                      Last Updated
                    </h3>
                    <div className="bg-gray-50 rounded-lg p-4">
                      <p className="text-sm text-gray-900">
                        {formatDate(ticket.updated_at)}
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            )}

          </div>
        </div>
      </div>
    </div>
  );
};

export default TicketDetail;