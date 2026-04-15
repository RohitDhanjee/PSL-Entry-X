import React, { useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useLocation } from 'react-router-dom';

// Different animation variants for different route types
const getPageVariants = (pathname) => {
  // Dashboard routes - slide from right
  if (pathname.includes('/dashboard') || pathname.includes('/admin')) {
    return {
      initial: {
        opacity: 0,
        x: 20,
      },
      in: {
        opacity: 1,
        x: 0,
      },
      out: {
        opacity: 0,
        x: -20,
      }
    };
  }
  
  // Default - fade with slight scale
  return {
    initial: {
      opacity: 0,
      y: 20,
      scale: 0.98
    },
    in: {
      opacity: 1,
      y: 0,
      scale: 1
    },
    out: {
      opacity: 0,
      y: -20,
      scale: 0.98
    }
  };
};

const pageTransition = {
  type: 'tween',
  ease: [0.43, 0.13, 0.23, 0.96], // Custom cubic-bezier for smoother animation
  duration: 0.4
};

const PageTransition = ({ children }) => {
  const location = useLocation();
  const pageVariants = getPageVariants(location.pathname);

  // Scroll to top on route change (with slight delay for smoother transition)
  useEffect(() => {
    const timer = setTimeout(() => {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }, 100);
    return () => clearTimeout(timer);
  }, [location.pathname]);

  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.div
        key={location.pathname}
        initial="initial"
        animate="in"
        exit="out"
        variants={pageVariants}
        transition={pageTransition}
        className="w-full"
        style={{ willChange: 'transform, opacity' }} // Optimize for animations
      >
        {children}
      </motion.div>
    </AnimatePresence>
  );
};

export default PageTransition;

