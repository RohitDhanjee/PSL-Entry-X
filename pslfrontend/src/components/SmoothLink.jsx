import React from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';

/**
 * Enhanced Link component with smooth navigation
 * Use this instead of regular Link for better UX
 */
const SmoothLink = ({ 
  to, 
  children, 
  className = '', 
  onClick,
  ...props 
}) => {
  const navigate = useNavigate();

  const handleClick = (e) => {
    e.preventDefault();
    
    // Call custom onClick if provided
    if (onClick) {
      onClick(e);
    }

    // Small delay for visual feedback before navigation
    setTimeout(() => {
      navigate(to);
    }, 50);
  };

  return (
    <Link
      to={to}
      onClick={handleClick}
      className={className}
      {...props}
    >
      {children}
    </Link>
  );
};

export default SmoothLink;

