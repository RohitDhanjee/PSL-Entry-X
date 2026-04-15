const hre = require("hardhat");
const fs = require("fs");
const path = require("path");

async function main() {
  // Detect network
  const networkName = hre.network.name;
  const isWireFluid = networkName === "wirefluidTestnet";
  const networkLabel = isWireFluid ? "WireFluid Testnet" : "Sepolia Testnet";
  const explorerUrl = isWireFluid
    ? "https://wirefluidscan.com/address/"
    : "https://sepolia.etherscan.io/address/";
  const currencySymbol = isWireFluid ? "WIRE" : "ETH";

  console.log("🚀 Starting ArtDRM contract deployment...");
  console.log(`📋 Network: ${networkLabel}\n`);
  
  // Get deployer account
  const [deployer] = await hre.ethers.getSigners();
  console.log("👤 Deploying with account:", deployer.address);
  
  // Check balance
  console.log("🔗 Connecting to provider...");
  const balance = await hre.ethers.provider.getBalance(deployer.address);
  console.log(`💰 Account balance: ${hre.ethers.formatEther(balance)} ${currencySymbol}`);
  
  if (balance < hre.ethers.parseEther("0.01")) {
    console.error(`❌ Insufficient balance! Need at least 0.01 ${currencySymbol} for deployment.`);
    if (isWireFluid) {
      console.error("   Get test WIRE from: https://faucet.wirefluid.com");
    }
    process.exit(1);
  }
  // ✅ Get current gas price
  const feeData = await deployer.provider.getFeeData();
  console.log("Current gas price:", feeData.gasPrice?.toString());
  
  // ✅ Use lower gas price if needed (optional)
  const gasPrice = feeData.gasPrice; // Use current, or set manually: ethers.parseUnits("20", "gwei")
  
  // Deploy contract
  console.log("📦 Deploying XDRM contract...");
  const XDRM = await hre.ethers.getContractFactory("XDRM");
  const xDRM = await XDRM.deploy(); // Let Hardhat/ethers handle gas automatically
  
  console.log("⏳ Waiting for deployment confirmation...");
  await xDRM.waitForDeployment();
  
  const address = await xDRM.getAddress();
  console.log("\n✅ XDRM deployed successfully!");
  console.log("📍 Contract Address:", address);
  console.log(`🔗 Explorer: ${explorerUrl}${address}`);
  
  
  // Save contract address to file
  const contractInfo = {
    address: address,
    network: networkName,
    chainId: isWireFluid ? 92533 : 11155111,
    deployedAt: new Date().toISOString(),
    deployer: deployer.address,
    explorerUrl: `${explorerUrl}${address}`,
  };
  
  const outputPath = path.join(__dirname, "..", "deployment-info.json");
  fs.writeFileSync(outputPath, JSON.stringify(contractInfo, null, 2));
  console.log("\n💾 Deployment info saved to: deployment-info.json");
  
  // Update .env file instructions
  const envVar = isWireFluid ? "WIREFLUID_CONTRACT_ADDRESS" : "CONTRACT_ADDRESS";
  console.log("\n📝 IMPORTANT: Update your .env file with:");
  console.log(`${envVar}=${address}`);
  console.log("\n⚠️  Note: Old contract address will NOT work anymore!");
  console.log(`   You need to update ${envVar} in your .env file`);
  console.log("   and restart your backend server.\n");
}

main()
  .then(() => process.exit(0))
  .catch((error) => {
    console.error("\n❌ Deployment failed:");
    console.error(error);
    process.exit(1);
  });