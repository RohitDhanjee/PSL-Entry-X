import { useState, useEffect, useRef } from 'react';

/**
 * Hook to load image and render on canvas to prevent direct URL access
 * Returns canvas element ready to be rendered
 */
export const useCanvasImage = (imageUrl) => {
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [imageDimensions, setImageDimensions] = useState({ width: 0, height: 0 });
  const canvasRef = useRef(null);
  const blobUrlRef = useRef(null);

  useEffect(() => {
    if (!imageUrl) {
      setIsLoading(false);
      return;
    }

    let isMounted = true;

    const loadImageOnCanvas = async () => {
      try {
        setIsLoading(true);
        setError(null);

        // Normalize legacy singular endpoint to current plural endpoint.
        let finalImageUrl = imageUrl;
        const legacyEndpointMatch = imageUrl?.match(/\/ticket\/([^/]+)\/image(\?.*)?$/);
        if (legacyEndpointMatch) {
          const artworkId = legacyEndpointMatch[1];
          const query = legacyEndpointMatch[2] || '';
          const baseUrl = imageUrl.split('/ticket')[0];
          finalImageUrl = `${baseUrl}/tickets/${artworkId}/image${query}`;
        }

        // Add auth token if available (for access-level detection)
        const authToken = localStorage.getItem('token') || sessionStorage.getItem('token');
        const fetchHeaders = { 'Accept': 'image/*' };
        if (authToken) {
          fetchHeaders['Authorization'] = `Bearer ${authToken}`;
        }

        // Fetch image using the backend endpoint
        const response = await fetch(finalImageUrl, {
          credentials: 'omit',
          mode: 'cors',
          headers: fetchHeaders
        });

        if (!response.ok) {
          throw new Error(`Failed to load image: ${response.status}`);
        }

        const blob = await response.blob();

        if (!blob || blob.size === 0) {
          throw new Error('Empty image blob received');
        }

        // Create object URL from blob
        const objectUrl = URL.createObjectURL(blob);
        blobUrlRef.current = objectUrl;

        // Load image and draw on canvas
        const img = new Image();
        // Remove crossOrigin for same-origin requests to avoid CORS issues
        // img.crossOrigin = 'anonymous';

        img.onload = () => {
          if (!isMounted) {
            URL.revokeObjectURL(objectUrl);
            return;
          }

          // Function to render canvas
          const renderCanvas = () => {
            if (!isMounted || !canvasRef.current) {
              return;
            }

            const canvas = canvasRef.current;
            const container = canvas.parentElement;

            if (!container) {
              console.warn('Canvas container not found');
              setIsLoading(false);
              return;
            }

            // Get container dimensions
            let containerWidth = container.clientWidth || container.offsetWidth || 400;
            let containerHeight = container.clientHeight || container.offsetHeight || 400;

            // Ensure minimum dimensions
            if (containerWidth === 0) containerWidth = 400;
            if (containerHeight === 0) containerHeight = 400;

            // Set canvas display size (CSS)
            canvas.style.width = `${containerWidth}px`;
            canvas.style.height = `${containerHeight}px`;

            // Set canvas internal resolution (for quality)
            const scale = window.devicePixelRatio || 1;
            canvas.width = containerWidth * scale;
            canvas.height = containerHeight * scale;

            const ctx = canvas.getContext('2d', {
              willReadFrequently: false,
              alpha: true
            });

            // Scale context for high DPI displays
            ctx.scale(scale, scale);

            // Clear canvas
            ctx.clearRect(0, 0, containerWidth, containerHeight);

            // Calculate aspect ratio and draw image to fill canvas
            const imgAspect = img.width / img.height;
            const containerAspect = containerWidth / containerHeight;

            let drawWidth, drawHeight, offsetX = 0, offsetY = 0;

            if (imgAspect > containerAspect) {
              // Image is wider - fit to height
              drawHeight = containerHeight;
              drawWidth = containerHeight * imgAspect;
              offsetX = (containerWidth - drawWidth) / 2;
            } else {
              // Image is taller - fit to width
              drawWidth = containerWidth;
              drawHeight = containerWidth / imgAspect;
              offsetY = (containerHeight - drawHeight) / 2;
            }

            // Draw image on canvas (centered and scaled to cover)
            ctx.drawImage(img, offsetX, offsetY, drawWidth, drawHeight);

            // Store dimensions for responsive sizing
            setImageDimensions({
              width: img.width,
              height: img.height
            });

            setIsLoading(false);
          };

          // Try to render immediately
          renderCanvas();

          // Also try after a small delay in case container isn't ready
          setTimeout(renderCanvas, 100);
        };

        img.onerror = () => {
          if (isMounted) {
            setError('Failed to load image');
            setIsLoading(false);
          }
          URL.revokeObjectURL(objectUrl);
        };

        img.src = objectUrl;

      } catch (err) {
        console.error('Error loading image:', err);
        if (isMounted) {
          setError(err.message || 'Failed to load image');
          setIsLoading(false);
        }
      }
    };

    loadImageOnCanvas();

    // Cleanup function
    return () => {
      isMounted = false;
      if (blobUrlRef.current) {
        URL.revokeObjectURL(blobUrlRef.current);
        blobUrlRef.current = null;
      }
    };
  }, [imageUrl]);

  return {
    canvasRef,
    isLoading,
    error,
    imageDimensions
  };
};