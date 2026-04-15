import React, { useState, useEffect } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useWeb3 } from "../context/Web3Context";
import { useAuth } from "../context/AuthContext";
import { ticketsAPI } from "../services/api";
import { cacheService } from "../services/cacheService";
import { UserIdentifier, CurrencyConverter, ArtworkStatus } from "../utils/currencyUtils";
import { useSettings } from "../context/SettingsContext";
import {
  ShoppingCart,
  ArrowLeft,
  AlertTriangle,
  CheckCircle,
  Wallet,
  CreditCard,
  Database,
  Palette,
} from "lucide-react";
import LoadingSpinner from "../components/common/LoadingSpinner";
import { Button } from "@mui/material";
import toast from "react-hot-toast";
import Web3 from "web3";
import axios from 'axios';
import { useImageProtection } from "../hooks/useImageProtection";
import ProtectedImage from "../components/common/ProtectedImage";

const SalePage = () => {
  const { artworkId } = useParams();
  const tokenId = artworkId; // Legacy alias for compatibility
  const navigate = useNavigate();
  const {
    account,
    isCorrectNetwork,
    sendTransaction,
    balance,
    web3,
    web3Utils,
    connectWallet,
    switchNetwork,
    selectedNetwork,
    currentNetworkConfig,
    currencySymbol,
    explorerUrl,
  } = useWeb3();
  const { isAuthenticated, user } = useAuth();
  const { enableCrypto } = useSettings();
  const enablePayPal = false;
  const [platformFeeRate, setPlatformFeeRate] = useState(0.05);

  // ✅ Add image protection hook
  useImageProtection(true);

  const [ticket, setTicket] = useState(null);
  const [blockchainInfo, setBlockchainInfo] = useState(null);
  const [loading, setLoading] = useState(true);
  const [purchasing, setPurchasing] = useState(false);
  const [error, setError] = useState(null);
  const [simulationResults, setSimulationResults] = useState(null);
  const [paymentMethod, setPaymentMethod] = useState("crypto");
  const isTicketItem = ticket?.is_psl_ticket === true;
  const itemNameLower = isTicketItem ? "ticket" : "ticket";
  const itemNameTitle = isTicketItem ? "Ticket" : "Ticket";

  // Get user identifier
  const userIdentifier = UserIdentifier.getUserIdentifier(user);
  const [gasEstimate, setGasEstimate] = useState(0); // Network-aware estimate is set below
  const [prepareResponseData, setPrepareResponseData] = useState(null); // Store prepare response

  useEffect(() => {
    setGasEstimate(0.01);
  }, []);

  // Fetch ticket data
  useEffect(() => {
    if (artworkId) {
      fetchArtworkData();
    }
  }, [artworkId]);

  // Fetch dynamic platform fee
  useEffect(() => {
    const fetchPlatformFee = async () => {
      try {
        const baseURL = import.meta.env.VITE_BASE_URL_BACKEND;

        // 👇 VERIFY THIS: Change '/settings/platform-fee' to your actual backend endpoint
        const response = await axios.get(`${baseURL}/ticket/settings/platform-fee`);

        // Handle different possible response structures
        // Assuming backend returns something like { "value": 2.5 } or { "fee": 2.5 }
        const feePercentage = response.data.value || response.data.fee || response.data.platform_fee;

        if (feePercentage !== undefined && !isNaN(feePercentage)) {
          // Convert percentage (e.g., 2.5) to decimal (0.025)
          setPlatformFeeRate(parseFloat(feePercentage) / 100);
          console.log(`Dynamic platform fee loaded: ${feePercentage}%`);
        } else {
          console.warn("Invalid fee format received, defaulting to 5%");
          setPlatformFeeRate(0.05);
        }

      } catch (error) {
        console.error("Failed to fetch platform fee, using default 5%", error);
        setPlatformFeeRate(0.05); // Safe Fallback
      }
    };

    fetchPlatformFee();
  }, []);

  // ✅ Set payment method based on ticket registration status and user capabilities
  useEffect(() => {
    if (ticket) {
      const isOnChain = ArtworkStatus.isOnChainArtwork(ticket);

      // ✅ Check if all payment methods are disabled
      if (!enableCrypto && !enablePayPal) {
        setError("All payment methods are currently disabled by the administrator. Please contact support or try again later.");
        return;
      }

      // ✅ RESTRICTION: On-chain tickets MUST use crypto (blockchain requirement)
      if (isOnChain) {
        if (!enableCrypto) {
          setError("Crypto payments are currently disabled by the administrator. This ticket requires crypto payment as it is registered on blockchain.");
          return;
        }
        setPaymentMethod("crypto");
      }
      // Off-chain purchasing is removed in crypto-only mode.
      else {
        setPaymentMethod("crypto");
        setError("Off-chain payment is no longer supported. Only on-chain crypto purchases are available.");
      }
    }
  }, [ticket, account, user, enableCrypto, enablePayPal]);

  // Calculate simulation whenever ticket data changes
  useEffect(() => {
    if (ticket && blockchainInfo) {
      calculateSaleSimulation();
    }
  }, [ticket, blockchainInfo, paymentMethod, platformFeeRate]);

  // ✅ Check if current user is the owner (for both crypto and PayPal tickets)
  useEffect(() => {
    if (!loading && ticket) {
      // ✅ Check for crypto tickets (owner_address)
      const isCryptoOwner =
        account &&
        ticket.owner_address &&
        account.toLowerCase() === ticket.owner_address.toLowerCase();

      // ✅ Check for PayPal tickets (owner_id) - use trimmed string comparison
      const isPayPalOwner =
        userIdentifier &&
        ticket.owner_id &&
        String(userIdentifier).trim() === String(ticket.owner_id).trim();

      // ✅ Also check blockchainInfo for crypto tickets (if available)
      const isBlockchainOwner =
        blockchainInfo &&
        blockchainInfo.owner &&
        blockchainInfo.owner !== "Unknown" &&
        blockchainInfo.owner !== "0x0000000000000000000000000000000000000000" &&
        account &&
        account.toLowerCase() === blockchainInfo.owner.toLowerCase();

      if (isAuthenticated && (isCryptoOwner || isPayPalOwner || isBlockchainOwner)) {
        console.log(`✅ User is the owner, redirecting to ${itemNameLower} detail page`);
        toast(`This is your ${itemNameLower}. You cannot purchase your own ${itemNameLower}.`);
        navigate(`/ticket/${artworkId}`);
      }
    }
  }, [
    account,
    userIdentifier,
    blockchainInfo,
    loading,
    artworkId,
    navigate,
    ticket,
  ]);

  const fetchArtworkData = async () => {
    setLoading(true);
    setError(null);

    try {
      console.log("🔄 Fetching ticket data for token:", artworkId);

      const [artworkRes, blockchainRes] = await Promise.allSettled([
        ticketsAPI.getById(artworkId),
        ticketsAPI.getBlockchainInfo(artworkId),
      ]);

      let artworkData = null;
      let blockchainData = null;

      if (artworkRes.status === "fulfilled") {
        artworkData = artworkRes.value;
        console.log("✅ Ticket data received:", {
          token_id: artworkData?.token_id,
          title: artworkData?.title,
          price: artworkData?.price,
          owner_address: artworkData?.owner_address,
          owner_id: artworkData?.owner_id,
          creator_address: artworkData?.creator_address,
          creator_id: artworkData?.creator_id,
          payment_method: artworkData?.payment_method,
          is_for_sale: artworkData?.is_for_sale,
          full_data: artworkData
        });

        // ✅ Validate that we have essential data
        if (!artworkData) {
          throw new Error("Ticket data is null or undefined");
        }

        if (!artworkData.token_id && !artworkData.title) {
          console.warn("⚠️ Ticket data missing essential fields:", artworkData);
        }

        setTicket(artworkData);
      } else {
        console.error("❌ Failed to fetch ticket:", artworkRes.reason);
        console.error("Error details:", {
          message: artworkRes.reason?.message,
          response: artworkRes.reason?.response?.data,
          status: artworkRes.reason?.response?.status
        });
        throw new Error(artworkRes.reason?.message || "Failed to fetch ticket data");
      }

      if (blockchainRes.status === "fulfilled") {
        blockchainData = blockchainRes.value;
        console.log("✅ Blockchain data received:", blockchainData);

        // Validate blockchain data before setting
        if (
          blockchainData.error ||
          blockchainData.blockchain_status === "error"
        ) {
          console.warn("⚠️ Blockchain data has errors:", blockchainData.error);
          // Still set it but with warning
          setBlockchainInfo(blockchainData);
        } else {
          setBlockchainInfo(blockchainData);
        }
      } else {
        console.warn("⚠️ Failed to fetch blockchain data:", blockchainRes.reason);
        // Create fallback blockchain data from ticket
        const fallbackBlockchainData = {
          token_id: artworkData?.token_id,
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
    } catch (err) {
      console.error("❌ Error in fetchArtworkData:", err);
      setError(err.message);
      toast.error(`Failed to load ticket details: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const calculateSaleSimulation = () => {
    // Validate inputs first
    if (!ticket || !blockchainInfo) {
      console.warn("Missing ticket or blockchain data for simulation");
      return;
    }

    // Use ticket price instead of user input
    const price = ticket.price || 0;

    if (price <= 0) {
      console.warn("Ticket price is not set or invalid");
      return;
    }

    //const platformFeeRate = 0.05; // 5% platform fee

    // Handle missing royalty_percentage
    const royaltyRate = (blockchainInfo.royalty_percentage || 0) / 10000;

    // ✅ Handle missing owner/creator addresses (for PayPal tickets)
    const creatorAddress = ticket.creator_address || ticket.creator_id || "unknown";
    const ownerAddress = blockchainInfo.owner || ticket.owner_id || "unknown";

    // ✅ Safe comparison (handle null/undefined)
    const isPrimarySale = creatorAddress && ownerAddress &&
      creatorAddress.toLowerCase() === ownerAddress.toLowerCase();

    //✅ DUAL PLATFORM FEE SYSTEM (same as on-chain)
    const buyerPlatformFee = price * platformFeeRate;
    const sellerPlatformFee = price * platformFeeRate;

    // ✅ Buyer pays: Sale Price + Buyer Platform Fee
    const buyerTotal = price + buyerPlatformFee;

    let royaltyAmount = 0;
    let sellerReceives = 0;
    let creatorRoyalty = 0;

    if (isPrimarySale) {
      sellerReceives = price - sellerPlatformFee;
      royaltyAmount = 0;
    } else {
      royaltyAmount = price * royaltyRate;
      creatorRoyalty = royaltyAmount;
      sellerReceives = price - sellerPlatformFee - royaltyAmount;
    }

    setSimulationResults({
      salePrice: price,
      buyerPlatformFee: buyerPlatformFee,
      sellerPlatformFee: sellerPlatformFee,
      buyerTotal: buyerTotal,
      royaltyAmount: royaltyAmount,
      creatorRoyalty: creatorRoyalty,
      sellerReceives: sellerReceives,
      isPrimarySale,
      royaltyRate: (royaltyRate * 100).toFixed(2),
      isValid: true,
    });
  };

  // const handlePurchase = async () => {
  //   if (!isAuthenticated) {
  //     toast.error("Please log in to purchase");
  //     return;
  //   }

  //   // Enhanced wallet connection check for crypto payments
  //   if (paymentMethod === "crypto") {
  //     if (!account) {
  //       toast.error("Please connect your wallet");
  //       const connected = await connectWallet();
  //       if (!connected) return;
  //     }

  //     if (!isCorrectNetwork) {
  //       if (!switched) return;
  //     }

  //     // ✅ COMPREHENSIVE WEB3 CHECK
  //     if (!web3 || !web3.utils) {
  //       console.error("Web3 not available:", {
  //         web3: !!web3,
  //         utils: web3?.utils,
  //       });
  //       toast.error("Web3 not available. Reconnecting wallet...");

  //       // Try to reconnect
  //       const reconnected = await connectWallet();
  //       if (!reconnected) {
  //         toast.error("Failed to initialize Web3. Please refresh the page.");
  //         return;
  //       }

  //       // Check again after reconnection
  //       if (!web3 || !web3.utils) {
  //         toast.error("Web3 still not available. Please refresh the page.");
  //         return;
  //       }
  //     }
  //   }

  //   // Validate blockchain data before purchase
  //   if (
  //     !blockchainInfo ||
  //     !blockchainInfo.owner ||
  //     blockchainInfo.owner === "Unknown"
  //   ) {
  //     toast.error("Cannot process purchase: Invalid owner information");
  //     return;
  //   }

  //   // Use ticket price
  //   const price = ticket.price;

  //   if (price <= 0 || isNaN(price)) {
  //     toast.error("Ticket price is not set or invalid");
  //     return;
  //   }

  //   // For crypto, check balance
  //   if (paymentMethod === "crypto") {
  //     const balanceEth = parseFloat(balance);
  //     const requiredBalance = price + 0.01; // Include gas estimate

  //     if (balanceEth < requiredBalance) {
  //       toast.error(
  //         `Insufficient balance. Need ${requiredBalance.toFixed(
  //           4
  //         )} ETH, have ${balanceEth} ETH`
  //       );
  //       return;
  //     }
  //   }

  //   setPurchasing(true);
  //   setError(null);

  //   try {
  //     console.log("🔄 Proceeding with purchase...");
  //     console.log("Web3 status:", {
  //       web3: !!web3,
  //       utils: web3?.utils,
  //       account,
  //       paymentMethod,
  //     });

  //     // ✅ SAFE PRICE CONVERSION WITH MULTIPLE FALLBACKS
  //     let salePriceWei;

  //     // Method 1: Use web3 from context (preferred)
  //     if (web3 && web3.utils) {
  //       console.log("Using Web3 from context for price conversion");
  //       salePriceWei = web3.utils.toWei(price.toString(), "ether");
  //     }
  //     // Method 2: Use web3Utils from context
  //     else if (web3Utils) {
  //       console.log("Using web3Utils for price conversion");
  //       salePriceWei = web3Utils.toWei(price.toString(), "ether");
  //     }
  //     // Method 3: Use ethers.js
  //     else if (typeof ethers !== "undefined") {
  //       console.log("Using ethers.js for price conversion");
  //       salePriceWei = ethers.parseEther(price.toString()).toString();
  //     }
  //     // Method 4: Manual calculation (fallback)
  //     else {
  //       console.log("Using manual calculation for price conversion");
  //       salePriceWei = (price * 1e18).toString();
  //     }

  //     console.log("💰 Price conversion:", {
  //       eth: price,
  //       wei: salePriceWei,
  //       method: "web3 context",
  //     });

  //     // ✅ FIXED: Send proper request body with correct field names
  //     const prepareResponse = await artworksAPI.prepareSaleTransaction({
  //       token_id: parseInt(tokenId),
  //       buyer_address: account || userIdentifier,
  //       seller_address: blockchainInfo.owner,
  //       sale_price_wei: salePriceWei, // ✅ Send wei value, not ETH
  //     });

  //     console.log("✅ Sale preparation response:", prepareResponse);



  //     // ✅ FIXED: Better response validation
  //     if (!prepareResponse || typeof prepareResponse !== 'object') {
  //       throw new Error("Invalid response from server");

  //     }
  //     // Check if it's a PayPal response
  //     if (prepareResponse.payment_method === "paypal" || prepareResponse.type === "paypal") {
  //       const approvalUrl = prepareResponse.transaction_data?.approval_url || prepareResponse.approval_url;
  //       if (approvalUrl) {
  //         window.location.href = approvalUrl;
  //         return;
  //       }
  //     }
  //     // ✅ FIXED: Handle different response structures
  //     const transactionData =
  //       prepareResponse.transaction_data || prepareResponse;

  //     // Validate required fields for MetaMask
  //     if (!transactionData.to || !transactionData.value) {
  //       console.error("Missing transaction data:", transactionData);
  //       throw new Error("Blockchain transaction required but not provided");
  //     }

  //     const requiresBlockchain = prepareResponse.requires_blockchain !== false;
  //     const mode = prepareResponse.mode || "REAL";

  //     // // Handle PayPal response
  //     // if (prepareResponse.payment_method === "paypal") {
  //     //   window.location.href = prepareResponse.transaction_data.approval_url;
  //     //   return;
  //     // }

  //     // ✅ FIXED: Handle MetaMask flow with proper transaction data
  //     if (
  //       (prepareResponse.payment_method === "crypto" ||
  //         paymentMethod === "crypto") &&
  //       requiresBlockchain
  //     ) {
  //       // Prepare transaction parameters for MetaMask
  //       const txParams = {
  //         to: transactionData.to,
  //         data: transactionData.data,
  //         from: account,
  //         value: transactionData.value, // This should already be in wei hex format
  //       };

  //       // Add gas settings
  //       if (
  //         transactionData.maxFeePerGas &&
  //         transactionData.maxPriorityFeePerGas
  //       ) {
  //         txParams.maxFeePerGas = transactionData.maxFeePerGas;
  //         txParams.maxPriorityFeePerGas = transactionData.maxPriorityFeePerGas;
  //       } else if (transactionData.gasPrice) {
  //         txParams.gasPrice = transactionData.gasPrice;
  //       }

  //       // Add gas limit if provided
  //       if (transactionData.gas) {
  //         txParams.gasLimit = transactionData.gas;
  //       }

  //       // Add chain ID if provided
  //       if (transactionData.chainId) {
  //         txParams.chainId = parseInt(transactionData.chainId, 16);
  //       }

  //       console.log("🦊 Sending transaction to MetaMask:", txParams);

  //       // ✅ This WILL trigger MetaMask popup
  //       const result = await sendTransaction(txParams);

  //       if (!result || !result.hash) {
  //         throw new Error("No transaction hash received from MetaMask");
  //       }

  //       toast.success(
  //         "Purchase transaction submitted! Waiting for confirmation..."
  //       );
  //       console.log("📝 Transaction hash:", result.hash);

  //       try {
  //         // ✅ NEW: Confirm the transaction with backend
  //         const confirmToast = toast.loading(
  //           "Confirming transaction on blockchain..."
  //         );

  //         // ✅ FIXED: Send proper confirmation data
  //         await artworksAPI.confirmSale({
  //           tx_hash: result.hash,
  //           token_id: parseInt(tokenId),
  //           buyer_address: account,
  //           seller_address: blockchainInfo.owner,
  //           sale_price_wei: salePriceWei, // Use the wei value we calculated
  //           sale_price_eth: price, // Original ETH price for display
  //           payment_method: paymentMethod,
  //         });

  //         toast.dismiss(confirmToast);
  //         toast.success(
  //           "✅ Purchase completed successfully! Transaction confirmed on blockchain."
  //         );

  //         // Refresh data to show new owner
  //         await fetchArtworkData();

  //         setTimeout(() => {
  //           navigate(`/ticket/${tokenId}`);
  //         }, 2000);
  //       } catch (confirmationError) {
  //         console.error("Sale confirmation failed:", confirmationError);
  //         // Even if confirmation fails, the transaction might still succeed
  //         toast.success(
  //           "✅ Transaction submitted! Please check your collection in a few moments."
  //         );

  //         setTimeout(() => {
  //           navigate(`/ticket/${tokenId}`);
  //         }, 2000);
  //       }
  //     } else {
  //       throw new Error(
  //         "Invalid response: Blockchain transaction required but not provided"
  //       );
  //     }
  //   } catch (error) {
  //     console.error("❌ Purchase failed:", error);

  //     // ✅ IMPROVED: Better error handling
  //     if (error.code === 4001) {
  //       setError("Transaction cancelled by user in MetaMask");
  //       toast.error("Transaction cancelled by user");
  //     } else if (error.code === -32603) {
  //       setError(
  //         "Transaction failed. Please check your gas settings and try again."
  //       );
  //       toast.error("Transaction failed. Check gas settings.");
  //     } else if (error.message?.includes("insufficient funds")) {
  //       setError("Insufficient funds. Please add ETH to your wallet.");
  //       toast.error("Insufficient funds. Add ETH to your wallet.");
  //     } else if (
  //       error.message?.includes("user rejected") ||
  //       error.message?.includes("denied")
  //     ) {
  //       setError("Transaction rejected by user in MetaMask.");
  //       toast.error("Transaction rejected by user");
  //     } else if (error.message?.includes("demo mode")) {
  //       setError(
  //         "Blockchain service is in demo mode. Real transactions are disabled."
  //       );
  //       toast.error("Blockchain service is in demo mode.");
  //     } else if (error.message?.includes("not connected")) {
  //       setError(
  //         "Blockchain connection issue detected, but proceeding with purchase..."
  //       );
  //       toast.success("Proceeding with purchase despite connection warning...");
  //       // Retry the purchase without health check
  //       setTimeout(() => handlePurchase(), 1000);
  //       return;
  //     } else if (error.response?.status === 422) {
  //       // ✅ FIXED: Handle 422 errors specifically
  //       const errorDetail = error.response?.data?.detail;
  //       if (Array.isArray(errorDetail)) {
  //         // Handle validation errors
  //         const fieldErrors = errorDetail
  //           .map((err) => `${err.loc.join(".")}: ${err.msg}`)
  //           .join(", ");
  //         setError(`Validation error: ${fieldErrors}`);
  //         toast.error("Validation error. Please check your input.");
  //       } else if (typeof errorDetail === "string") {
  //         setError(errorDetail);
  //         toast.error(errorDetail);
  //       } else {
  //         setError(
  //           "Invalid request format. Please check your input and try again."
  //         );
  //         toast.error("Invalid request format.");
  //       }
  //     } else if (error.response?.status === 400) {
  //       setError(
  //         error.response?.data?.detail ||
  //         "Bad request. Please check your input."
  //       );
  //       toast.error(error.response?.data?.detail || "Bad request.");
  //     } else if (error.response?.status === 500) {
  //       setError("Server error. Please try again later.");
  //       toast.error("Server error. Please try again later.");
  //     } else {
  //       const errorMessage =
  //         error.response?.data?.detail ||
  //         error.response?.data?.error ||
  //         error.message ||
  //         "Purchase failed. Please try again.";
  //       setError(errorMessage);
  //       toast.error(errorMessage || "Purchase failed");
  //     }
  //   } finally {
  //     setPurchasing(false);
  //   }
  // };

  const handlePurchase = async () => {
    if (!isAuthenticated) {
      toast.error(`Please log in to purchase this ${itemNameLower}`);
      return;
    }
    // ✅ STEP 1: CHECK PAYMENT METHOD FIRST
    // PayPal flow removed.
    if (paymentMethod === "paypal") {
      setError("PayPal payments are no longer supported. Please use crypto payment.");
      toast.error("PayPal payments are no longer supported.");
      return;
    }

    // Enhanced wallet connection check for crypto payments
    if (paymentMethod === "crypto") {
      if (!account) {
        toast.error("Please connect your wallet to proceed with the purchase");
        setError(`Wallet not connected. Please connect your wallet to purchase this ${itemNameLower}.`);
        const connected = await connectWallet();
        if (!connected) return;
      }

      const artworkNetwork = (ticket?.network || "wirefluid").toLowerCase();
      const activeNetwork = (selectedNetwork || "").toLowerCase();
      if (activeNetwork !== artworkNetwork) {
        toast.error(`Please switch to ${artworkNetwork} to proceed with the purchase`);
        setError(`Wrong network. Please switch to ${artworkNetwork} to purchase ${itemNameLower}s.`);
        const switched = await switchNetwork(artworkNetwork);
        if (!switched) {
          setError(`Please switch to ${artworkNetwork} to make purchases.`);
          return;
        }
        // Clear error if network switch successful
        setError(null);
      }

      // ✅ COMPREHENSIVE WEB3 CHECK
      if (!web3 || !web3.utils) {
        console.error("Web3 not available:", {
          web3: !!web3,
          utils: web3?.utils,
        });
        toast.error("Web3 not available. Reconnecting wallet...");

        // Try to reconnect
        const reconnected = await connectWallet();
        if (!reconnected) {
          toast.error("Failed to initialize Web3. Please refresh the page.");
          return;
        }

        // Check again after reconnection
        if (!web3 || !web3.utils) {
          toast.error("Web3 still not available. Please refresh the page.");
          return;
        }
      }
    }

    // ✅ Validate ticket data before purchase (NEW: On-chain/Off-chain)
    const isOnChain = ArtworkStatus.isOnChainArtwork(ticket);

    if (isOnChain) {
      // On-chain tickets: MUST use crypto and check blockchain owner
      if (paymentMethod !== "crypto") {
        toast.error(`On-chain ${itemNameLower}s can only be purchased with crypto`);
        return;
      }
      if (
        !blockchainInfo ||
        !blockchainInfo.owner ||
        blockchainInfo.owner === "Unknown"
      ) {
        toast.error("Cannot process purchase: Invalid blockchain owner information");
        return;
      }
    } else {
      // Off-chain tickets: Can ONLY use off-chain payment methods (PayPal, etc.)
      // Crypto payment is NOT allowed for off-chain tickets
      if (paymentMethod === "crypto") {
        toast.error(`Off-chain ${itemNameLower}s can only be purchased with off-chain payment methods (PayPal, etc.)`);
        return;
      } else if (paymentMethod === "paypal") {
        // PayPal payment: check owner_id
        if (!ticket || !ticket.owner_id) {
          toast.error("Cannot process purchase: Invalid owner information");
          return;
        }
      } else {
        // Other off-chain payment methods
        if (!ticket || !ticket.owner_id) {
          toast.error("Cannot process purchase: Invalid owner information");
          return;
        }
      }
    }

    // Use listed sale price
    const price = ticket.price;

    if (price <= 0 || isNaN(price)) {
      toast.error(`${itemNameTitle} price is not set or invalid`);
      return;
    }

    // For crypto, check balance
    if (paymentMethod === "crypto") {
      const balanceEth = parseFloat(balance);
      const fallbackEstimate = 0.01;
      const effectiveGasEstimate = Number(gasEstimate) > 0 ? Number(gasEstimate) : fallbackEstimate;
      const requiredBalance = price + effectiveGasEstimate;

      if (balanceEth < requiredBalance) {
        const symbol = CurrencyConverter.getSymbol(ticket?.network);
        toast.error(
          `Insufficient balance. Need ${requiredBalance.toFixed(
            4
          )} ${symbol}, have ${balanceEth} ${symbol}`
        );
        return;
      }
    }

    setPurchasing(true);
    setError(null);

    try {
      console.log("🔄 Proceeding with purchase...");
      console.log("Web3 status:", {
        web3: !!web3,
        utils: web3?.utils,
        account,
        paymentMethod,
      });

      // ✅ SAFE PRICE CONVERSION
      let salePriceWei;

      // Method 1: Use web3 from context (preferred)
      if (web3 && web3.utils) {
        console.log("Using Web3 from context for price conversion");
        salePriceWei = web3.utils.toWei(price.toString(), "ether");
      }
      // Method 2: Use web3Utils from context
      else if (web3Utils) {
        console.log("Using web3Utils for price conversion");
        salePriceWei = web3Utils.toWei(price.toString(), "ether");
      }
      // Method 3: Use ethers.js
      else if (typeof ethers !== "undefined") {
        console.log("Using ethers.js for price conversion");
        salePriceWei = ethers.parseEther(price.toString()).toString();
      }
      // Method 4: Manual calculation (fallback)
      else {
        console.log("Using manual calculation for price conversion");
        salePriceWei = (price * 1e18).toString();
      }

      console.log("💰 Price conversion:", {
        eth: price,
        base_units: salePriceWei,
        method: "wei",
      });

      // ✅ FIXED: Send proper request body with correct field names
      const prepareResponse = await ticketsAPI.prepareSaleTransaction({
        token_id: ticket?.token_id || tokenId,
        artwork_id: artworkId,
        buyer_address: account || userIdentifier,
        seller_address: blockchainInfo.owner,
        sale_price_wei: salePriceWei, // ✅ Send wei value, not ETH
        payment_method: paymentMethod,
        sale_price_eth: price,
      });

      // ✅ Store prepare response and gas estimate
      setPrepareResponseData(prepareResponse);

      console.log("✅ Sale preparation response:", prepareResponse);

      // ✅ FIXED: Better response validation
      if (!prepareResponse || typeof prepareResponse !== 'object') {
        throw new Error("Invalid response from server");
      }

      // ✅ NEW FIX: Check if response has transaction fields directly at root level
      let transactionData;
      if (prepareResponse.to && prepareResponse.value) {
        // Response IS the transaction data
        transactionData = prepareResponse;
        console.log("✅ Using root-level transaction data");
      } else if (prepareResponse.transaction_data) {
        // Response has nested transaction_data
        transactionData = prepareResponse.transaction_data;
        console.log("✅ Using nested transaction_data");
      } else {
        // No valid transaction data found
        console.error("Missing transaction data:", prepareResponse);
        throw new Error("Blockchain transaction required but not provided");
      }

      // Validate required fields for MetaMask
      if (!transactionData.to || !transactionData.value) {
        console.error("Missing required fields:", transactionData);
        throw new Error("Blockchain transaction required but not provided");
      }

      if (prepareResponse?.gas_estimate_eth) {
        setGasEstimate(prepareResponse.gas_estimate_eth);
        console.log(`💰 Gas estimate from backend: ${prepareResponse.gas_estimate_eth} ETH`);
      }

      const requiresBlockchain = prepareResponse.requires_blockchain !== false;
      const mode = prepareResponse.mode || "REAL";

      // ✅ FIXED: Handle MetaMask flow with proper transaction data
      if (
        (prepareResponse.payment_method === "crypto" ||
          paymentMethod === "crypto") &&
        requiresBlockchain
      ) {
        let result;
        // Prepare transaction parameters for MetaMask
        const txParams = {
          to: transactionData.to,
          data: transactionData.data,
          from: account,
          value: transactionData.value, // This should already be in wei hex format
        };

        // Add gas settings
        if (
          transactionData.maxFeePerGas &&
          transactionData.maxPriorityFeePerGas
        ) {
          txParams.maxFeePerGas = transactionData.maxFeePerGas;
          txParams.maxPriorityFeePerGas = transactionData.maxPriorityFeePerGas;
        } else if (transactionData.gasPrice) {
          txParams.gasPrice = transactionData.gasPrice;
        }

        // Add gas limit if provided
        if (transactionData.gas) {
          txParams.gasLimit = transactionData.gas;
        }

        // Add chain ID if provided
        if (transactionData.chainId) {
          txParams.chainId = parseInt(transactionData.chainId, 16);
        }

        console.log("🦊 Sending transaction to MetaMask:", txParams);
        result = await sendTransaction(txParams);

        if (!result || !result.hash) {
          throw new Error("No transaction hash received from wallet");
        }

        toast.success(
          "Purchase transaction submitted! Waiting for confirmation..."
        );
        console.log("📝 Transaction hash:", result.hash);

        try {
          // ✅ NEW: Confirm the transaction with backend
          const confirmToast = toast.loading(
            "Confirming transaction on blockchain..."
          );

          // ✅ FIXED: Send proper confirmation data
          await ticketsAPI.confirmSale({
            tx_hash: result.hash,
            token_id: ticket?.token_id || tokenId,
            artwork_id: artworkId,
            buyer_address: account,
            seller_address: blockchainInfo.owner,
            sale_price_wei: salePriceWei, // Use the wei value we calculated
            sale_price_eth: price, // Original ETH price for display
            payment_method: paymentMethod,
          });

          toast.dismiss(confirmToast);
          toast.success(
            "✅ Purchase completed successfully! Transaction confirmed on blockchain."
          );
          
          // ✅ NEW: Invalidate all caches after successful purchase
          cacheService.invalidateAll();

          // Refresh data to show new owner
          await fetchArtworkData();

          setTimeout(() => {
            navigate(`/ticket/${artworkId}`);
          }, 2000);
        } catch (confirmationError) {
          console.error("Sale confirmation failed:", confirmationError);
          const backendDetail =
            confirmationError?.response?.data?.detail ||
            confirmationError?.message ||
            "Sale confirmation failed on backend";

          setError(`Transaction submitted but confirmation failed: ${backendDetail}`);
          toast.error(`Confirmation failed: ${backendDetail}`);
          return;
        }
      } else {
        throw new Error(
          "Invalid response: Blockchain transaction required but not provided"
        );
      }
    } catch (error) {
      console.error("❌ Purchase failed:", error);

      // ✅ IMPROVED: Better error handling
      if (error.code === 4001) {
        setError("Transaction cancelled by user in wallet");
        toast.error("Transaction cancelled by user");
      } else if (error.code === -32603) {
        setError(
          "Transaction failed. Please check your gas settings and try again."
        );
        toast.error("Transaction failed. Check gas settings.");
      } else if (error.message?.includes("insufficient funds")) {
        setError("Insufficient funds. Please add funds to your wallet.");
        toast.error("Insufficient funds. Add funds to your wallet.");
      } else if (
        error.message?.includes("user rejected") ||
        error.message?.includes("denied")
      ) {
        setError("Transaction rejected by user in wallet.");
        toast.error("Transaction rejected by user");
      } else if (error.message?.includes("demo mode")) {
        setError(
          "Blockchain service is in demo mode. Real transactions are disabled."
        );
        toast.error("Blockchain service is in demo mode.");
      } else if (error.message?.includes("not connected")) {
        setError(
          "Blockchain connection issue detected, but proceeding with purchase..."
        );
        toast.success("Proceeding with purchase despite connection warning...");
        // Retry the purchase without health check
        setTimeout(() => handlePurchase(), 1000);
        return;
      } else if (error.response?.status === 422) {
        // ✅ FIXED: Handle 422 errors specifically
        const errorDetail = error.response?.data?.detail;
        if (Array.isArray(errorDetail)) {
          // Handle validation errors
          const fieldErrors = errorDetail
            .map((err) => `${err.loc.join(".")}: ${err.msg}`)
            .join(", ");
          setError(`Validation error: ${fieldErrors}`);
          toast.error("Validation error. Please check your input.");
        } else if (typeof errorDetail === "string") {
          setError(errorDetail);
          toast.error(errorDetail);
        } else {
          setError(
            "Invalid request format. Please check your input and try again."
          );
          toast.error("Invalid request format.");
        }
      } else if (error.response?.status === 400) {
        setError(
          error.response?.data?.detail ||
          "Bad request. Please check your input."
        );
        toast.error(error.response?.data?.detail || "Bad request.");
      } else if (error.response?.status === 500) {
        setError("Server error. Please try again later.");
        toast.error("Server error. Please try again later.");
      } else {
        const errorMessage =
          error.response?.data?.detail ||
          error.response?.data?.error ||
          error.message ||
          "Purchase failed. Please try again.";
        setError(errorMessage);
        toast.error(errorMessage || "Purchase failed");
      }
    } finally {
      setPurchasing(false);
    }
  };

  const formatAddress = (address) => {
    if (!address) return "Unknown";
    return `${address.substring(0, 6)}...${address.substring(
      address.length - 4
    )}`;
  };

  // Format price display based on payment method
  const formatPrice = (amount) => {
    if (!amount || isNaN(amount)) return "N/A";

    if (paymentMethod === "paypal") {
      const usdAmount = CurrencyConverter.ethToUsd(amount);
      return CurrencyConverter.formatUsd(usdAmount);
    }
    return CurrencyConverter.formatCrypto(amount, ticket?.network);
  };

  // Format simulation values
  const formatSimValue = (ethValue) => {
    if (!ethValue) return "N/A";

    if (paymentMethod === "paypal") {
      return CurrencyConverter.formatUsd(CurrencyConverter.ethToUsd(ethValue));
    }
    return CurrencyConverter.formatCrypto(ethValue, ticket?.network);
  };

  if (loading) {
    return (
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
        <div className="flex justify-center">
          <LoadingSpinner size="large" />
        </div>
      </div>
    );
  }

  // Only show "Ticket Not Found" if ticket truly doesn't exist after loading completes
  // Otherwise, show errors inline on the page
  if (!loading && !ticket) {
    return (
      <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
        <div className="text-center bg-red-50 border border-red-200 rounded-lg p-8">
          <h2 className="text-2xl font-bold text-gray-900 mb-4">
            Item Not Found
          </h2>
          <p className="text-gray-600 mb-4">
            {error || "The requested item could not be loaded."}
          </p>
          <Link
            to="/explorer"
            className="px-4 py-2 bg-blue-800 text-white rounded-lg hover:bg-blue-900"
          >
            Back to Explorer
          </Link>
        </div>
      </div>
    );
  }

  // If ticket exists but there are errors (like wallet connection), show them inline
  // Don't redirect - show the purchase form with error messages

  // Create fallback blockchainInfo if missing (to prevent crashes)
  const safeBlockchainInfo = blockchainInfo || {
    token_id: ticket?.token_id || tokenId,
    owner: ticket?.owner_address || "Unknown",
    creator: ticket?.creator_address || "Unknown",
    royalty_percentage: ticket?.royalty_percentage || 0,
    metadata_uri: ticket?.metadata_uri || "",
    is_licensed: false,
    blockchain_status: "fallback",
    source: "database_fallback",
  };

  // Show warning if using fallback data
  const isUsingFallbackData =
    safeBlockchainInfo?.blockchain_status === "fallback" ||
    safeBlockchainInfo?.blockchain_status === "partial" ||
    safeBlockchainInfo?.blockchain_status === "unavailable";

  return (
    <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div className="text-center flex-1">
          <div className="flex justify-center mb-4">
            <div className="bg-blue-800 p-3 rounded-full">
              <ShoppingCart className="w-8 h-8 text-white" />
            </div>
          </div>
          <h1 className="text-3xl font-bold text-gray-900 mb-2">
            Purchase {itemNameTitle}
          </h1>
          <p className="text-lg text-gray-600">{itemNameTitle} #{tokenId}</p>
        </div>
        <Link
          to={`/explorer`}
          className="px-4 py-2 text-gray-600 hover:text-gray-800 border border-gray-300 rounded-lg hover:bg-gray-50"
        >
          <ArrowLeft className="w-5 h-5 mr-1 inline" />
          Back to Explorer
        </Link>
      </div>

      {/* Fallback Data Warning */}
      {isUsingFallbackData && (
        <div className="mb-6 bg-yellow-50 border border-yellow-200 rounded-lg p-4">
          <div className="flex items-center">
            <AlertTriangle className="w-5 h-5 text-yellow-600 mr-2" />
            <p className="text-yellow-800 text-sm">
              Using fallback data. Blockchain information may be incomplete.
            </p>
          </div>
        </div>
      )}

      {/* Error Message Display */}
      {error && (
        <div className="mb-6 bg-red-50 border border-red-200 rounded-lg p-4">
          <div className="flex items-center">
            <AlertTriangle className="w-5 h-5 text-red-600 mr-2" />
            <p className="text-red-800 text-sm font-medium">{error}</p>
          </div>
        </div>
      )}

      {/* ✅ Payment Method Restriction Message */}
      {ticket && (() => {
        // ✅ Check if all payment methods are disabled
        if (!enableCrypto && !enablePayPal) {
          return (
            <div className="mb-6 rounded-lg p-4 bg-red-50 border border-red-200">
              <div className="flex items-center">
                <AlertTriangle className="w-5 h-5 text-red-600 mr-2" />
                <p className="text-red-800 text-sm font-medium">
                  All payment methods are currently disabled by the administrator. Please contact support or try again later.
                </p>
              </div>
            </div>
          );
        }

        const isOnChain = ArtworkStatus.isOnChainArtwork(ticket);
        return (
          <div className={`mb-6 rounded-lg p-4 ${isOnChain
            ? "bg-blue-50 border border-blue-200"
            : "bg-green-50 border border-green-200"
            }`}>
            <div className="flex items-center">
              {isOnChain ? (
                <>
                  <Wallet className="w-5 h-5 text-blue-600 mr-2" />
                  <p className="text-blue-800 text-sm font-medium">
                    This {itemNameLower} is registered on blockchain. Crypto payment required.
                  </p>
                </>
              ) : (
                <>
                  <CreditCard className="w-5 h-5 text-green-600 mr-2" />
                  <p className="text-green-800 text-sm font-medium">
                    This {itemNameLower} is registered off-chain. Off-chain payment methods required.
                  </p>
                </>
              )}
            </div>
          </div>
        );
      })()}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Ticket Details */}
        <div className="bg-white rounded-lg shadow-md overflow-hidden">
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
            {/* Get image URL from database (GridFS) instead of IPFS */}
            {(() => {
              const baseUrl = import.meta.env.VITE_BASE_URL_BACKEND || '';
              const cleanBaseUrl = baseUrl.endsWith('/') ? baseUrl.slice(0, -1) : baseUrl;
              const imageUrl = ticket.token_id
                ? `${cleanBaseUrl}/tickets/${ticket.token_id}/image`
                : null;

              return imageUrl ? (
                <>
                  {/* DB Badge - indicates image is fetched from database */}
                  <div className="absolute top-2 right-2 z-20">
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
                    aspectRatio="square"
                    showToast={true}
                    onError={() => {
                      const placeholder = document.querySelector('.image-placeholder');
                      if (placeholder) placeholder.style.display = 'flex';
                    }}
                  />
                  
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

          <div className="p-6">
            <h2 className="text-2xl font-bold text-gray-900 mb-4">
              {ticket.title || `${itemNameTitle} #${tokenId}`}
            </h2>

            {ticket.description && (
              <p className="text-gray-600 mb-4">{ticket.description}</p>
            )}

            <div className="space-y-3">
              <div className="flex justify-between items-center">
                <span className="text-sm text-gray-500">Creator</span>
                <div className="text-right">
                  {/* ✅ For PayPal tickets, show name/email; for crypto, show address */}
                  {ticket.payment_method === "paypal" && (ticket.creator_name || ticket.creator_email) ? (
                    <div className="text-sm text-gray-900">
                      {ticket.creator_name && <div className="font-medium">{ticket.creator_name}</div>}
                      {ticket.creator_email && <div className="text-xs text-gray-500">{ticket.creator_email}</div>}
                    </div>
                  ) : (
                    <span className="text-sm font-mono text-gray-900">
                      {ticket.creator_address
                        ? formatAddress(ticket.creator_address)
                        : ticket.creator_id || "N/A"}
                    </span>
                  )}
                </div>
              </div>

              <div className="flex justify-between items-center">
                <span className="text-sm text-gray-500">Current Owner</span>
                <div className="text-right">
                  {/* ✅ For PayPal tickets, show name/email; for crypto, show address */}
                  {ticket.payment_method === "paypal" && (ticket.owner_name || ticket.owner_email) ? (
                    <div className="text-sm text-gray-900">
                      {ticket.owner_name && <div className="font-medium">{ticket.owner_name}</div>}
                      {ticket.owner_email && <div className="text-xs text-gray-500">{ticket.owner_email}</div>}
                    </div>
                  ) : (
                    // drmfrontend/src/pages/SalePage.jsx - Line 1371-1375

                    <span className="text-sm font-mono text-gray-900">
                      {(() => {
                        // ✅ Priority: blockchain owner > database owner_address > owner_id > fallback
                        if (safeBlockchainInfo.owner && safeBlockchainInfo.owner !== "Unknown") {
                          return formatAddress(safeBlockchainInfo.owner);
                        } else if (ticket.owner_address) {
                          return formatAddress(ticket.owner_address);
                        } else if (ticket.owner_id) {
                          return ticket.owner_id;
                        } else {
                          return "N/A";
                        }
                      })()}
                    </span>
                  )}
                </div>
              </div>

              <div className="flex justify-between items-center">
                <span className="text-sm text-gray-500">{itemNameTitle} Price</span>
                <span className="text-sm font-semibold text-gray-900">
                  {formatPrice(ticket.price)}
                </span>
              </div>

              {!isTicketItem && (
                <div className="flex justify-between items-center">
                  <span className="text-sm text-gray-500">Royalty</span>
                  <span className="text-sm font-semibold text-gray-900">
                    {((safeBlockchainInfo.royalty_percentage || 0) / 100).toFixed(2)}%
                  </span>
                </div>
              )}

              <div className="flex justify-between items-center">
                <span className="text-sm text-gray-500">Sale Type</span>
                <span
                  className={`text-sm px-2 py-1 rounded-full ${
                    // ✅ Check if creator and owner are the same (handle null addresses)
                    (ticket.creator_address && safeBlockchainInfo.owner &&
                      ticket.creator_address.toLowerCase() === safeBlockchainInfo.owner.toLowerCase()) ||
                      (ticket.creator_id && ticket.owner_id &&
                        ticket.creator_id === ticket.owner_id)
                      ? "bg-blue-100 text-blue-800"
                      : "bg-green-100 text-green-800"
                    }`}
                >
                  {(ticket.creator_address && safeBlockchainInfo.owner &&
                    ticket.creator_address.toLowerCase() === safeBlockchainInfo.owner.toLowerCase()) ||
                    (ticket.creator_id && ticket.owner_id &&
                      ticket.creator_id === ticket.owner_id)
                    ? "Primary Sale"
                    : "Secondary Sale"}
                </span>
              </div>

              {ticket.payment_method && (
                <div className="flex justify-between items-center">
                  <span className="text-sm text-gray-500">Listed With</span>
                  <span
                    className={`text-sm px-2 py-1 rounded-full ${ticket.payment_method === "paypal"
                      ? "bg-yellow-100 text-yellow-800"
                      : "bg-blue-100 text-blue-800"
                      }`}
                  >
                    {ticket.payment_method === "paypal" ? (
                      <CreditCard className="w-3 h-3 inline mr-1" />
                    ) : (
                      <Wallet className="w-3 h-3 inline mr-1" />
                    )}
                    {ticket.payment_method === "paypal" ? "PayPal" : "Crypto"}
                  </span>
                </div>
              )}

              
              {/* Blockchain Status - Only show for on-chain tickets */}
              {ArtworkStatus.isOnChainArtwork(ticket) && (
                <div className="flex justify-between items-center">
                  <span className="text-sm text-gray-500">Blockchain Status</span>
                  {(() => {
                    const isLiveStatus =
                      safeBlockchainInfo.blockchain_status === "full";

                    return (
                      <span
                        className={`text-sm px-2 py-1 rounded-full ${isLiveStatus
                          ? "bg-green-100 text-green-800"
                          : "bg-red-100 text-red-800"
                          }`}
                      >
                        {isLiveStatus ? "Live" : "Fallback"}
                      </span>
                    );
                  })()}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Purchase Form */}
        <div className="bg-white rounded-lg shadow-md p-6">
          <h3 className="text-xl font-bold text-gray-900 mb-6">
            Purchase Details
          </h3>

          {!isAuthenticated ? (
            <div className="text-center py-8">
              <AlertTriangle className="w-12 h-12 text-yellow-500 mx-auto mb-4" />
              <h4 className="text-lg font-semibold text-gray-900 mb-2">
                Authentication Required
              </h4>
              <p className="text-gray-600">
                Please log in to purchase this {itemNameLower}.
              </p>
            </div>
          ) : ticket.price <= 0 ? (
            <div className="text-center py-8">
              <AlertTriangle className="w-12 h-12 text-red-500 mx-auto mb-4" />
              <h4 className="text-lg font-semibold text-gray-900 mb-2">
                {itemNameTitle} Price Not Set
              </h4>
              <p className="text-gray-600">
                This {itemNameLower} does not have a price set. Cannot purchase.
              </p>
            </div>
          ) : (
            <>
              {/* Fixed Price Display */}
              <div className="mb-6 p-4 bg-blue-50 border border-blue-200 rounded-lg">
                <h4 className="font-semibold text-blue-900 mb-2">
                  {itemNameTitle} Price
                </h4>
                <div className="text-2xl font-bold text-blue-800">
                  {formatPrice(ticket.price)}
                </div>
                <p className="text-sm text-blue-600 mt-1">
                  This is the fixed price set by the seller
                </p>
              </div>

              <div className="mb-4">
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Payment Method
                </label>
                {(() => {
                  // ✅ Check if all payment methods are disabled
                  if (!enableCrypto && !enablePayPal) {
                    return (
                      <div className="w-full px-4 py-3 border border-red-300 rounded-lg bg-red-50">
                        <p className="text-red-700 text-sm font-medium">
                          All payment methods are currently disabled by the administrator. Please contact support.
                        </p>
                      </div>
                    );
                  }

                  if (ArtworkStatus.isOnChainArtwork(ticket)) {
                    // On-chain tickets: Only crypto available
                    if (!enableCrypto) {
                      return (
                        <div className="w-full px-4 py-3 border border-red-300 rounded-lg bg-red-50">
                          <p className="text-red-700 text-sm font-medium">
                            Crypto payments are currently disabled. This {itemNameLower} requires crypto payment as it is registered on blockchain.
                          </p>
                        </div>
                      );
                    }
                    return (
                      <div className="w-full px-4 py-3 border border-gray-300 rounded-lg bg-gray-50">
                        <span className="text-gray-700">
                          {`MetaMask (Crypto) - Required for on-chain ${itemNameLower}s`}
                        </span>
                      </div>
                    );
                  } else {
                    // Off-chain tickets: Show ONLY off-chain payment methods (PayPal, etc.)
                    if (!enablePayPal) {
                      return (
                        <div className="w-full px-4 py-3 border border-red-300 rounded-lg bg-red-50">
                          <p className="text-red-700 text-sm font-medium">
                            Off-chain payment methods are currently disabled by the administrator. Please contact support.
                          </p>
                        </div>
                      );
                    }
                    return (
                      <>
                        <select
                          value={paymentMethod}
                          onChange={(e) => setPaymentMethod(e.target.value)}
                          className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-800 focus:border-blue-800"
                        >
                          {/* ✅ For buyers: PayPal is always available if enabled by admin */}
                          {/* Buyer doesn't need to be onboarded - direct checkout works */}
                          {enablePayPal && (
                            <option value="paypal">PayPal</option>
                          )}
                          {!enablePayPal && (
                            <option value="">No payment methods available</option>
                          )}
                        </select>
                        <p className="text-sm text-gray-500 mt-1">
                          {paymentMethod === "paypal"
                            ? "Pay with PayPal - Direct checkout, no account needed"
                            : "Select a payment method"}
                        </p>
                      </>
                    );
                  }
                })()}
              </div>


              {/* Simulation Results */}
              {simulationResults && simulationResults.isValid && (
                <div className="bg-gray-50 p-4 rounded-lg mb-6">
                  <h4 className="font-semibold text-gray-900 mb-3">
                    Transaction Breakdown
                    {!simulationResults.isPrimarySale && (
                      <span className="ml-2 text-xs font-normal text-orange-600 bg-orange-100 px-2 py-1 rounded">
                        Secondary Sale
                      </span>
                    )}
                  </h4>
                  <div className="space-y-2 text-sm">
                    <div className="flex justify-between">
                      <span className="text-gray-600">Sale Price:</span>
                      <span className="font-mono">
                        {formatSimValue(simulationResults.salePrice)}
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-gray-600">Platform Fee ({(platformFeeRate * 100).toFixed(2)}%):</span>
                      <span className="font-mono text-blue-600">
                        +{formatSimValue(simulationResults.buyerPlatformFee)}
                      </span>
                    </div>
                    {!isTicketItem && !simulationResults.isPrimarySale && simulationResults.royaltyAmount > 0 && (
                      <div className="text-xs text-gray-500 italic pt-1">
                        Note: Creator royalty ({simulationResults.royaltyRate}%) will be deducted from seller's amount
                      </div>
                    )}
                    <div className="border-t pt-2 mt-2">
                      <div className="flex justify-between font-semibold">
                        <span className="text-gray-900">Total Amount:</span>
                        <span className="font-mono text-green-600">
                          {formatSimValue(simulationResults.buyerTotal)}
                        </span>
                      </div>
                      <p className="text-xs text-gray-500 mt-1">
                        This is the total amount you will pay
                      </p>
                    </div>
                    {paymentMethod === "crypto" && (
                      <div className="border-t pt-2 mt-2">
                        <div className="flex justify-between items-center">
                          <div>
                            <span className="text-gray-600 text-xs">Gas Fee:</span>
                            <p className="text-xs text-gray-500 italic mt-0.5">
                              Will be added at transaction time
                            </p>
                          </div>
                          <span className="font-mono text-gray-500 text-xs">
                            ~{CurrencyConverter.formatCrypto(gasEstimate, ticket?.network)}
                          </span>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {paymentMethod === "crypto" && (
                <div className="mb-4 p-3 bg-gray-50 rounded-lg">
                  <div className="space-y-2">
                    <div className="flex justify-between items-center">
                      <span className="text-sm text-gray-600">Your balance:</span>
                      <span className="text-sm font-mono font-medium text-gray-900">
                        {balance} {CurrencyConverter.getSymbol(ticket?.network)}
                      </span>
                    </div>
                    {ticket.price > 0 && simulationResults && (
                      <>
                        <div className="flex justify-between items-center pt-2 border-t">
                          <span className="text-sm text-gray-600">Total Payment:</span>
                          <span className="text-sm font-mono font-semibold text-green-600">
                            {CurrencyConverter.formatCrypto(
                              simulationResults.buyerTotal, ticket?.network
                            )}
                          </span>
                        </div>
                        <div className="flex justify-between items-center">
                          <span className="text-sm text-gray-600">+ Estimated Gas Fee:</span>
                          <span className="text-sm font-mono text-gray-500">
                            ~{CurrencyConverter.formatCrypto(gasEstimate, ticket?.network)}
                          </span>
                        </div>
                        <div className="flex justify-between items-center pt-2 border-t">
                          <span className="text-sm font-medium text-gray-900">Total Required:</span>
                          <span className="text-sm font-mono font-semibold text-blue-600">
                            {CurrencyConverter.formatCrypto(
                              (simulationResults.buyerTotal) + gasEstimate, ticket?.network
                            )}
                          </span>
                        </div>
                        <p className="text-xs text-gray-500 mt-1 italic">
                          Gas fee is estimated and may vary at transaction time
                        </p>
                      </>
                    )}
                  </div>
                </div>
              )}

              <Button
                onClick={handlePurchase}
                disabled={purchasing || ticket.price <= 0}
                variant="contained"
                color="primary"
                fullWidth
                size="large"
                className="py-3"
              >
                {purchasing ? (
                  <div className="flex items-center justify-center">
                    <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></div>
                    <span>Processing Purchase...</span>
                  </div>
                ) : (
                  <div className="flex items-center justify-center">
                    {paymentMethod === "crypto" ? (
                      <Wallet className="w-5 h-5 mr-2" />
                    ) : (
                      <CreditCard className="w-5 h-5 mr-2" />
                    )}
                    {(() => {
                      // ✅ Calculate total amount (Sale Price + Platform Fee)
                      const totalAmount = simulationResults
                        ? (simulationResults.buyerTotal)
                        : ticket.price;

                      return `Purchase ${itemNameTitle} for ${formatPrice(totalAmount)} (${paymentMethod === "crypto" ? "Crypto" : "PayPal"})`;
                    })()}
                  </div>
                )}
              </Button>

              <div className="mt-4 text-xs text-gray-500 text-center">
                <p>
                  By purchasing this {itemNameLower}, you agree to the platform's terms and
                  conditions.
                </p>
                <p className="mt-1">
                  Transaction fees will be deducted automatically.
                </p>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Additional Information */}
      <div className="mt-8 bg-blue-50 border border-blue-200 rounded-lg p-6">
        <div className="flex items-start">
          <CheckCircle className="w-6 h-6 text-blue-800 mt-0.5 mr-3" />
          <div>
            <h4 className="text-lg font-semibold text-blue-900 mb-2">
              Secure Transaction
            </h4>
            <p className="text-blue-800 mb-2">
              This transaction is secured by{" "}
              {paymentMethod === "crypto"
                ? "blockchain technology and smart contracts"
                : "PayPal's secure payment system"}
              .
            </p>
            <ul className="text-sm text-blue-700 space-y-1">
              <li>• {isTicketItem ? "Ticket ownership transfer" : "Ownership transfer"} is automatic upon payment</li>
              <li>• {isTicketItem ? "Applicable ticket fee rules" : "Creator royalties"} are distributed automatically</li>
              <li>• Transaction is permanently recorded</li>
              <li>• Platform fees support continued development</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
};

export default SalePage;
