import React, { useState } from 'react';
import { useCanvasImage } from '../../hooks/useCanvasImage';
import { Palette } from 'lucide-react';
import toast from 'react-hot-toast';

const ProtectedImage = ({
  imageUrl,
  alt,
  className = '',
  onError,
  showToast = true,
  aspectRatio = 'square', // 'square', 'auto', or custom
  fallbackToImg = true // Fallback to regular img if canvas fails
}) => {
  const { canvasRef, isLoading, error, imageDimensions } = useCanvasImage(imageUrl);
  const [useFallback, setUseFallback] = useState(false);

  const handleContextMenu = (e) => {
    // Allow right-click but show message
    if (showToast) {
      toast('Save Image option is disabled to protect ticket', {
        duration: 2000,
        icon: '🔒',
      });
    }
    // Don't prevent default - allow right-click
  };

  const handleDragStart = (e) => {
    e.preventDefault();
    return false;
  };

  // Use fallback if error and fallbackToImg is true
  if (error && fallbackToImg && !useFallback) {
    setUseFallback(true);
  }

  // Fallback to regular img tag if canvas fails
  if (useFallback || (error && fallbackToImg)) {
    return (
      <img
        src={imageUrl}
        alt={alt}
        className={`w-full h-full object-cover ${className}`}
        onContextMenu={handleContextMenu}
        onDragStart={handleDragStart}
        onError={() => {
          if (onError) onError();
        }}
        style={{
          userSelect: 'none',
          WebkitUserSelect: 'none',
          MozUserSelect: 'none',
          msUserSelect: 'none',
          WebkitTouchCallout: 'none',
          pointerEvents: 'auto'
        }}
        draggable={false}
      />
    );
  }

  if (error && !fallbackToImg) {
    if (onError) onError();
    return (
      <div className={`flex items-center justify-center bg-gray-100 ${className}`}>
        <Palette className="w-12 h-12 text-gray-400" />
        <p className="text-sm text-gray-500 ml-2">Image unavailable</p>
      </div>
    );
  }

  // Calculate aspect ratio style
  const aspectStyle = aspectRatio === 'square'
    ? { aspectRatio: '1 / 1' }
    : aspectRatio === 'auto' && imageDimensions.width > 0
      ? { aspectRatio: `${imageDimensions.width} / ${imageDimensions.height}` }
      : {};

  return (
    <div
      className={`relative w-full h-full ${className}`}
      style={{
        userSelect: 'none',
        WebkitUserSelect: 'none',
        MozUserSelect: 'none',
        msUserSelect: 'none',
        WebkitTouchCallout: 'none',
        ...aspectStyle
      }}
    >
      {/* Loading skeleton */}
      {isLoading && (
        <div className="absolute inset-0 bg-gray-200 animate-pulse flex items-center justify-center z-10">
          <Palette className="w-8 h-8 text-gray-400" />
        </div>
      )}

      {/* Canvas with image */}
      <canvas
        ref={canvasRef}
        className={`absolute inset-0 ${isLoading ? 'opacity-0' : 'opacity-100'} transition-opacity duration-300`}
        onContextMenu={handleContextMenu}
        onDragStart={handleDragStart}
        style={{
          userSelect: 'none',
          WebkitUserSelect: 'none',
          MozUserSelect: 'none',
          msUserSelect: 'none',
          WebkitTouchCallout: 'none',
          pointerEvents: 'auto',
          display: 'block',
          width: '100%',
          height: '100%',
          objectFit: 'cover',
          imageRendering: 'auto',
          position: 'absolute',
          top: 0,
          left: 0
        }}
      />

      {/* Hidden img removed - was exposing URL in DevTools. Canvas handles display. */}
    </div>
  );
};

export default ProtectedImage;