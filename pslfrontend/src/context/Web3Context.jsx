import React, { createContext, useContext, useEffect, useMemo, useState } from "react";
import { ethers } from "ethers";
import Web3 from "web3";
import toast from "react-hot-toast";

const Web3Context = createContext();

export const useWeb3 = () => {
  const context = useContext(Web3Context);
  if (!context) {
    throw new Error("useWeb3 must be used within Web3Provider");
  }
  return context;
};

const WIREFLUID_CONFIG = {
  chainId: "0x16975",
  chainIdDecimal: 92533,
  chainName: "WireFluid Testnet",
  nativeCurrency: {
    name: "WIRE",
    symbol: "WIRE",
    decimals: 18,
  },
  rpcUrls: [
    "https://evm.wirefluid.com",
    "https://evm2.wirefluid.com",
    "https://evm3.wirefluid.com",
  ],
  blockExplorerUrls: ["https://wirefluidscan.com"],
  faucetUrl: "https://faucet.wirefluid.com",
  label: "WireFluid Testnet",
  shortLabel: "WireFluid",
  icon: "⚡",
  contractAddress: "0x14bFef74617fe9f3f6a2D53be75448f37e03dE10",
};

const NETWORK_CONFIGS = {
  wirefluid: WIREFLUID_CONFIG,
};

export { NETWORK_CONFIGS };

