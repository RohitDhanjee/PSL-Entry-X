require("@nomicfoundation/hardhat-toolbox");
require("dotenv").config();
require("solidity-coverage");

module.exports = {
  solidity: {
    version: "0.8.19",
    settings: {
      optimizer: {
        enabled: true,
        runs: 10000
      },
      viaIR: true
    }
  },
  networks: {
    wirefluidTestnet: {
      url: process.env.WIREFLUID_RPC_URL || "https://evm.wirefluid.com",
      chainId: 92533,
      accounts: process.env.PRIVATE_KEY ? [process.env.PRIVATE_KEY] : [],
      gasPrice: "auto"
    },
    hardhat: {
      chainId: 1337,
      // ✅ Windows fix: Explicitly close connections
      forking: undefined
    }
  },
  paths: {
    sources: "./contracts",
    artifacts: "./artifacts",
    tests: "./test"
  },
  mocha: {
    timeout: 60000,
    // ✅ Windows fix: Exit after tests
    exit: true
  }
};