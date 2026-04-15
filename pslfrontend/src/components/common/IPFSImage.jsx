import React, { useState, useEffect, useCallback } from 'react';
import { Palette, WifiOff, RefreshCw, ImageIcon, Database } from 'lucide-react';

// IPFS Gateway utilities
const extractIPFSHash = (ipfsUri) => {
  if (!ipfsUri) return null;
  
  // Handle ipfs:// format
  if (ipfsUri.startsWith('ipfs://')) {
    return ipfsUri.replace('ipfs://', '');
  }
  
  // Handle gateway URLs
  if (ipfsUri.includes('/ipfs/')) {
    const parts = ipfsUri.split('/ipfs/');
    return parts[1].split('/')[0];
  }
  
  // Handle direct hash (CIDv0: Qm..., CIDv1: bafy...)
  if (ipfsUri.startsWith('Qm') || ipfsUri.startsWith('bafy') || ipfsUri.startsWith('bafk')) {
    return ipfsUri;
  }
  
  return null;
};

const getIPFSGateways = (hash) => {
  if (!hash) return [];
  
  return [
    `https://ipfs.io/ipfs/${hash}`,
    `https://gateway.pinata.cloud/ipfs/${hash}`,
    `https://nftstorage.link/ipfs/${hash}`,
    `https://${hash}.ipfs.dweb.link/`,
    `https://cloudflare-ipfs.com/ipfs/${hash}`,
    `https://w3s.link/ipfs/${hash}`,
  ];
};