export const Web3Provider = ({ children }) => {
  const [web3, setWeb3] = useState(null);
  const [ethersProvider, setEthersProvider] = useState(null);
  const [account, setAccount] = useState(null);
  const [chainId, setChainId] = useState(null);
  const [balance, setBalance] = useState("0");
  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [pendingTransactions, setPendingTransactions] = useState(new Set());
  const [selectedNetwork, setSelectedNetworkState] = useState("wirefluid");

  const currentNetworkConfig = WIREFLUID_CONFIG;
  const EXPECTED_CHAIN_ID = WIREFLUID_CONFIG.chainId;
  const EXPECTED_CHAIN_ID_DECIMAL = WIREFLUID_CONFIG.chainIdDecimal;

  const initializeProviders = () => {
    if (typeof window.ethereum === "undefined") {
      return { web3Instance: null, provider: null };
    }

    try {
      const web3Instance = new Web3(window.ethereum);
      const provider = new ethers.BrowserProvider(window.ethereum);
      return { web3Instance, provider };
    } catch (error) {
      console.error("Provider initialization failed:", error);
      return { web3Instance: null, provider: null };
    }
  };

  const web3Utils = {
    toWei: (value, unit = "ether") => {
      if (web3?.utils) return web3.utils.toWei(value.toString(), unit);
      const units = { ether: 1e18, gwei: 1e9, wei: 1, kwei: 1e3, mwei: 1e6 };
      return (parseFloat(value) * (units[unit] || units.ether)).toString();
    },
    fromWei: (value, unit = "ether") => {
      if (web3?.utils) return web3.utils.fromWei(value, unit);
      const units = { ether: 1e18, gwei: 1e9, wei: 1, kwei: 1e3, mwei: 1e6 };
      return (parseFloat(value) / (units[unit] || units.ether)).toString();
    },
    isAddress: (address) => {
      if (web3?.utils) return web3.utils.isAddress(address);
      return /^0x[a-fA-F0-9]{40}$/.test(address || "");
    },
    toHex: (value) => {
      if (web3?.utils) return web3.utils.toHex(value);
      if (typeof value === "number") return `0x${value.toString(16)}`;
      return value;
    },
  };

  const updateBalance = async (accountAddress) => {
    if (!accountAddress) {
      setBalance("0");
      return;
    }

    try {
      if (web3?.eth?.getBalance && web3?.utils?.fromWei) {
        const balanceWei = await web3.eth.getBalance(accountAddress);
        const balanceWire = web3.utils.fromWei(balanceWei, "ether");
        setBalance(parseFloat(balanceWire).toFixed(4));
        return;
      }

      if (typeof window.ethereum !== "undefined") {
        const balanceHex = await window.ethereum.request({
          method: "eth_getBalance",
          params: [accountAddress, "latest"],
        });
        const parsed = Number(BigInt(balanceHex)) / 1e18;
        setBalance(parsed.toFixed(4));
      }
    } catch (error) {
      console.error("Balance update failed:", error);
      setBalance("0");
    }
  };

  const switchNetwork = async () => {
    setSelectedNetworkState("wirefluid");

    if (typeof window.ethereum === "undefined") {
      toast.error("MetaMask not installed");
      return false;
    }

    try {
      await window.ethereum.request({
        method: "wallet_switchEthereumChain",
        params: [{ chainId: WIREFLUID_CONFIG.chainId }],
      });
      toast.success("Switched to WireFluid Testnet");
      return true;
    } catch (switchError) {
      if (switchError?.code === 4902) {
        try {
          await window.ethereum.request({
            method: "wallet_addEthereumChain",
            params: [
              {
                chainId: WIREFLUID_CONFIG.chainId,
                chainName: WIREFLUID_CONFIG.chainName,
                nativeCurrency: WIREFLUID_CONFIG.nativeCurrency,
                rpcUrls: WIREFLUID_CONFIG.rpcUrls,
                blockExplorerUrls: WIREFLUID_CONFIG.blockExplorerUrls,
              },
            ],
          });
          toast.success("WireFluid added and activated");
          return true;
        } catch (addError) {
          console.error("Failed to add WireFluid network:", addError);
          toast.error("Failed to add WireFluid network");
          return false;
        }
      }

      if (switchError?.code === 4001) {
        toast.error("Network switch rejected");
        return false;
      }

      console.error("Network switch failed:", switchError);
      toast.error("Failed to switch to WireFluid");
      return false;
    }
  };

  const connectWallet = async () => {
    setConnecting(true);

    if (typeof window.ethereum === "undefined") {
      toast.error("MetaMask not installed");
      setConnecting(false);
      return false;
    }

    try {
      const accounts = await window.ethereum.request({ method: "eth_requestAccounts" });
      if (!accounts?.length) {
        toast.error("No accounts found");
        return false;
      }

      const switched = await switchNetwork();
      if (!switched) return false;

      const { web3Instance, provider } = initializeProviders();
      if (!web3Instance?.utils) {
        throw new Error("Failed to initialize Web3");
      }

      const currentChainId = await window.ethereum.request({ method: "eth_chainId" });

      setWeb3(web3Instance);
      setEthersProvider(provider);
      setAccount(accounts[0]);
      setChainId(currentChainId);
      setConnected(true);

      await updateBalance(accounts[0]);
      toast.success("Wallet connected on WireFluid");
      return true;
    } catch (error) {
      console.error("Wallet connection failed:", error);
      if (error?.code === 4001) {
        toast.error("Connection rejected by user");
      } else {
        toast.error(error?.message || "Connection failed");
      }
      return false;
    } finally {
      setConnecting(false);
    }
  };

  const refreshBalance = async () => {
    if (account) {
      await updateBalance(account);
    }
  };

  const transferERC721Token = async (contractAddress, toAddress, tokenId) => {
    if (!ethersProvider || !account) {
      throw new Error("Wallet not connected");
    }

    const abi = ["function safeTransferFrom(address from, address to, uint256 tokenId)"];
    const signer = await ethersProvider.getSigner();
    const contract = new ethers.Contract(contractAddress, abi, signer);

    const toastId = toast.loading("Confirm transaction in MetaMask...");
    try {
      const tx = await contract.safeTransferFrom(account, toAddress, tokenId);
      toast.loading("Waiting for blockchain confirmation...", { id: toastId });
      const receipt = await tx.wait();
      toast.success("Transaction confirmed", { id: toastId });
      return { success: true, transactionHash: receipt.hash || receipt.transactionHash, receipt };
    } catch (error) {
      toast.error("Transfer failed", { id: toastId });
      throw new Error(error?.reason || error?.message || "Transfer failed");
    }
  };

  const estimateGasForTransaction = async (transactionData) => {
    try {
      const estimateParams = {
        from: transactionData.from,
        to: transactionData.to,
        value: transactionData.value || "0",
        data: transactionData.data || "0x",
      };
      const estimate = await web3.eth.estimateGas(estimateParams);
      const estimateNum = typeof estimate === "bigint" ? Number(estimate) : parseInt(estimate, 10);
      return Math.floor(estimateNum * 1.25);
    } catch (error) {
      console.warn("Gas estimation failed, using fallback:", error);
      return 300000;
    }
  };

  const getOptimizedGasPrices = async () => {
    try {
      const gasPrice = await web3.eth.getGasPrice();
      const gasPriceNum = typeof gasPrice === "bigint" ? Number(gasPrice) : parseInt(gasPrice, 10);
      return { gasPrice: Math.floor(gasPriceNum * 1.2).toString() };
    } catch {
      return { gasPrice: web3Utils.toWei("30", "gwei").toString() };
    }
  };

  const checkTransactionStatus = async (transactionHash) => {
    try {
      const receipt = await web3.eth.getTransactionReceipt(transactionHash);
      return receipt ? (receipt.status ? "CONFIRMED" : "FAILED") : "PENDING";
    } catch {
      return "UNKNOWN";
    }
  };

  const monitorTransaction = async (transactionHash) => {
    const toastId = toast.loading("Waiting for blockchain confirmation...");
    const timeoutMs = 3 * 60 * 1000;
    const started = Date.now();

    try {
      while (Date.now() - started < timeoutMs) {
        const receipt = await web3.eth.getTransactionReceipt(transactionHash);
        if (receipt) {
          if (receipt.status) {
            toast.success("Transaction confirmed", { id: toastId });
            return { success: true, receipt };
          }
          toast.error("Transaction failed", { id: toastId });
          return { success: false, receipt };
        }
        await new Promise((resolve) => setTimeout(resolve, 3000));
      }
      toast.error("Confirmation taking longer than expected", { id: toastId });
      return { success: false, error: "Timeout" };
    } catch (error) {
      toast.error("Confirmation check failed", { id: toastId });
      return { success: false, error };
    }
  };

  const sendTransaction = async (transactionData) => {
    if (!web3 || !account) {
      throw new Error("Web3 not initialized or wallet not connected");
    }

    if (!transactionData.to || !web3Utils.isAddress(transactionData.to)) {
      throw new Error("Invalid recipient address");
    }

    const gasPrices = await getOptimizedGasPrices();
    const gasLimit = await estimateGasForTransaction(transactionData);

    const txParams = {
      from: account,
      to: transactionData.to,
      value: transactionData.value || "0",
      data: transactionData.data || "0x",
      gas: web3Utils.toHex(gasLimit),
      gasPrice: gasPrices.gasPrice,
    };

    const receipt = await web3.eth.sendTransaction(txParams);
    const transactionHash = receipt.transactionHash || receipt;
    setPendingTransactions((prev) => new Set(prev).add(transactionHash));

    monitorTransaction(transactionHash).finally(() => {
      setPendingTransactions((prev) => {
        const updated = new Set(prev);
        updated.delete(transactionHash);
        return updated;
      });
      updateBalance(account);
    });

    return { hash: transactionHash, receipt };
  };

  const disconnectWallet = () => {
    setAccount(null);
    setConnected(false);
    setBalance("0");
    setWeb3(null);
    setEthersProvider(null);
  };

  useEffect(() => {
    if (typeof window.ethereum === "undefined") {
      return undefined;
    }

    const handleAccountsChanged = (accounts) => {
      if (!accounts.length) {
        disconnectWallet();
        return;
      }
      setAccount(accounts[0]);
      updateBalance(accounts[0]);
    };

    const handleChainChanged = (newChainId) => {
      setChainId(newChainId);
      if (newChainId !== WIREFLUID_CONFIG.chainId) {
        toast.error("Please switch to WireFluid Testnet");
      }
    };

    const autoConnect = async () => {
      try {
        const accounts = await window.ethereum.request({ method: "eth_accounts" });
        if (accounts?.length) {
          const { web3Instance, provider } = initializeProviders();
          const currentChainId = await window.ethereum.request({ method: "eth_chainId" });
          if (web3Instance?.utils) {
            setWeb3(web3Instance);
            setEthersProvider(provider);
            setAccount(accounts[0]);
            setChainId(currentChainId);
            setConnected(true);
            await updateBalance(accounts[0]);
          }
        }
      } catch (error) {
        console.error("Auto-connect failed:", error);
      }
    };

    window.ethereum.on("accountsChanged", handleAccountsChanged);
    window.ethereum.on("chainChanged", handleChainChanged);

    autoConnect();

    return () => {
      window.ethereum.removeListener("accountsChanged", handleAccountsChanged);
      window.ethereum.removeListener("chainChanged", handleChainChanged);
    };
  }, []);

  const isCorrectNetwork = useMemo(() => chainId === EXPECTED_CHAIN_ID, [chainId]);

  return (
    <Web3Context.Provider
      value={{
        web3,
        ethersProvider,
        account,
        chainId,
        balance,
        connected,
        connecting,
        pendingTransactions: Array.from(pendingTransactions),
        web3Utils,
        connectWallet,
        disconnectWallet,
        switchNetwork,
        sendTransaction,
        transferERC721Token,
        checkTransactionStatus,
        updateBalance,
        refreshBalance,
        selectedNetwork,
        setSelectedNetwork: switchNetwork,
        currentNetworkConfig,
        networkConfigs: NETWORK_CONFIGS,
        isCorrectNetwork,
        expectedChainId: EXPECTED_CHAIN_ID,
        expectedChainIdDecimal: EXPECTED_CHAIN_ID_DECIMAL,
        currencySymbol: currentNetworkConfig.nativeCurrency.symbol,
        explorerUrl: currentNetworkConfig.blockExplorerUrls[0],
        faucetUrl: currentNetworkConfig.faucetUrl,
      }}
    >
      {children}
    </Web3Context.Provider>
  );
};
