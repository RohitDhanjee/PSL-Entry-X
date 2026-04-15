/**
 * CacheService.js
 * Centralized utility for managing frontend caches to ensure data consistency
 */

const EXPLORER_CACHE_PREFIX = 'explorer_cache_';
const DASHBOARD_CACHE_KEY = 'dashboard_artworks_cache';

// In-memory cache for Dashboard
const dashboardCache = new Map();

export const cacheService = {
  /**
   * Invalidate all ticket-related caches in the browser
   */
  invalidateAll: () => {
    console.log('🔄 Global Cache Invalidation Triggered');
    
    // 1. Clear LocalStorage caches (Explorer)
    cacheService.invalidateExplorerCache();
    
    // 2. Clear In-memory caches (Dashboard)
    cacheService.invalidateDashboardCache();
    
    // 3. Optional: Trigger a custom event if active components need to know
    window.dispatchEvent(new CustomEvent('ticket-cache-invalidated'));
  },

  /**
   * Specifically invalidate Explorer localStorage caches
   */
  invalidateExplorerCache: () => {
    try {
      console.log('🧹 Scanning LocalStorage for explorer cache keys...');
      
      const allKeys = Object.keys(localStorage);
      const keysToRemove = allKeys.filter(key => key.startsWith(EXPLORER_CACHE_PREFIX));
      
      if (keysToRemove.length === 0) {
        console.log('✅ No explorer cache keys found to remove.');
        return;
      }
      
      console.log(`🗑️ Found ${keysToRemove.length} cache keys to remove.`);
      
      keysToRemove.forEach(key => {
        try {
          localStorage.removeItem(key);
          console.log(`✅ Removed: ${key}`);
        } catch (removeError) {
          console.error(`❌ Failed to remove key ${key}:`, removeError);
        }
      });
      
      console.log('✨ Explorer cache invalidation complete.');
    } catch (e) {
      console.error('❌ Critical failure in invalidateExplorerCache:', e);
    }
  },

  /**
   * Dashboard Tickets Caching (In-memory)
   */
  getDashboardArtworks: (key) => {
    const cached = dashboardCache.get(key);
    if (!cached) return null;
    
    const age = Date.now() - cached.timestamp;
    if (age < 60000) { // 60s TTL
      return cached.data;
    }
    
    dashboardCache.delete(key);
    return null;
  },

  setDashboardArtworks: (key, data) => {
    dashboardCache.set(key, {
      data,
      timestamp: Date.now()
    });
  },

  invalidateDashboardCache: () => {
    console.log('🗑️ Clearing dashboard memory cache');
    dashboardCache.clear();
  }
};

export default cacheService;