const IPFSImage = ({ 
  ipfsUri, 
  tokenId,
  hasFallback = true,
  alt = "Ticket", 
  className = "",
  showRetryButton = true,
  showFallbackInfo = false,
  onLoad,
  onError,
  ...props 
}) => {
  const [currentGatewayIndex, setCurrentGatewayIndex] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [hasError, setHasError] = useState(false);
  const [retryCount, setRetryCount] = useState(0);
  const [usingFallback, setUsingFallback] = useState(false);
  const [imageUrl, setImageUrl] = useState(null);

  const hash = extractIPFSHash(ipfsUri);
  const gateways = hash ? getIPFSGateways(hash) : [];
  // Use the same env variable as api.js
  const API_BASE = import.meta.env.VITE_BASE_URL_BACKEND;
  // Ensure API_BASE doesn't already include /api/v1, and construct fallback URL correctly
  const baseUrl = API_BASE?.endsWith('/api/v1') ? API_BASE.replace('/api/v1', '') : API_BASE;
  const fallbackUrl = tokenId && baseUrl ? `${baseUrl}/api/v1/tickets/${tokenId}/image` : null;

  // Define tryFallback FIRST
  const tryFallback = useCallback(() => {
    console.log('Trying fallback...');
    if (hasFallback && fallbackUrl && !usingFallback) {
      console.log('Switching to fallback image:', fallbackUrl);
      setUsingFallback(true);
      setImageUrl(fallbackUrl);
      setIsLoading(true);
      setHasError(false);
    } else {
      console.log('Fallback not available or already tried');
      setIsLoading(false);
      setHasError(true);
      if (onError) {
        onError({
          error: 'All sources failed',
          gateways: gateways.length,
          retries: retryCount,
          fallback_attempted: usingFallback
        });
      }
    }
  }, [hasFallback, fallbackUrl, usingFallback, onError, gateways.length, retryCount]);

  // Then define tryNextGateway which uses tryFallback
  const tryNextGateway = useCallback(() => {
    console.log('Trying next gateway...');
    if (currentGatewayIndex < gateways.length - 1) {
      const nextIndex = currentGatewayIndex + 1;
      console.log('Trying gateway', nextIndex, ':', gateways[nextIndex]);
      setCurrentGatewayIndex(nextIndex);
      setImageUrl(gateways[nextIndex]);
      setIsLoading(true);
    } else {
      console.warn('❌ All IPFS gateways failed for token', tokenId, {
        hash: hash,
        ipfsUri: ipfsUri,
        'Gateways tried': gateways.length,
        'Common reasons': [
          'Content not pinned to IPFS',
          'Network/firewall blocking IPFS',
          'Invalid IPFS hash',
          'Gateway rate limiting',
          'Content expired/removed from IPFS'
        ]
      });
      console.log('All gateways failed, trying fallback');
      tryFallback();
    }
  }, [currentGatewayIndex, gateways, tryFallback, tokenId, hash, ipfsUri]);

  // Then define other functions
  const handleImageLoad = () => {
    console.log('Image loaded successfully:', imageUrl);
    setIsLoading(false);
    setHasError(false);
    if (onLoad) {
      onLoad({ 
        source: usingFallback ? 'database' : 'ipfs',
        url: imageUrl, 
        attempts: currentGatewayIndex + 1,
        using_fallback: usingFallback
      });
    }
  };

  const handleImageError = (event) => {
    const currentBaseUrl = API_BASE?.endsWith('/api/v1') ? API_BASE.replace('/api/v1', '') : API_BASE;
    
    // Extract more error details
    const errorInfo = {
      url: imageUrl,
      usingFallback,
      tokenId,
      fallbackUrl,
      API_BASE,
      baseUrl: currentBaseUrl,
      gatewayIndex: currentGatewayIndex,
      gatewayUrl: gateways[currentGatewayIndex],
      ipfsHash: hash,
      ipfsUri: ipfsUri
    };
    
    // Try to get more details from the event
    if (event && event.target) {
      errorInfo.errorType = event.type;
      errorInfo.targetSrc = event.target.src;
    }
    
    console.error('Image failed to load:', errorInfo);
    
    if (usingFallback) {
      console.error('Fallback also failed. Check:', {
        fallbackUrl,
        'Is backend running?': 'Check http://localhost:8000',
        'Is endpoint correct?': `/api/v1/tickets/${tokenId}/image`
      });
      setIsLoading(false);
      setHasError(true);
      if (onError) {
        onError({
          error: 'Fallback image also failed',
          fallback_attempted: true,
          fallbackUrl
        });
      }
    } else {
      // Log IPFS-specific failure reasons
      console.warn('IPFS Gateway Failed:', {
        gateway: gateways[currentGatewayIndex],
        gatewayIndex: currentGatewayIndex,
        totalGateways: gateways.length,
        ipfsHash: hash,
        'Possible reasons': [
          '1. IPFS content not pinned/available',
          '2. Network/CORS issues',
          '3. Gateway rate limiting',
          '4. Invalid IPFS hash',
          '5. Content never uploaded to IPFS'
        ]
      });
      console.log('Trying next source');
      tryNextGateway();
    }
  };

  const handleRetry = () => {
    console.log('Manual retry triggered');
    setRetryCount(prev => prev + 1);
    setCurrentGatewayIndex(0);
    setUsingFallback(false);
    setHasError(false);
    
    if (hash && gateways.length > 0) {
      console.log('Retrying IPFS');
      setImageUrl(gateways[0]);
    } else if (hasFallback && fallbackUrl) {
      console.log('Retrying fallback');
      setUsingFallback(true);
      setImageUrl(fallbackUrl);
    }
    setIsLoading(true);
  };

  // DEBUG: Log component state
  useEffect(() => {
    if (tokenId) {
      console.log('IPFSImage Debug:', {
        tokenId,
        API_BASE,
        baseUrl,
        fallbackUrl,
        'Expected URL': `http://localhost:8000/api/v1/tickets/${tokenId}/image`,
        hasFallback,
        ipfsUri: ipfsUri,
        hash: hash ? `${hash.substring(0, 20)}...` : null,
        'Hash valid?': hash && (hash.startsWith('Qm') || hash.startsWith('bafy') || hash.startsWith('bafk')),
        gateways: gateways.length,
        'First gateway': gateways[0] || 'N/A'
      });
      
      // Warn if IPFS hash looks invalid
      if (ipfsUri && !hash) {
        console.warn('⚠️ Could not extract IPFS hash from URI:', ipfsUri);
      }
      if (hash && !hash.startsWith('Qm') && !hash.startsWith('bafy') && !hash.startsWith('bafk')) {
        console.warn('⚠️ IPFS hash format looks invalid:', hash);
      }
    }
  }, [tokenId, API_BASE, baseUrl, fallbackUrl, hasFallback, hash, gateways.length, ipfsUri]);

  // Reset when props change
  useEffect(() => {
    console.log('Resetting IPFSImage state');
    setCurrentGatewayIndex(0);
    setIsLoading(true);
    setHasError(false);
    setRetryCount(0);
    setUsingFallback(false);
    
    // Start with IPFS if available, otherwise go straight to fallback
    if (hash && gateways.length > 0) {
      console.log('Starting with IPFS:', gateways[0]);
      setImageUrl(gateways[0]);
    } else if (hasFallback && fallbackUrl) {
      console.log('No IPFS, going straight to fallback:', fallbackUrl);
      setUsingFallback(true);
      setImageUrl(fallbackUrl);
    } else {
      console.log('No image sources available');
      setHasError(true);
      setIsLoading(false);
    }
  }, [ipfsUri, tokenId]);

  // Error state - no URI or hash and no fallback
  if (!imageUrl || hasError) {
    return (
      <div className={`bg-gray-100 rounded-lg overflow-hidden flex flex-col items-center justify-center p-4 ${className}`}>
        <div className="text-center">
          <WifiOff className="w-8 h-8 text-gray-400 mx-auto mb-2" />
          <p className="text-gray-500 text-sm mb-1">Failed to load image</p>
          <p className="text-gray-400 text-xs mb-2">
            {gateways.length > 0 && `IPFS: ${gateways.length} gateways tried`}
            {hasFallback && <span> • Fallback: attempted</span>}
          </p>
          {showRetryButton && (
            <button
              onClick={handleRetry}
              className="flex items-center justify-center text-xs text-purple-500 hover:text-purple-700 mx-auto transition-colors"
            >
              <RefreshCw className="w-3 h-3 mr-1" />
              Retry
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className={`relative rounded-lg overflow-hidden bg-gray-100 ${className}`}>
      {/* Loading state */}
      {isLoading && (
        <div className="absolute inset-0 flex items-center justify-center bg-gray-100 z-10">
          <div className="text-center">
            {usingFallback ? (
              <>
                <Database className="w-8 h-8 text-blue-400 mx-auto mb-2 animate-pulse" />
                <p className="text-xs text-gray-500">Loading from database...</p>
              </>
            ) : (
              <>
                <Palette className="w-8 h-8 text-purple-400 mx-auto mb-2 animate-pulse" />
                <p className="text-xs text-gray-500">Loading ticket...</p>
              </>
            )}
            {gateways.length > 1 && !usingFallback && (
              <div className="mt-2 w-16 h-1 bg-gray-200 rounded-full mx-auto overflow-hidden">
                <div 
                  className="h-full bg-purple-400 rounded-full transition-all duration-500"
                  style={{ width: `${((currentGatewayIndex + 1) / gateways.length) * 100}%` }}
                />
              </div>
            )}
          </div>
        </div>
      )}

      {/* Fallback indicator */}
      {showFallbackInfo && usingFallback && !isLoading && (
        <div className="absolute top-2 right-2 z-20">
          <div className="bg-blue-500 text-white text-xs px-2 py-1 rounded-full flex items-center">
            <Database className="w-3 h-3 mr-1" />
            DB
          </div>
        </div>
      )}

      {/* Image */}
      <img
        src={imageUrl}
        alt={alt}
        className={`w-full h-full object-cover transition-opacity duration-300 ${
          isLoading ? 'opacity-0' : 'opacity-100'
        }`}
        onLoad={handleImageLoad}
        onError={handleImageError}
        {...props}
      />
    </div>
  );
};

export default IPFSImage;