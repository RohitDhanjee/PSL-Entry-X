import { useEffect, useCallback } from 'react';
import toast from 'react-hot-toast';
import axios from 'axios';

const API_BASE = import.meta.env.VITE_BASE_URL_BACKEND || '';

/**
 * Custom hook to protect ticket images from right-click, drag, keyboard shortcuts,
 * tab switching (blur canvas), and screenshot attempts.
 * @param {boolean} enabled - Enable/disable protection (default: true)
 * @param {number} tokenId - Optional ticket token ID for logging screenshot attempts
 */
export const useImageProtection = (enabled = true, tokenId = null) => {
  useEffect(() => {
    if (!enabled) return;

    // Handle right-click (context menu)
    const handleContextMenu = (e) => {
      // Allow right-click on interactive elements (buttons, links, inputs, etc.)
      if (e.target.closest('button, a, input, textarea, select, [role="button"]')) {
        return;
      }
      
      // Block right-click on images and image containers
      if (e.target.tagName === 'IMG' || e.target.closest('.image-container')) {
        e.preventDefault();
        toast.error('Right-click is disabled to protect ticket', {
          duration: 2000,
          icon: '🔒',
        });
        return false;
      }
    };

    // Helper to instantly hide all canvases and images (faster than CSS blur)
    const applyBlur = () => {
      const canvases = document.querySelectorAll('canvas');
      const imageContainers = document.querySelectorAll('.image-container');
      
      // Use opacity: 0 with transition: none for absolute instant disappearance 
      // without waiting for the GPU to render the blur filter.
      canvases.forEach(canvas => {
        canvas.style.opacity = '0';
        canvas.style.filter = 'blur(50px)'; // secondary protection
        canvas.style.transition = 'none';
      });
      imageContainers.forEach(container => {
        container.style.opacity = '0';
        container.style.transition = 'none';
      });
    };

    // Helper to restore images
    const removeBlur = () => {
      const canvases = document.querySelectorAll('canvas');
      const imageContainers = document.querySelectorAll('.image-container');
      
      canvases.forEach(canvas => {
        canvas.style.opacity = '1';
        canvas.style.filter = 'none';
        canvas.style.transition = 'opacity 0.2s ease, filter 0.2s ease';
      });
      imageContainers.forEach(container => {
        container.style.opacity = '1';
        container.style.transition = 'opacity 0.2s ease';
      });
    };

    // Handle keyboard shortcuts (DevTools, Print Screen, etc.)
    const handleKeyDown = (e) => {
      // Block F12 (DevTools)
      if (e.key === 'F12') {
        e.preventDefault();
        toast.error('Developer tools are disabled', {
          duration: 2000,
          icon: '🔒',
        });
        return false;
      }
      
      // Block Ctrl+Shift+I (DevTools)
      if (e.ctrlKey && e.shiftKey && e.key === 'I') {
        e.preventDefault();
        toast.error('Developer tools are disabled', {
          duration: 2000,
          icon: '🔒',
        });
        return false;
      }
      
      // Block Ctrl+Shift+C (Inspect Element)
      if (e.ctrlKey && e.shiftKey && e.key === 'C') {
        e.preventDefault();
        toast.error('Inspect element is disabled', {
          duration: 2000,
          icon: '🔒',
        });
        return false;
      }
      
      // Block Ctrl+Shift+J (Console)
      if (e.ctrlKey && e.shiftKey && e.key === 'J') {
        e.preventDefault();
        toast.error('Console is disabled', {
          duration: 2000,
          icon: '🔒',
        });
        return false;
      }
      
      // Block Ctrl+U (View Source)
      if (e.ctrlKey && e.key === 'u') {
        e.preventDefault();
        toast.error('View source is disabled', {
          duration: 2000,
          icon: '🔒',
        });
        return false;
      }
      
      // Block Print Screen
      if (e.key === 'PrintScreen') {
        e.preventDefault();
        applyBlur(); // Hide instantly
        toast.error('Screenshots are not allowed', {
          duration: 2000,
          icon: '📸',
        });
        // Log screenshot attempt to backend
        logScreenshotAttempt('printscreen');
        return false;
      }
      
      // Block Ctrl+S (Save Page)
      if (e.ctrlKey && e.key === 's') {
        e.preventDefault();
        toast.error('Saving is disabled to protect ticket', {
          duration: 2000,
          icon: '🔒',
        });
        return false;
      }
      
      // Block Ctrl+P (Print)
      if (e.ctrlKey && e.key === 'p') {
        e.preventDefault();
        toast.error('Printing is disabled to protect ticket', {
          duration: 2000,
          icon: '🔒',
        });
        return false;
      }
      
      // Block Ctrl+Shift+S (Save As)
      if (e.ctrlKey && e.shiftKey && (e.key === 's' || e.key === 'S')) {
        e.preventDefault();
        toast.error('Save As is disabled to protect ticket', {
          duration: 2000,
          icon: '🔒',
        });
        return false;
      }

      // 🚨 PREEMPTIVE HIDE for OS Screenshot shortcuts 🚨
      // Hide instantly the moment they hold Meta(Win/Cmd) + Shift,
      // which happens milliseconds BEFORE they actually press 'S' or '3/4/5'.
      if (e.metaKey && e.shiftKey) {
        applyBlur(); // Instantly hide before OS freezes screen
        
        // Only log if they actually press the final screenshot trigger key
        if (e.key === 's' || e.key === 'S' || ['3', '4', '5'].includes(e.key)) {
          logScreenshotAttempt('os_screenshot_shortcut');
        }
      }
    };

    // Restore image if they abandon the shortcut (release Win or Shift)
    const handleKeyUp = (e) => {
      if (!e.metaKey || !e.shiftKey) {
        // Only restore if the Snipping Tool hasn't stolen window focus
        if (document.hasFocus && document.hasFocus() && !document.hidden) {
          removeBlur();
        }
      }
    };

    // Handle text selection on images
    const handleSelectStart = (e) => {
      if (e.target.tagName === 'IMG' || (e.target.closest && e.target.closest('.image-container'))) {
        e.preventDefault();
        return false;
      }
    };

    // Handle drag and drop
    const handleDragStart = (e) => {
      if (e.target.tagName === 'IMG') {
        e.preventDefault();
        return false;
      }
    };

    // Handle tab visibility change
    const handleVisibilityChange = () => {
      if (document.hidden) {
        applyBlur();
      } else {
        removeBlur();
      }
    };

    // Aggressive Window Blur (when Snipping Tool or OS overlay opens)
    const handleWindowBlur = () => {
      applyBlur();
    };

    const handleWindowFocus = () => {
      if (!document.hidden) {
        removeBlur();
      }
    };

    // Log screenshot attempt to backend (fire-and-forget)
    function logScreenshotAttempt(trigger) {
      if (!tokenId) return;
      try {
        const token = localStorage.getItem('token') || sessionStorage.getItem('token');
        axios.post(
          `${API_BASE}/drm/usage/screenshot-attempt`,
          { token_id: tokenId, trigger },
          token ? { headers: { Authorization: `Bearer ${token}` } } : {}
        ).catch(() => {});
      } catch (e) {
        // Silently fail — this is a best-effort log
      }
    }

    // Add event listeners
    document.addEventListener('contextmenu', handleContextMenu);
    document.addEventListener('keydown', handleKeyDown);
    document.addEventListener('keyup', handleKeyUp);
    document.addEventListener('selectstart', handleSelectStart);
    document.addEventListener('dragstart', handleDragStart);
    document.addEventListener('visibilitychange', handleVisibilityChange);
    // Add aggressive window focus/blur for Snipping Tool overlays
    window.addEventListener('blur', handleWindowBlur);
    window.addEventListener('focus', handleWindowFocus);

    // Cleanup function
    return () => {
      document.removeEventListener('contextmenu', handleContextMenu);
      document.removeEventListener('keydown', handleKeyDown);
      document.removeEventListener('keyup', handleKeyUp);
      document.removeEventListener('selectstart', handleSelectStart);
      document.removeEventListener('dragstart', handleDragStart);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      window.removeEventListener('blur', handleWindowBlur);
      window.removeEventListener('focus', handleWindowFocus);
    };
  }, [enabled, tokenId]);
};