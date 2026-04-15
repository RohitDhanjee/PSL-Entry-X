import React from "react";
import { useWeb3 } from "../context/Web3Context";

const NetworkSelector = () => {
  const { currentNetworkConfig, connected, isCorrectNetwork } = useWeb3();

  const getStatusColor = () => {
    if (!connected) return "#9ca3af";
    if (isCorrectNetwork) return "#22c55e";
    return "#ef4444";
  };

  return (
    <div style={{ position: "relative", zIndex: 9999 }}>
      <div
        id="network-selector-button"
        style={{
          display: "flex",
          alignItems: "center",
          gap: "6px",
          padding: "6px 12px",
          borderRadius: "8px",
          border: "1px solid #e5e7eb",
          backgroundColor: "#ffffff",
          fontSize: "13px",
          fontWeight: 500,
          color: "#374151",
          whiteSpace: "nowrap",
          boxShadow: "0 1px 2px rgba(0,0,0,0.05)",
        }}
      >
        <span
          style={{
            width: "8px",
            height: "8px",
            borderRadius: "50%",
            backgroundColor: getStatusColor(),
            flexShrink: 0,
          }}
        />
        <span>{currentNetworkConfig.icon}</span>
        <span>{currentNetworkConfig.shortLabel}</span>
      </div>
    </div>
  );
};

export default NetworkSelector;
