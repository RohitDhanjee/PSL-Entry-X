// frontend/src/utils/web3Utils.js
import Web3 from 'web3';

export const web3Utils = {
  // Convert ETH to Wei (for sending transactions)
  ethToWei: (ethAmount) => {
    return Web3.utils.toWei(ethAmount.toString(), 'ether');
  },
  
  // Convert Wei to ETH (for displaying balances)
  weiToEth: (weiAmount) => {
    return Web3.utils.fromWei(weiAmount.toString(), 'ether');
  },
  
  // Format ETH for display
  formatEth: (ethAmount) => {
    return parseFloat(ethAmount).toFixed(4);
  },
  
  // Validate Ethereum address
  isValidAddress: (address) => {
    return Web3.utils.isAddress(address);
  },
  
  // Convert to checksum address
  toChecksumAddress: (address) => {
    return Web3.utils.toChecksumAddress(address);
  },
  
  // Format address for display
  formatAddress: (address) => {
    if (!address) return '';
    return `${address.substring(0, 6)}...${address.substring(address.length - 4)}`;
  }
};